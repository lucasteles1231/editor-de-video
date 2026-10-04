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



class TestAPessoaQueMudaDeLugar:
    """Com o recorte falso: a silhueta de busto no meio do quadro."""

    def _quadro(self, caminho, t: float):
        with av.open(str(caminho)) as c:
            for fr in c.decode(video=0):
                if fr.time >= t:
                    return fr.to_ndarray(format="rgb24").astype(int)
        raise AssertionError(f"sem quadro em {t}")

    def test_edita_com_a_pessoa_saindo_do_lugar(self, tmp_path):
        import json

        entrada = fazer_video(tmp_path / "e.mp4", segundos=14.0)
        parado = render.editar(entrada, tmp_path / "parado.mp4", OpcoesDeEdicao(),
                               saida.OpcoesDeSaida())
        movido = render.editar(entrada, tmp_path / "movido.mp4",
                               OpcoesDeEdicao(mover_pessoa=True), saida.OpcoesDeSaida())
        movimentos = json.loads(movido.plano.read_text(encoding="utf-8"))["movimentos"]
        assert movimentos, "nenhum movimento num vídeo de 14 s"
        info = ler_info(movido.video)
        assert info["duracao"] == pytest.approx(movido.duracao_final, abs=0.12)
        m = movimentos[0]
        meio = (m["inicio"] + m["fim"]) / 2
        diferenca = np.abs(self._quadro(movido.video, meio) - self._quadro(parado.video, meio))
        assert diferenca.mean() > 8, "o quadro do movimento saiu igual ao parado"
        # fora dos movimentos, nada muda
        antes = max(0.0, m["inicio"] - 0.5)
        diferenca = np.abs(self._quadro(movido.video, antes) - self._quadro(parado.video, antes))
        assert diferenca.mean() < 2

    def test_sem_o_modelo_a_edicao_sai_com_a_pessoa_parada(self, tmp_path, monkeypatch):
        from editor import recorte

        monkeypatch.setattr(recorte, "preparar_modelo", lambda: False)
        avisos = []
        entrada = fazer_video(tmp_path / "e.mp4", segundos=14.0)
        r = render.editar(entrada, tmp_path / "s.mp4", OpcoesDeEdicao(mover_pessoa=True),
                          saida.OpcoesDeSaida(),
                          progresso=lambda etapa, f, detalhe: avisos.append(detalhe))
        assert r.video.is_file()
        assert any("a pessoa fica no lugar" in a for a in avisos)

    def test_no_terminal(self, tmp_path, monkeypatch):
        from editor import cli

        pedidos = []
        monkeypatch.setattr(render, "editar", lambda entrada, destino, edicao, saida_, **kw:
                            pedidos.append(edicao) or render.Resultado(destino, destino))
        video = fazer_video(tmp_path / "e.mp4", segundos=1.0)
        assert cli.main([str(video), "--mover-pessoa", "--fundo-da-pessoa", "cor",
                         "--cor-do-fundo", "lima"]) == 0
        assert (pedidos[0].mover_pessoa, pedidos[0].fundo_da_pessoa,
                pedidos[0].cor_do_fundo) == (True, "cor", "lima")
