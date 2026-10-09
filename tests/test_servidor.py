"""
A API da interface, pelo TestClient do FastAPI. A transcrição é a falsa (conftest),
então uma edição inteira leva alguns segundos.
"""
from __future__ import annotations

import io
import json
import threading
import time
from itertools import pairwise
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from editor import ia, recorte, render, servidor
from tests.conftest import fazer_video

PORTA, TOKEN = 8899, "token-de-teste"
BASE = f"http://127.0.0.1:{PORTA}"
CABECA = {"X-Editor-Token": TOKEN}


@pytest.fixture
def cliente(tmp_path):
    app = servidor.criar_app(TOKEN, porta=PORTA, pasta_saida=tmp_path / "saida")
    with TestClient(app, base_url=BASE) as c:
        yield c


def _enviar(cliente, caminho, nome=None):
    with open(caminho, "rb") as f:
        r = cliente.post("/api/videos", headers=CABECA,
                         files={"arquivo": (nome or caminho.name, f, "video/mp4")})
    assert r.status_code == 200, r.text
    return r.json()


def _esperar(cliente, tid, limite=60.0):
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        t = cliente.get(f"/api/tarefas/{tid}", headers=CABECA).json()
        if t["estado"] != "rodando":
            return t
        time.sleep(0.2)
    raise AssertionError("a edição não terminou a tempo")


class TestSoQuemAbriu:
    def test_sem_token_recusa(self, cliente):
        assert cliente.get("/api/estado").status_code == 401
        assert cliente.get("/api/estado", headers={"X-Editor-Token": "outro"}).status_code == 401

    def test_token_na_url_vale(self, cliente):
        assert cliente.get(f"/api/estado?t={TOKEN}").status_code == 200

    def test_site_de_fora_e_recusado(self, cliente):
        r = cliente.get("/api/estado", headers={**CABECA, "Origin": "https://site-qualquer.com"})
        assert r.status_code == 403

    def test_host_estranho_e_recusado(self, tmp_path):
        """Um site de fora pode apontar um domínio para 127.0.0.1 (DNS rebinding):
        o Host da requisição denuncia."""
        app = servidor.criar_app(TOKEN, porta=PORTA, pasta_saida=tmp_path)
        with TestClient(app, base_url="http://malicioso.com") as c:
            assert c.get("/api/estado", headers=CABECA).status_code == 403

    def test_a_pagina_abre_sem_token(self, cliente):
        assert cliente.get("/").status_code == 200


class TestOFluxo:
    def test_estado(self, cliente):
        e = cliente.get("/api/estado", headers=CABECA).json()
        assert "mp4" in e["formatos"] and e["padroes"]["saida"]["formato"] == "mp4"
        assert any(m["nome"] == "small" for m in e["modelos"])

    def test_envio_com_espaco_e_acento_no_nome(self, cliente, tmp_path):
        v = _enviar(cliente, fazer_video(tmp_path / "x.mp4"), nome="meu vídeo: final?.mp4")
        assert v["nome"] == "meu vídeo_ final_.mp4"
        assert (v["largura"], v["altura"], v["vertical"]) == (320, 568, True)

    def test_arquivo_que_nao_e_video(self, cliente, tmp_path):
        falso = tmp_path / "nota.txt"
        falso.write_text("não sou vídeo")
        with open(falso, "rb") as f:
            r = cliente.post("/api/videos", headers=CABECA, files={"arquivo": ("nota.mp4", f)})
        assert r.status_code == 400

    def test_quadro_para_a_thumbnail(self, cliente, tmp_path):
        v = _enviar(cliente, fazer_video(tmp_path / "x.mp4"))
        r = cliente.get(f"/api/videos/{v['id']}/quadro?segundo=1.2&largura=200&t={TOKEN}")
        assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
        assert Image.open(io.BytesIO(r.content)).size[0] == 200
        auto = cliente.get(f"/api/videos/{v['id']}/quadro-automatico", headers=CABECA).json()
        assert 0 <= auto["t"] <= 3

    def test_edita_baixa_e_salva_thumbnail(self, cliente, tmp_path):
        v = _enviar(cliente, fazer_video(tmp_path / "x.mp4", segundos=4.0))
        r = cliente.post("/api/tarefas", headers=CABECA, json={
            "video_id": v["id"], "edicao": {}, "saida": {"formato": "mp4", "srt": True}})
        assert r.status_code == 200, r.text
        t = _esperar(cliente, r.json()["id"])
        assert t["estado"] == "pronto", t
        tid = t["id"]
        video = cliente.get(f"/api/tarefas/{tid}/arquivo/video", headers=CABECA)
        assert video.status_code == 200 and len(video.content) > 1000
        assert "attachment" in video.headers["content-disposition"]
        assert cliente.get(f"/api/tarefas/{tid}/arquivo/srt", headers=CABECA).status_code == 200
        plano = cliente.get(f"/api/tarefas/{tid}/arquivo/plano?inline=1", headers=CABECA).json()
        assert plano["blocos"]

        png = io.BytesIO()
        Image.new("RGB", (1280, 720), (255, 212, 0)).save(png, "PNG")
        r = cliente.post(f"/api/tarefas/{tid}/thumbnail", headers=CABECA,
                         data={"nome": "1280x720"}, files={"imagem": ("t.png", png.getvalue())})
        assert r.status_code == 200, r.text
        saida = tmp_path / "saida"
        assert (saida / r.json()["png"]).is_file() and (saida / r.json()["jpg"]).is_file()
        assert r.json()["jpg_bytes"] <= servidor.JPG_MAXIMO
        baixada = cliente.get(f"/api/tarefas/{tid}/arquivo/{r.json()['png']}", headers=CABECA)
        assert baixada.status_code == 200

    def test_nome_de_thumbnail_estranho_e_recusado(self, cliente, tmp_path):
        v = _enviar(cliente, fazer_video(tmp_path / "x.mp4", segundos=2.0))
        tid = cliente.post("/api/tarefas", headers=CABECA,
                           json={"video_id": v["id"]}).json()["id"]
        _esperar(cliente, tid)
        r = cliente.post(f"/api/tarefas/{tid}/thumbnail", headers=CABECA,
                         data={"nome": "../../fora"}, files={"imagem": ("t.png", b"x")})
        assert r.status_code == 422

    def test_opcao_invalida_volta_com_o_motivo(self, cliente, tmp_path):
        v = _enviar(cliente, fazer_video(tmp_path / "x.mp4"))
        r = cliente.post("/api/tarefas", headers=CABECA,
                         json={"video_id": v["id"], "saida": {"formato": "webm", "codec": "h264"}})
        assert r.status_code == 422 and "não aceita o codec" in r.json()["detail"]


