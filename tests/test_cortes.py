"""Os cortes de silêncio: o que fica, onde a borda cai e como o tempo se desloca."""
from __future__ import annotations

import numpy as np
import pytest

from editor import cortes
from editor.transcricao import Palavra

TAXA = 48_000


def _audio(segundos: float, falas: list[tuple[float, float]]) -> np.ndarray:
    t = np.arange(round(segundos * TAXA)) / TAXA
    som = np.zeros_like(t, dtype=np.float32)
    for ini, fim in falas:
        trecho = (t >= ini) & (t < fim)
        som[trecho] = 0.3 * np.sin(2 * np.pi * 200 * t[trecho])
    return som


class TestAsFalas:
    def test_pausa_curta_junta_pausa_longa_separa(self):
        ws = [Palavra("a", 0.0, 0.3), Palavra("b", 0.5, 0.8), Palavra("c", 2.0, 2.3)]
        primeiro, segundo = cortes.calcular(ws, None, TAXA, 3.0, pausa_maxima=0.45)
        assert primeiro.ini == 0.0 and 0.8 < primeiro.fim < 1.0 and 1.8 < segundo.ini < 2.0

    def test_sem_palavras_o_video_fica_inteiro(self):
        assert cortes.calcular([], None, TAXA, 5.0) == [cortes.Trecho(0.0, 5.0)]


class TestABordaVaiParaOSilencio:
    """O Whisper marca o fim da palavra cedo: aqui ele diz 1,90 s e o som vai até 2,00 s.
    Cortar em 1,90 comeria o fim da sílaba."""

    def test_o_fim_da_fala_fica_depois_do_som(self):
        audio = _audio(5.0, [(0.5, 2.0), (3.5, 4.5)])
        ws = [Palavra("um", 0.55, 1.2), Palavra("dois", 1.3, 1.90),
              Palavra("tres", 3.5, 4.4)]
        trechos = cortes.calcular(ws, audio, TAXA, 5.0, pausa_maxima=0.45, respiro=0.15)
        assert len(trechos) == 2
        primeiro, segundo = trechos
        # o som acaba em 2,00 s: a borda vem depois dele, com metade do respiro
        assert 2.0 <= primeiro.fim <= 2.0 + 0.075 + 0.03
        # e a fala seguinte começa em 3,50 s: a borda vem antes, com a outra metade
        assert 3.5 - 0.075 - 0.03 <= segundo.ini <= 3.5
        # o começo e o fim do vídeo foram aparados
        assert primeiro.ini > 0.3 and segundo.fim < 4.7

    def test_cauda_que_decai_ate_zero_nao_e_cortada(self):
        """Visto com fala real: a sílaba final decai (−10, −30, −44 dB) e depois vem
        silêncio digital (zeros). Medindo a pausa só pelo ponto mais baixo da janela,
        só os zeros contavam como pausa, a busca desistia e o corte caía no tempo do
        Whisper — no meio da cauda de "senadores"."""
        t = np.arange(round(3.0 * TAXA)) / TAXA
        som = np.zeros_like(t, dtype=np.float32)
        fala = t < 1.45
        som[fala] = 0.3 * np.sin(2 * np.pi * 200 * t[fala])
        cauda = (t >= 1.45) & (t < 1.70)                 # o fim da palavra, decaindo
        som[cauda] = (0.3 * np.exp(-(t[cauda] - 1.45) * 25)
                      * np.sin(2 * np.pi * 200 * t[cauda]))
        # depois de 1,70 s: zeros
        ws = [Palavra("senadores.", 0.9, 1.30), Palavra("depois", 2.6, 2.9)]
        trechos = cortes.calcular(ws, som, TAXA, 3.0)
        fim = trechos[0].fim
        assert fim >= 1.50, f"cortou na cauda da palavra ({fim:.3f} s)"

    def test_comeco_adiantado_pelo_whisper(self):
        """Visto com fala real: depois de uma pausa, o Whisper dá à palavra seguinte o
        silêncio que vem antes dela — "O" começava em 3,99 s e o som em 4,74 s. Cortar no
        tempo dele deixava quase 0,9 s de pausa no vídeo."""
        audio = _audio(5.0, [(0.5, 2.0), (3.5, 4.5)])
        ws = [Palavra("um", 0.55, 1.9), Palavra("dois", 2.7, 4.4)]
        trechos = cortes.calcular(ws, audio, TAXA, 5.0)
        assert len(trechos) == 2
        assert 3.5 - 0.075 - 0.03 <= trechos[1].ini <= 3.5

    def test_pausa_engolida_inteira_tambem_e_cortada(self):
        """Visto com fala real: em "sozinho, [1 s] e escreve", o Whisper pôs o "e" de
        6,95 a 8,15 s, colado em "sozinho". Entre as palavras não havia pausa nenhuma, e o
        segundo inteiro de silêncio ficava no vídeo."""
        audio = _audio(5.0, [(0.5, 2.0), (3.2, 4.5)])
        ws = [Palavra("corta", 0.5, 1.4), Palavra("sozinho,", 1.4, 2.0),
              Palavra("e", 2.0, 3.4), Palavra("escreve", 3.4, 4.4)]
        trechos = cortes.calcular(ws, audio, TAXA, 5.0)
        assert len(trechos) == 2
        assert 2.0 <= trechos[0].fim <= 2.0 + 0.075 + 0.03
        assert 3.2 - 0.075 - 0.03 <= trechos[1].ini <= 3.2

    def test_primeira_palavra_adiantada(self):
        audio = _audio(3.0, [(0.8, 2.0)])
        ws = [Palavra("gravou", 0.43, 1.2), Palavra("um", 1.2, 1.9)]
        trechos = cortes.calcular(ws, audio, TAXA, 3.0)
        assert 0.8 - 0.075 - 0.03 <= trechos[0].ini <= 0.8

    def test_video_que_ja_abre_falando_nao_perde_a_primeira_silaba(self):
        """Sem silêncio antes da fala, a pausa mais longa da janela é o fechamento de uma
        consoante dentro da primeira palavra (60 ms aqui) — e isso não é começo de fala."""
        audio = _audio(2.0, [(0.0, 0.30), (0.36, 1.5)])
        ws = [Palavra("tapete", 0.0, 0.6), Palavra("azul", 0.7, 1.4)]
        assert cortes.calcular(ws, audio, TAXA, 2.0)[0].ini == 0.0

    def test_pausa_perto_escolhe_a_mais_longa(self):
        audio = _audio(2.0, [(0.0, 0.50), (0.53, 1.0), (1.4, 2.0)])
        a, b = cortes.pausa_perto(audio, TAXA, 0.3, 1.6)
        assert a == pytest.approx(1.0, abs=0.02) and b == pytest.approx(1.4, abs=0.02)

    def test_sem_contraste_nao_inventa_pausa(self):
        audio = _audio(1.0, [(0.0, 1.0)])
        assert cortes.pausa_perto(audio, TAXA, 0.2, 0.8) is None


