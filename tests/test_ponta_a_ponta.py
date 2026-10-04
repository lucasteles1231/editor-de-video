"""
O editor inteiro, do vídeo de entrada ao editado, em vídeos sintéticos pequenos.

A transcrição é a falsa (ver conftest): ela devolve palavras espalhadas pelo vídeo,
com uma pausa longa a cada frase — o bastante para cortar, legendar e planejar.
"""
from __future__ import annotations

from typing import ClassVar

import av
import numpy as np
import pytest
from PIL import Image

from editor import render, saida
from editor.opcoes import OpcoesDeEdicao
from tests.conftest import FIXTURES, fazer_video, ler_info


def _editar(entrada, destino, **saida_kw):
    return render.editar(entrada, destino, OpcoesDeEdicao(), saida.OpcoesDeSaida(**saida_kw))


class TestFormatoDaEntrada:
    @pytest.mark.parametrize("largura, altura", [(320, 568), (568, 320)])
    def test_sai_no_mesmo_tamanho_com_audio_e_cortado(self, tmp_path, largura, altura):
        entrada = fazer_video(tmp_path / "e.mp4", largura=largura, altura=altura, segundos=6.0)
        r = _editar(entrada, tmp_path / "s.mp4")
        info = ler_info(r.video)
        assert (info["largura"], info["altura"]) == (largura, altura)
        assert info["fps"] == 30 and info["audio"] == ["aac"]
        # a transcrição falsa tem pausas de 0,9 s: o corte encurta o vídeo
        assert r.duracao_final < r.duracao_original - 0.5
        assert info["duracao"] == pytest.approx(r.duracao_final, abs=0.12)
        assert r.plano.is_file()

    def test_video_de_celular_girado_sai_em_pe(self, tmp_path):
        """O arquivo guarda 320×240 deitado com rotação de −90°: sai 240×320."""
        r = _editar(FIXTURES / "girado.mp4", tmp_path / "s.mp4")
        info = ler_info(r.video)
        assert (info["largura"], info["altura"]) == (240, 320)

    def test_sem_cortes_mantem_a_duracao(self, tmp_path, video):
        r = render.editar(video, tmp_path / "s.mp4", OpcoesDeEdicao(cortes=False),
                          saida.OpcoesDeSaida())
        assert r.duracao_final == pytest.approx(r.duracao_original, abs=0.05)


class TestCadaFormato:
    COMBINACOES: ClassVar[list[tuple[str, str]]] = [
        ("mp4", "h264"), ("mp4", "h265"), ("mov", "prores"), ("webm", "vp9"),
        ("webm", "av1"), ("mkv", "h264"), ("gif", "gif")]

    @pytest.mark.parametrize("formato, codec", COMBINACOES)
    def test_grava_e_rele(self, tmp_path, formato, codec):
        if codec not in saida.disponiveis().get(formato, {}).get("codecs", []):
            pytest.skip(f"{formato}/{codec} não existe neste computador")
        entrada = fazer_video(tmp_path / "e.mp4", segundos=2.0)
        r = _editar(entrada, tmp_path / f"s.{formato}", formato=formato, codec=codec,
                    qualidade="leve")
        if formato == "gif":
            with Image.open(r.video) as gif:
                assert gif.size[0] % 2 == 0 and gif.n_frames > 5
            return
        info = ler_info(r.video)
        assert (info["largura"], info["altura"]) == (320, 568)
        assert info["audio"], "saiu sem áudio"