class TestUmaPorVez:
    def test_segunda_edicao_espera(self, cliente, tmp_path, monkeypatch):
        liberar = threading.Event()

        def lenta(*_a, **_k):
            liberar.wait(10)
            raise render.Cancelado

        monkeypatch.setattr(render, "editar", lenta)
        v = _enviar(cliente, fazer_video(tmp_path / "x.mp4", segundos=1.0))
        primeira = cliente.post("/api/tarefas", headers=CABECA, json={"video_id": v["id"]})
        segunda = cliente.post("/api/tarefas", headers=CABECA, json={"video_id": v["id"]})
        liberar.set()
        assert primeira.status_code == 200 and segunda.status_code == 409


class TestAThumbnailComIA:
    def test_estado(self, cliente):
        e = cliente.get("/api/estado", headers=CABECA).json()
        assert e["ia"]["configurada"] and e["ia"]["origem"] == "falsa"
        assert e["recorte"]["baixado"] and e["recorte"]["tamanho"] == recorte.TAMANHO

    def test_salvar_e_apagar_a_chave(self, cliente, monkeypatch):
        monkeypatch.delenv(ia.VARIAVEL_FALSA)
        monkeypatch.setattr(ia, "validar_chave", lambda valor: ia.limpar_chave(valor))
        chave = "AIzaSy" + "x" * 29 + "9876"
        r = cliente.put("/api/ia/chave", headers=CABECA, json={"chave": chave})
        assert r.status_code == 200, r.text
        assert r.json()["configurada"] and r.json()["final"] == "…9876"
        assert chave not in r.text and chave not in cliente.get("/api/estado",
                                                                headers=CABECA).text
        assert cliente.delete("/api/ia/chave", headers=CABECA).json()["configurada"] is False

    def test_chave_recusada_volta_com_o_motivo(self, cliente, monkeypatch):
        def recusa(valor):
            raise ia.ErroDaIA("O Google recusou esta chave.")

        monkeypatch.setattr(ia, "validar_chave", recusa)
        r = cliente.put("/api/ia/chave", headers=CABECA, json={"chave": "x" * 30})
        assert r.status_code == 422 and "recusou" in r.json()["detail"]

    def test_ideias_depois_da_edicao(self, cliente, tmp_path):
        v = _enviar(cliente, fazer_video(tmp_path / "x.mp4", segundos=4.0))
        tid = cliente.post("/api/tarefas", headers=CABECA,
                           json={"video_id": v["id"]}).json()["id"]
        assert _esperar(cliente, tid)["estado"] == "pronto"
        r = cliente.post(f"/api/tarefas/{tid}/thumbs-ia", headers=CABECA,
                         json={"evitar": ["Uma chamada antiga"]})
        assert r.status_code == 200, r.text
        variantes = r.json()["variantes"]
        assert len(variantes) == 3
        assert all(0 <= x["t"] <= 4.0 and x["chamada"] for x in variantes)

    def test_erro_da_ia_chega_na_pagina(self, cliente, tmp_path, monkeypatch):
        def sem_cota(*_a, **_k):
            raise ia.ErroDaIA("A cota grátis do Gemini acabou por hoje.")

        monkeypatch.setattr(ia, "sugerir", sem_cota)
        v = _enviar(cliente, fazer_video(tmp_path / "x.mp4", segundos=2.0))
        tid = cliente.post("/api/tarefas", headers=CABECA,
                           json={"video_id": v["id"]}).json()["id"]
        _esperar(cliente, tid)
        r = cliente.post(f"/api/tarefas/{tid}/thumbs-ia", headers=CABECA, json={})
        assert r.status_code == 502 and "cota" in r.json()["detail"]

    def test_recorte(self, cliente, tmp_path):
        v = _enviar(cliente, fazer_video(tmp_path / "x.mp4"))
        info = cliente.get(f"/api/videos/{v['id']}/recorte?segundo=1", headers=CABECA).json()
        assert info["ok"] and info["rosto"]["y1"] < info["pessoa"]["y1"]
        r = cliente.get(f"/api/videos/{v['id']}/recorte.png?segundo=1&largura=200&t={TOKEN}")
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"
        with Image.open(io.BytesIO(r.content)) as im:
            assert im.mode == "RGBA" and im.width == 200
            assert im.getpixel((0, 0))[3] == 0                 # o canto é fundo

    def test_fontes(self, cliente):
        for nome in servidor.FONTES:
            assert cliente.get(f"/fontes/{nome}").status_code == 200
        assert cliente.get("/fontes/..%2Fservidor.py").status_code == 404

    def test_quadros_candidatos(self, tmp_path):
        from editor import video as video_mod

        caminho = fazer_video(tmp_path / "x.mp4", segundos=6.0, largura=640, altura=1136)
        quadros = servidor.quadros_candidatos(caminho, video_mod.sondar(caminho), n=4)
        tempos = [t for t, _ in quadros]
        assert len(quadros) == 4 and tempos == sorted(tempos)
        assert all(b - a >= 6.0 / 12 for a, b in pairwise(tempos))
        with Image.open(io.BytesIO(quadros[0][1])) as im:
            assert im.format == "JPEG" and max(im.size) == 512


