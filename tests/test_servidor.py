"""
A API da interface, pelo TestClient do FastAPI. A transcrição é a falsa (conftest),
então uma edição inteira leva alguns segundos.
"""
from __future__ import annotations

import io
import threading
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from editor import render, servidor
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