class TestOpcoesDeSaida:
    def test_resolucao_e_fps(self, tmp_path):
        entrada = fazer_video(tmp_path / "e.mp4", largura=540, altura=960, fps=60, segundos=2.0)
        r = _editar(entrada, tmp_path / "s.mp4", resolucao="480p", fps="30")
        info = ler_info(r.video)
        assert (info["largura"], info["altura"]) == (480, 854) and info["fps"] == 30

    def test_legendas_com_os_tempos_cortados(self, tmp_path, video):
        r = _editar(video, tmp_path / "s.mp4", srt=True, vtt=True)
        nomes = sorted(p.suffix for p in r.legendas)
        assert nomes == [".srt", ".vtt"]
        srt = (tmp_path / "s.srt").read_text(encoding="utf-8")
        assert srt.startswith("1\n00:00:00,") and " --> " in srt
        assert (tmp_path / "s.vtt").read_text(encoding="utf-8").startswith("WEBVTT")

    def test_previa_so_os_primeiros_segundos(self, tmp_path):
        entrada = fazer_video(tmp_path / "e.mp4", segundos=6.0)
        r = render.editar(entrada, tmp_path / "s.mp4", OpcoesDeEdicao(cortes=False),
                          saida.OpcoesDeSaida(), previa_s=2.0)
        assert r.duracao_final == pytest.approx(2.0, abs=0.1)


class TestCaminhosDificeis:
    def test_espaco_e_acento_no_nome(self, tmp_path):
        pasta = tmp_path / "Meus Vídeos" / "gravação de hoje"
        pasta.mkdir(parents=True)
        entrada = fazer_video(pasta / "meu vídeo final.mp4", segundos=2.0)
        r = _editar(entrada, pasta / "meu vídeo final-editado.mp4")
        assert r.video.is_file() and r.video.stat().st_size > 1000


class TestCancelar:
    def test_cancelar_para_e_levanta(self, tmp_path, video):
        with pytest.raises(render.Cancelado):
            render.editar(video, tmp_path / "s.mp4", OpcoesDeEdicao(), saida.OpcoesDeSaida(),
                          cancelar=lambda: True)


class TestNoTerminal:
    def test_a_extensao_do_o_escolhe_o_formato(self, tmp_path, video):
        """"-o final.mov --codec prores" sem --formato: antes o formato ficava no padrão
        (MP4), que não aceita ProRes, e o comando recusava."""
        from editor import cli

        destino = tmp_path / "final.mov"
        assert cli.main([str(video), "-o", str(destino), "--codec", "prores"]) == 0
        assert ler_info(destino)["video"] == "prores"
        with av.open(str(destino)) as c:
            assert "mov" in c.format.name

    def test_sem_o_o_padrao_e_mp4_ao_lado_do_original(self, tmp_path, video):
        from editor import cli

        assert cli.main([str(video)]) == 0
        assert (video.parent / f"{video.stem}-editado.mp4").is_file()