class TestOFundoDaThumbnail:
    def test_estado(self, cliente):
        e = cliente.get("/api/estado", headers=CABECA).json()
        assert e["pexels"]["configurada"] and e["geracao"]["restantes"] == 10

    def test_enviar_imagem(self, cliente):
        png = io.BytesIO()
        Image.new("RGB", (640, 360), (0, 120, 200)).save(png, "PNG")
        r = cliente.post("/api/imagens", headers=CABECA,
                         files={"arquivo": ("fundo.png", png.getvalue(), "image/png")})
        assert r.status_code == 200, r.text
        info = r.json()
        assert (info["largura"], info["origem"]) == (640, "envio")
        foto = cliente.get(f"{info['url']}?t={TOKEN}")
        assert foto.status_code == 200 and foto.headers["content-type"] == "image/jpeg"

    def test_imagem_que_nao_e_imagem(self, cliente):
        r = cliente.post("/api/imagens", headers=CABECA,
                         files={"arquivo": ("x.png", b"texto", "image/png")})
        assert r.status_code == 400 and "imagem" in r.json()["detail"]

    def test_pexels(self, cliente):
        fotos = cliente.post("/api/pexels/buscar", headers=CABECA,
                             json={"consulta": "estúdio", "orientacao": "paisagem"}).json()["fotos"]
        assert fotos and "previa" not in fotos[0] and "grande" not in fotos[0]
        previa = cliente.get(f"/api/pexels/foto/{fotos[0]['id']}?t={TOKEN}")
        assert previa.status_code == 200 and previa.content[:2] == b"\xff\xd8"
        usada = cliente.post("/api/pexels/usar", headers=CABECA, json={"id": fotos[0]["id"]})
        assert usada.status_code == 200 and "Pexels" in usada.json()["credito"]

    def test_chave_do_pexels_nunca_volta(self, cliente, monkeypatch):
        from editor import pexels

        monkeypatch.delenv(pexels.VARIAVEL_FALSA)
        monkeypatch.setattr(pexels, "validar_chave", lambda v: v.strip())
        chave = "pexels-" + "y" * 30 + "4321"
        r = cliente.put("/api/pexels/chave", headers=CABECA, json={"chave": chave})
        assert r.status_code == 200 and r.json()["final"] == "…4321" and chave not in r.text
        assert cliente.delete("/api/pexels/chave", headers=CABECA).json()["configurada"] is False

    def test_fundo_gerado_nao_paga_duas_vezes(self, cliente):
        pedido = {"cena": "um estúdio colorido", "proporcao": "16:9", "lado": "esquerda"}
        primeira = cliente.post("/api/fundo-gerado", headers=CABECA, json=pedido).json()
        segunda = cliente.post("/api/fundo-gerado", headers=CABECA, json=pedido).json()
        assert primeira["nova"] and not segunda["nova"] and primeira["id"] == segunda["id"]

    def test_maos(self, cliente):
        for nome in servidor.MAOS:
            r = cliente.get(f"/maos/{nome}")
            assert r.status_code == 200 and r.content
        assert cliente.get("/maos/..%2F..%2Fservidor.py").status_code == 404