class TestOMapaDoTempo:
    def setup_method(self):
        self.linha = cortes.Linha([cortes.Trecho(1.0, 2.0), cortes.Trecho(3.0, 4.5)])

    def test_dentro_e_fora(self):
        assert self.linha.para_saida(1.5) == pytest.approx(0.5)
        assert self.linha.para_saida(3.2) == pytest.approx(1.2)
        assert self.linha.para_saida(2.5) is None
        assert self.linha.duracao == pytest.approx(2.5)
        assert self.linha.cortes == [pytest.approx(1.0)]

    def test_prender_vai_para_a_borda_mais_proxima(self):
        assert self.linha.prender(2.2) == pytest.approx(1.0)
        assert self.linha.prender(2.9) == pytest.approx(1.0)
        assert self.linha.prender(0.2) == pytest.approx(0.0)

    def test_palavra_cortada_inteira_some(self):
        ws = [Palavra("fica", 1.2, 1.5), Palavra("some", 2.3, 2.6), Palavra("vai", 3.1, 3.4)]
        saida = self.linha.palavras(ws)
        assert [w.texto for w in saida] == ["fica", "vai"]
        assert saida[1].inicio == pytest.approx(1.1)

    def test_palavra_que_atravessa_o_corte_comeca_no_trecho_dela(self):
        """O Whisper deu ao "e" o silêncio de antes (de 1,9 a 3,3 s). O som está no
        segundo trecho: a legenda acende a palavra quando ele começa, e não ainda no fim
        da frase anterior."""
        e = self.linha.palavras([Palavra("e", 1.9, 3.3)])[0]
        assert (e.inicio, e.fim) == (pytest.approx(1.0), pytest.approx(1.3))
