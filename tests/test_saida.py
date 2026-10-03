"""As opções de saída: o que este computador grava, tamanhos e combinações."""
from __future__ import annotations

from fractions import Fraction

import pytest

from editor import saida


class TestOQueOComputadorGrava:
    def test_h264_e_aac_vem_dentro_do_pyav(self):
        """A promessa do README — "nada para instalar além do uv" — depende disto.
        O CI roda este teste no Windows, no macOS e no Linux."""
        d = saida.disponiveis()
        assert "h264" in d["mp4"]["codecs"] and "aac" in d["mp4"]["audios"]

    def test_so_combinacoes_que_existem(self):
        for formato, d in saida.disponiveis().items():
            _conteiner, codecs, audios = saida.FORMATOS[formato]
            assert set(d["codecs"]) <= set(codecs) and set(d["audios"]) <= set(audios)


class TestOTamanho:
    @pytest.mark.parametrize("entrada, resolucao, esperado", [
        ((1080, 1920), "720p", (720, 1280)),
        ((1920, 1080), "720p", (1280, 720)),
        ((1080, 1920), "2160p", (1080, 1920)),       # nunca aumenta
        ((1080, 1920), "original", (1080, 1920)),
        ((1081, 1921), "original", (1080, 1920)),    # sempre par, sem passar do original
        ((720, 1280), "480p", (480, 854)),
    ])
    def test_pelo_lado_curto_sem_aumentar_e_par(self, entrada, resolucao, esperado):
        assert saida.tamanho(*entrada, resolucao) == esperado

    def test_gif_fica_pequeno(self):
        assert saida.tamanho(1080, 1920, "original", "gif") == (480, 854)
        assert saida.fps_de_saida(Fraction(60), "original", "gif") == 15

    def test_fps(self):
        assert saida.fps_de_saida(Fraction(30000, 1001), "original") == Fraction(30000, 1001)
        assert saida.fps_de_saida(Fraction(60), "30") == 30


class TestAsCombinacoes:
    def test_padrao_do_formato(self):
        r = saida.OpcoesDeSaida(formato="webm").resolvidas()
        assert r.codec in ("vp9", "av1") and r.audio == "opus"

    @pytest.mark.parametrize("opcoes, trecho", [
        ({"formato": "webm", "codec": "h264"}, "não aceita o codec"),
        ({"formato": "mp4", "audio": "opus"}, "não aceita áudio"),
        ({"formato": "avi"}, "formato desconhecido"),
        ({"resolucao": "8k"}, "resolução desconhecida"),
        ({"qualidade": "máxima"}, "qualidade"),
    ])
    def test_recusa_o_que_nao_combina(self, opcoes, trecho):
        problemas = saida.OpcoesDeSaida(**opcoes).problemas()
        assert any(trecho in p for p in problemas), problemas