class TestAMontagem:
    """O fundo e, por cima, a pessoa ou o personagem, pela API."""

    def _enviar_arquivo(self, cliente, rota, caminho, tipo):
        with open(caminho, "rb") as f:
            return cliente.post(rota, headers=CABECA, files={"arquivo": (caminho.name, f, tipo)})

    def test_personagem(self, cliente, tmp_path):
        from tests.test_montagem import gif

        r = self._enviar_arquivo(cliente, "/api/personagens", gif(tmp_path / "b.gif", lado=80),
                                 "image/gif")
        assert r.status_code == 200, r.text
        p = r.json()
        assert (p["quadros"], p["tem_alfa"], p["largura"]) == (4, True, 80)
        quadro = cliente.get(f"/api/personagens/{p['id']}/quadro.png", headers=CABECA)
        assert quadro.status_code == 200
        with Image.open(io.BytesIO(quadro.content)) as im:
            assert im.mode == "RGBA" and im.getpixel((0, 0))[3] == 0
        caixas = cliente.get(f"/api/personagens/{p['id']}/recorte", headers=CABECA).json()
        assert caixas["ok"] and 0 < caixas["pessoa"]["x0"] < 0.3

    def test_personagem_de_fundo_de_cor(self, cliente, tmp_path):
        from tests.test_montagem import gif

        r = self._enviar_arquivo(cliente, "/api/personagens",
                                 gif(tmp_path / "b.gif", transparente=False), "image/gif")
        p = r.json()
        assert (p["tem_alfa"], p["fundo_de_cor"]) == (False, True)
        com_fundo = cliente.get(f"/api/personagens/{p['id']}/quadro.png?tirar_fundo=0",
                                headers=CABECA)
        sem_fundo = cliente.get(f"/api/personagens/{p['id']}/quadro.png?tirar_fundo=1",
                                headers=CABECA)
        with Image.open(io.BytesIO(com_fundo.content)) as a, \
                Image.open(io.BytesIO(sem_fundo.content)) as b:
            assert a.getpixel((0, 0))[3] == 255 and b.getpixel((0, 0))[3] == 0

    def test_personagem_que_nao_e_imagem(self, cliente, tmp_path):
        ruim = tmp_path / "x.gif"
        ruim.write_bytes(b"nada")
        r = self._enviar_arquivo(cliente, "/api/personagens", ruim, "image/gif")
        assert r.status_code == 400 and "GIF" in r.json()["detail"]

    def test_audio(self, cliente, tmp_path):
        from tests.test_montagem import audio_wav

        r = self._enviar_arquivo(cliente, "/api/audios", audio_wav(tmp_path / "n.wav",
                                                                   segundos=2.0), "audio/wav")
        assert r.status_code == 200 and r.json()["duracao"] == pytest.approx(2.0, abs=0.05)
        sem_som = fazer_video(tmp_path / "mudo.mp4", com_audio=False)
        r = self._enviar_arquivo(cliente, "/api/audios", sem_som, "video/mp4")
        assert r.status_code == 400

    def test_video_com_transparencia(self, cliente, tmp_path):
        from tests.test_montagem import video_com_alfa

        assert _enviar(cliente, video_com_alfa(tmp_path / "eu.mov"))["tem_alfa"]
        assert not _enviar(cliente, fazer_video(tmp_path / "v.mp4"))["tem_alfa"]

    def test_recorte_pelo_alfa_do_arquivo(self, cliente, tmp_path, monkeypatch):
        """O vídeo já sem fundo não passa pelo MODNet: o recorte é o alfa dele."""
        from tests.test_montagem import video_com_alfa

        monkeypatch.setattr(recorte, "recortar", lambda m: (_ for _ in ()).throw(
            AssertionError("não devia chamar o modelo")))
        v = _enviar(cliente, video_com_alfa(tmp_path / "eu.mov"))
        info = cliente.get(f"/api/videos/{v['id']}/recorte?segundo=0.3", headers=CABECA).json()
        assert info["ok"] and info["pessoa"]["y1"] > 0.95

    def test_edita_a_montagem_e_pede_ideias(self, cliente, tmp_path):
        from tests.test_montagem import audio_wav, gif

        fundo = _enviar(cliente, fazer_video(tmp_path / "tela.mp4", largura=320, altura=180,
                                             segundos=3.0, com_audio=False))
        boneco = self._enviar_arquivo(cliente, "/api/personagens", gif(tmp_path / "b.gif"),
                                      "image/gif").json()
        narracao = self._enviar_arquivo(cliente, "/api/audios",
                                        audio_wav(tmp_path / "n.wav", segundos=4.0),
                                        "audio/wav").json()
        pedido = {"montagem": {"fundo_id": fundo["id"], "personagem_id": boneco["id"],
                               "audio_id": narracao["id"], "formato": "vertical"},
                  "edicao": {}, "saida": {}}
        r = cliente.post("/api/tarefas", headers=CABECA, json=pedido)
        assert r.status_code == 200, r.text
        t = _esperar(cliente, r.json()["id"])
        assert t["estado"] == "pronto", t
        assert (t["resultado"]["largura"], t["resultado"]["altura"]) == (180, 320)
        assert t["resultado"]["video"].endswith("tela-editado.mp4")
        ideias = cliente.post(f"/api/tarefas/{t['id']}/thumbs-ia", headers=CABECA, json={})
        assert ideias.status_code == 200 and len(ideias.json()["variantes"]) == 3

    def test_transparente_sem_alfa_e_recusado(self, cliente, tmp_path):
        fundo = _enviar(cliente, fazer_video(tmp_path / "tela.mp4"))
        pessoa = _enviar(cliente, fazer_video(tmp_path / "eu.mp4"))
        pedido = {"montagem": {"fundo_id": fundo["id"], "pessoa_id": pessoa["id"],
                               "recorte": "transparente"}, "edicao": {}, "saida": {}}
        r = cliente.post("/api/tarefas", headers=CABECA, json=pedido)
        assert r.status_code == 422 and "transparência" in r.json()["detail"]

    def test_escolhas_de_audio_que_nao_servem(self, cliente, tmp_path):
        from tests.test_montagem import gif

        fundo = _enviar(cliente, fazer_video(tmp_path / "tela.mp4"))
        boneco = self._enviar_arquivo(cliente, "/api/personagens", gif(tmp_path / "b.gif"),
                                      "image/gif").json()
        base = {"fundo_id": fundo["id"], "personagem_id": boneco["id"]}
        for fala, motivo in (("pessoa", "personagem"), ("audio", "nenhum arquivo")):
            r = cliente.post("/api/tarefas", headers=CABECA,
                             json={"montagem": {**base, "fala": fala}, "edicao": {}, "saida": {}})
            assert r.status_code == 422 and motivo in r.json()["detail"], r.text

    def test_o_audio_escolhido_manda_na_duracao(self, cliente, tmp_path):
        from tests.test_montagem import gif

        fundo = _enviar(cliente, fazer_video(tmp_path / "tela.mp4", segundos=2.0))
        boneco = self._enviar_arquivo(cliente, "/api/personagens", gif(tmp_path / "b.gif"),
                                      "image/gif").json()
        pedido = {"montagem": {"fundo_id": fundo["id"], "personagem_id": boneco["id"],
                               "fala": "fundo"}, "edicao": {"cortes": False}, "saida": {}}
        r = cliente.post("/api/tarefas", headers=CABECA, json=pedido)
        assert r.status_code == 200, r.text
        t = _esperar(cliente, r.json()["id"])
        assert t["estado"] == "pronto", t
        assert t["resultado"]["duracao_original"] == pytest.approx(2.0, abs=0.1)

    def test_montagem_sem_nada_por_cima(self, cliente, tmp_path):
        """Por cima pode não ir nada: só o fundo, a legenda e os efeitos."""
        fundo = _enviar(cliente, fazer_video(tmp_path / "tela.mp4", segundos=2.0))
        r = cliente.post("/api/tarefas", headers=CABECA,
                         json={"montagem": {"fundo_id": fundo["id"]}, "edicao": {}, "saida": {}})
        assert r.status_code == 200, r.text
        assert _esperar(cliente, r.json()["id"])["estado"] == "pronto"