class TestAMontagem:
    """O fundo e, por cima, a pessoa ou o personagem. O recorte e a transcrição são os
    falsos (conftest)."""

    def _quadro(self, caminho, t: float):
        with av.open(str(caminho)) as c:
            for fr in c.decode(video=0):
                if fr.time >= t:
                    return fr.to_ndarray(format="rgb24").astype(int)
        raise AssertionError(f"sem quadro em {t}")

    def test_personagem_com_audio_a_parte_em_pe(self, tmp_path):
        import json

        from editor.montagem import Montagem
        from tests.test_montagem import audio_wav, gif

        fundo = fazer_video(tmp_path / "tela.mp4", largura=320, altura=180, segundos=6.0,
                            com_audio=False)
        m = Montagem(fundo, personagem=gif(tmp_path / "b.gif", lado=80),
                     audio=audio_wav(tmp_path / "n.wav", segundos=14.0,
                                     falas=((0.3, 3.0), (4.2, 7.5), (8.6, 13.5))),
                     formato="vertical")
        r = render.editar(None, tmp_path / "s.mp4", OpcoesDeEdicao(), saida.OpcoesDeSaida(),
                          montagem=m)
        info = ler_info(r.video)
        assert (info["largura"], info["altura"]) == (180, 320)
        assert info["audio"] == ["aac"]
        # a fala manda: o vídeo tem a duração da narração cortada, não a do fundo
        assert r.duracao_original == pytest.approx(14.0, abs=0.1)
        assert info["duracao"] == pytest.approx(r.duracao_final, abs=0.12)
        assert r.duracao_final > 6.0                      # o fundo de 6 s deu a volta
        movimentos = json.loads(r.plano.read_text(encoding="utf-8"))["movimentos"]
        assert movimentos, "o personagem não saiu do lugar nenhuma vez"

    def test_pessoa_com_alfa_e_mexendo(self, tmp_path):
        from editor.montagem import Montagem
        from tests.test_montagem import video_com_alfa

        fundo = fazer_video(tmp_path / "tela.mp4", largura=320, altura=180, segundos=14.0)
        pessoa = video_com_alfa(tmp_path / "eu.mov", segundos=14.0)
        m = Montagem(fundo, pessoa=pessoa, recorte="transparente")
        parado = render.editar(None, tmp_path / "parado.mp4", OpcoesDeEdicao(mover=False),
                               saida.OpcoesDeSaida(), montagem=m)
        movido = render.editar(None, tmp_path / "movido.mp4", OpcoesDeEdicao(),
                               saida.OpcoesDeSaida(), montagem=m)
        import json

        info = ler_info(movido.video)
        assert (info["largura"], info["altura"]) == (320, 180)    # o formato do fundo
        mov = json.loads(movido.plano.read_text(encoding="utf-8"))["movimentos"]
        assert mov
        meio = (mov[0]["inicio"] + mov[0]["fim"]) / 2
        diferenca = np.abs(self._quadro(movido.video, meio) - self._quadro(parado.video, meio))
        assert diferenca.mean() > 3, "o quadro do movimento saiu igual ao parado"
        antes = max(0.0, mov[0]["inicio"] - 0.5)
        diferenca = np.abs(self._quadro(movido.video, antes) - self._quadro(parado.video, antes))
        assert diferenca.mean() < 2

    def test_pessoa_recortada_pelo_modnet(self, tmp_path):
        from editor.montagem import Montagem

        fundo = fazer_video(tmp_path / "tela.mp4", largura=320, altura=180, segundos=3.0)
        pessoa = fazer_video(tmp_path / "eu.mp4", largura=180, altura=320, segundos=3.0)
        m = Montagem(fundo, pessoa=pessoa, recorte="modnet", formato="quadrado")
        r = render.editar(None, tmp_path / "s.mp4", OpcoesDeEdicao(), saida.OpcoesDeSaida(),
                          montagem=m)
        info = ler_info(r.video)
        assert (info["largura"], info["altura"]) == (180, 180)

    def test_sem_o_modelo_avisa_o_que_fazer(self, tmp_path, monkeypatch):
        from editor import recorte
        from editor.montagem import Montagem

        monkeypatch.setattr(recorte, "preparar_modelo", lambda: False)
        fundo = fazer_video(tmp_path / "tela.mp4", segundos=2.0)
        m = Montagem(fundo, pessoa=fazer_video(tmp_path / "eu.mp4", segundos=2.0))
        with pytest.raises(RuntimeError, match="sem fundo"):
            render.editar(None, tmp_path / "s.mp4", OpcoesDeEdicao(), saida.OpcoesDeSaida(),
                          montagem=m)

    def test_no_terminal(self, tmp_path, monkeypatch):
        from editor import cli
        from tests.test_montagem import gif, video_com_alfa

        pedidos = []

        def editar(entrada, destino, edicao, saida_, **kw):
            pedidos.append((entrada, destino, edicao, kw.get("montagem")))
            return render.Resultado(destino, destino)

        monkeypatch.setattr(render, "editar", editar)
        fundo = fazer_video(tmp_path / "tela.mp4", segundos=1.0)
        boneco = gif(tmp_path / "b.gif")
        assert cli.main(["--fundo", str(fundo), "--personagem", str(boneco),
                         "--quadro", "vertical", "--parada"]) == 0
        entrada, destino, edicao, m = pedidos[-1]
        assert entrada is None and destino.name == "tela-editado.mp4"
        assert (m.personagem, m.formato, edicao.mover) == (boneco, "vertical", False)
        # o vídeo do argumento vira a pessoa; com alfa, o recorte é o do arquivo
        eu = video_com_alfa(tmp_path / "eu.mov")
        assert cli.main([str(eu), "--fundo", str(fundo)]) == 0
        assert (pedidos[-1][3].pessoa, pedidos[-1][3].recorte) == (eu, "transparente")
        assert cli.main(["--pessoa", str(eu)]) == 2          # sem --fundo