class TestPresetsESons:
    def test_o_estado_traz_os_presets_e_os_temas(self, cliente):
        e = cliente.get("/api/estado", headers=CABECA).json()
        assert [p["nome"] for p in e["presets"]][:2] == ["padrao", "gameplay"]
        assert e["temas_dos_sons"]["gameplay"] == "Gameplay"
        assert e["padroes"]["edicao"]["tema_dos_sons"] == "padrao"

    def test_ouvir_um_tema(self, cliente):
        r = cliente.get(f"/api/sons/gameplay.wav?volume=0.8&t={TOKEN}")
        assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
        assert r.content[:4] == b"RIFF" and len(r.content) > 48_000 * 2 * 3

    def test_so_os_temas_do_catalogo(self, cliente):
        assert cliente.get("/api/sons/nao-existe.wav", headers=CABECA).status_code == 404
        assert cliente.get("/api/sons/..%2Fsons.wav", headers=CABECA).status_code == 404
        assert cliente.get("/api/sons/gameplay.wav").status_code == 401

    def test_opcao_nova_invalida_volta_com_o_motivo(self, cliente, tmp_path):
        v = _enviar(cliente, fazer_video(tmp_path / "x.mp4"))
        r = cliente.post("/api/tarefas", headers=CABECA, json={
            "video_id": v["id"], "edicao": {"tema_dos_sons": "rock", "ritmo": 5}})
        assert r.status_code == 422
        assert "ritmo" in r.json()["detail"] and "rock" in r.json()["detail"]

    def test_edita_com_um_preset(self, cliente, tmp_path):
        from editor import presets

        v = _enviar(cliente, fazer_video(tmp_path / "x.mp4", segundos=4.0))
        p = presets.PRESETS["humor"]
        r = cliente.post("/api/tarefas", headers=CABECA, json={
            "video_id": v["id"], "edicao": p.edicao, "saida": {"formato": "mp4", **p.saida}})
        assert r.status_code == 200, r.text
        t = _esperar(cliente, r.json()["id"])
        assert t["estado"] == "pronto", t
        plano = cliente.get(f"/api/tarefas/{t['id']}/arquivo/plano?inline=1", headers=CABECA).json()
        assert plano["forca_do_empurrao"] == p.edicao["empurrao"]
        assert all(len(b["texto"]) <= 14 for b in plano["blocos"])


class TestBaixarAThumbnail:
    """O botão "Baixar" do passo 5: salva na pasta e entrega como download, antes ou
    depois de editar."""

    def _png(self, largura=1080, altura=1920):
        corpo = io.BytesIO()
        Image.new("RGB", (largura, altura), (0, 194, 255)).save(corpo, "PNG")
        return corpo.getvalue()

    def test_antes_de_editar_leva_o_nome_do_video(self, cliente, tmp_path):
        v = _enviar(cliente, fazer_video(tmp_path / "x.mp4"), nome="minha aula.mp4")
        r = cliente.post("/api/thumbnails", headers=CABECA,
                         data={"tamanho": "1080x1920", "video_id": v["id"]},
                         files={"imagem": ("t.png", self._png())})
        assert r.status_code == 200, r.text
        assert r.json()["jpg"] == "minha aula-thumb-1080x1920.jpg"
        assert r.json()["jpg_bytes"] <= servidor.JPG_MAXIMO
        assert (tmp_path / "saida" / "minha aula-thumb-1080x1920.png").is_file()
        baixada = cliente.get(f"/api/thumbnails/{r.json()['jpg']}", headers=CABECA)
        assert baixada.status_code == 200 and "attachment" in baixada.headers["content-disposition"]
        assert Image.open(io.BytesIO(baixada.content)).size == (1080, 1920)

    def test_depois_de_editar_leva_o_nome_do_editado(self, cliente, tmp_path):
        v = _enviar(cliente, fazer_video(tmp_path / "x.mp4", segundos=2.0))
        tid = cliente.post("/api/tarefas", headers=CABECA, json={"video_id": v["id"]}).json()["id"]
        assert _esperar(cliente, tid)["estado"] == "pronto"
        r = cliente.post("/api/thumbnails", headers=CABECA,
                         data={"tamanho": "1280x720", "video_id": v["id"], "tarefa_id": tid},
                         files={"imagem": ("t.png", self._png(1280, 720))})
        assert r.status_code == 200, r.text
        assert r.json()["png"] == "x-editado-thumb-1280x720.png"
        t = cliente.get(f"/api/tarefas/{tid}", headers=CABECA).json()
        assert any(c.endswith("x-editado-thumb-1280x720.jpg") for c in t["resultado"]["thumbnails"])

    def test_o_que_nao_vale(self, cliente, tmp_path):
        v = _enviar(cliente, fazer_video(tmp_path / "x.mp4"))
        r = cliente.post("/api/thumbnails", headers=CABECA,
                         data={"tamanho": "../../fora", "video_id": v["id"]},
                         files={"imagem": ("t.png", self._png())})
        assert r.status_code == 422
        r = cliente.post("/api/thumbnails", headers=CABECA,
                         data={"tamanho": "1080x1920", "video_id": v["id"]},
                         files={"imagem": ("t.png", b"nao sou imagem")})
        assert r.status_code == 422
        assert cliente.get("/api/thumbnails/outra.jpg", headers=CABECA).status_code == 404
        assert cliente.get("/api/thumbnails/..%2F..%2Fsegredo", headers=CABECA).status_code == 404


class TestABiblioteca:
    """A biblioteca de cenas pela API: a pasta (um clipe por pedido), a matriz e a edição
    com ela, nada por cima e a narração em dois arquivos."""

    def _clipes(self, tmp_path, nomes=("t1-001", "t1-002", "t1-003")) -> list:
        pasta = tmp_path / "cenas"
        pasta.mkdir(exist_ok=True)
        return [fazer_video(pasta / f"{n}.mp4", largura=320, altura=180, segundos=1.0,
                            com_audio=False) for n in nomes]

    def _abrir(self, cliente, tmp_path, matriz: list | None = None) -> str:
        bid = cliente.post("/api/bibliotecas", headers=CABECA, json={"nome": "cenas"}).json()["id"]
        for c in self._clipes(tmp_path):
            with open(c, "rb") as f:
                r = cliente.post(f"/api/bibliotecas/{bid}/clipes", headers=CABECA,
                                 files={"arquivo": (c.name, f, "video/mp4")})
            assert r.status_code == 200, r.text
        if matriz is not None:
            r = cliente.post(f"/api/bibliotecas/{bid}/matriz", headers=CABECA,
                             files={"arquivo": ("cenas.json", json.dumps(matriz).encode(),
                                                "application/json")})
            assert r.status_code == 200, r.text
        return bid

    MATRIZ = (
        {"id": "t1-001", "arquivo": "clipes/t1-001.mp4", "descricao": "explosão",
         "energia": "alta"},
        {"id": "t1-002", "arquivo": "t1-002.mp4", "descricao": "praia"},
        {"id": "t1-003", "arquivo": "t1-003.mp4", "descricao": "boate", "monetizacao": "evitar"},
    )

    def test_a_pasta_e_a_matriz(self, cliente, tmp_path):
        bid = self._abrir(cliente, tmp_path)
        with open(self._clipes(tmp_path)[0], "rb") as f:
            r = cliente.post(f"/api/bibliotecas/{bid}/clipes", headers=CABECA,
                             files={"arquivo": ("leia-me.txt", f, "text/plain")})
        assert r.status_code == 400 and "só vídeos" in r.json()["detail"]
        r = cliente.post(f"/api/bibliotecas/{bid}/matriz", headers=CABECA,
                         files={"arquivo": ("cenas.json", json.dumps(list(self.MATRIZ)).encode(),
                                            "application/json")})
        ficha = r.json()
        assert (ficha["cenas"], ficha["evitadas"]) == (2, 1)
        # a capa é a cena forte, registrada como vídeo (a thumbnail tira os quadros dela)
        assert ficha["capa"]["nome"] == "t1-001.mp4" and ficha["capa"]["largura"] == 320
        quadro = cliente.get(f"/api/videos/{ficha['capa']['id']}/quadro?segundo=0.5",
                             headers=CABECA)
        assert quadro.status_code == 200

    # Os nomes curtos importam: o pytest põe o nome do teste numa variável de ambiente, e
    # no Windows ela não passa de 32.767 letras (os 3 MB do último quebravam o CI).
    @pytest.mark.parametrize(("conteudo", "status", "trecho"), [
        (b"{quebrado", 422, "JSON"),
        (b'[{"arquivo": "nenhum.mp4", "descricao": "x"}]', 422, "nenhuma cena"),
        (b"\xff\xfe\x00", 422, "UTF-8"),
        (b"[" + b" " * (3 * 1024 * 1024) + b"]", 400, "2 MB"),
    ], ids=["json-quebrado", "nenhuma-cena", "nao-e-utf8", "grande-demais"])
    def test_matriz_ruim(self, cliente, tmp_path, conteudo, status, trecho):
        bid = self._abrir(cliente, tmp_path)
        r = cliente.post(f"/api/bibliotecas/{bid}/matriz", headers=CABECA,
                         files={"arquivo": ("cenas.json", conteudo, "application/json")})
        assert r.status_code == status and trecho in r.json()["detail"]

    def test_sem_matriz_nao_edita(self, cliente, tmp_path):
        bid = self._abrir(cliente, tmp_path)
        r = cliente.post("/api/tarefas", headers=CABECA, json={
            "montagem": {"biblioteca_id": bid, "fala": "audio", "formato": "vertical"}})
        assert r.status_code == 422 and "matriz" in r.json()["detail"]
        r = cliente.post("/api/tarefas", headers=CABECA, json={
            "montagem": {"biblioteca_id": "nao-existe", "fala": "audio"}})
        assert r.status_code == 404

    def test_edita_com_as_cenas_e_dois_audios(self, cliente, tmp_path):
        from tests.test_montagem import audio_wav

        bid = self._abrir(cliente, tmp_path, list(self.MATRIZ))
        ids = []
        for nome in ("parte 1.wav", "parte 2.wav"):
            with open(audio_wav(tmp_path / nome, segundos=2.5, falas=((0.3, 2.2),)), "rb") as f:
                r = cliente.post("/api/audios", headers=CABECA,
                                 files={"arquivo": (nome, f, "audio/wav")})
            ids.append(r.json()["id"])
        r = cliente.post("/api/tarefas", headers=CABECA, json={
            "montagem": {"biblioteca_id": bid, "audio_ids": ids, "fala": "audio",
                         "formato": "vertical"},
            "edicao": {"janela": True, "animacoes": True, "voz": "limpa",
                       "estilo_da_legenda": "destaques", "bipe": "sexo"},
            "saida": {"resolucao": "480p"}})
        assert r.status_code == 200, r.text
        t = _esperar(cliente, r.json()["id"], limite=120)
        assert t["estado"] == "pronto", t["erro"]
        resultado = t["resultado"]
        assert resultado["roteiro"]["por"] == "falsa" and resultado["roteiro"]["cenas"] >= 2
        assert Path(resultado["video"]).name == "cenas-editado.mp4"
        plano = json.loads(Path(resultado["plano"]).read_text(encoding="utf-8"))
        assert {b["tipo"] for b in plano["blocos"]} <= {"linha", "pilula"}


class TestAMatrizGerada:
    """O botão "Gerar a matriz": o Gemini (aqui, a IA de teste) descreve os clipes em
    segundo plano, a página acompanha, mostra as miniaturas e salva o que foi revisado."""

    def _abrir_sem_matriz(self, cliente, tmp_path) -> str:
        bid = cliente.post("/api/bibliotecas", headers=CABECA, json={"nome": "cenas"}).json()["id"]
        for nome in ("a.mp4", "b.mp4"):
            c = fazer_video(tmp_path / nome, largura=320, altura=180, segundos=1.0,
                            com_audio=False)
            with open(c, "rb") as f:
                cliente.post(f"/api/bibliotecas/{bid}/clipes", headers=CABECA,
                             files={"arquivo": (nome, f, "video/mp4")})
        return bid

    def test_gera_acompanha_e_salva(self, cliente, tmp_path):
        bid = self._abrir_sem_matriz(cliente, tmp_path)
        r = cliente.post(f"/api/bibliotecas/{bid}/gerar-matriz", headers=CABECA,
                         json={"assunto": "um jogo"})
        assert r.status_code == 200 and r.json()["total"] == 2
        fim = time.monotonic() + 30
        while True:
            estado = cliente.get(f"/api/bibliotecas/{bid}/gerar-matriz", headers=CABECA).json()
            if not estado["rodando"] or time.monotonic() > fim:
                break
            time.sleep(0.1)
        assert estado["erro"] == "" and estado["por"] == "falsa"
        assert [c["arquivo"] for c in estado["cenas"]] == ["a.mp4", "b.mp4"]
        quadro = cliente.get(f"/api/bibliotecas/{bid}/quadro?arquivo=a.mp4", headers=CABECA)
        assert quadro.status_code == 200 and quadro.content[:2] == b"\xff\xd8"
        assert cliente.get(f"/api/bibliotecas/{bid}/quadro?arquivo=../../segredo.mp4",
                           headers=CABECA).status_code == 404
        # a revisada vale como o cenas.json enviado, e volta para revisar de novo
        revisada = [{**c, "descricao": "Revisada à mão"} for c in estado["cenas"]]
        r = cliente.post(f"/api/bibliotecas/{bid}/matriz", headers=CABECA,
                         files={"arquivo": ("cenas.json", json.dumps(revisada).encode(),
                                            "application/json")})
        assert r.status_code == 200 and r.json()["cenas"] == 2
        atual = cliente.get(f"/api/bibliotecas/{bid}/matriz", headers=CABECA).json()["cenas"]
        assert {c["descricao"] for c in atual} == {"Revisada à mão"}

    def test_sem_clipes_e_sem_matriz(self, cliente):
        bid = cliente.post("/api/bibliotecas", headers=CABECA, json={}).json()["id"]
        assert cliente.post(f"/api/bibliotecas/{bid}/gerar-matriz", headers=CABECA,
                            json={}).status_code == 422
        assert cliente.get(f"/api/bibliotecas/{bid}/gerar-matriz",
                           headers=CABECA).status_code == 404
        assert cliente.get(f"/api/bibliotecas/{bid}/matriz", headers=CABECA).status_code == 404
