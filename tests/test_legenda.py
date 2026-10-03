"""O desenho da legenda: cores do karaokê, o pulo de entrada e o adesivo."""
from __future__ import annotations

import numpy as np
from PIL import Image

from editor import legenda as leg
from editor import plano
from editor.transcricao import Palavra


def _plano(texto: str, *, chave_em: int = -1, adesivo_em: int = -1) -> plano.Plano:
    ws = [Palavra(w, 0.5 + i * 0.4, 0.5 + i * 0.4 + 0.3) for i, w in enumerate(texto.split())]
    bloco = plano.Bloco(ws, 0.5, 4.0, chave_em, [i == 0 for i in range(len(ws))])
    adesivos = ([plano.Adesivo(0, adesivo_em, ws[adesivo_em].inicio, 4.0, 0)]
                if adesivo_em >= 0 else [])
    return plano.Plano(4.0, True, [bloco], adesivos, [(0.0, 1.0)], [], [], [])


def _quadro(p: plano.Plano, t: float) -> np.ndarray:
    img = Image.new("RGB", (540, 960), (40, 90, 160))
    leg.Legenda(540, 960, vertical=True).desenhar(img, p, t)
    return np.asarray(img)


def _conta(matriz: np.ndarray, cor: tuple[int, int, int], tolerancia: int = 12) -> int:
    return int((np.abs(matriz.astype(int) - np.array(cor)).max(axis=2) <= tolerancia).sum())


class TestKaraoke:
    def test_antes_de_dita_cinza_depois_branca(self):
        p = _plano("tudo isso aqui")
        antes = _quadro(p, 0.55)        # só a primeira palavra começou
        depois = _quadro(p, 2.0)        # todas ditas
        assert _conta(antes, leg.CINZA) > _conta(depois, leg.CINZA)
        assert _conta(depois, leg.BRANCO) > _conta(antes, leg.BRANCO)

    def test_a_palavra_chave_acende_amarela_quando_dita(self):
        p = _plano("o frio atinge", chave_em=2)
        assert _conta(_quadro(p, 0.9), leg.AMARELO) == 0      # "atinge" ainda não foi dita
        assert _conta(_quadro(p, 2.0), leg.AMARELO) > 50

    def test_fora_do_bloco_nao_desenha(self):
        p = _plano("nada aqui")
        assert np.array_equal(_quadro(p, 0.1), _quadro(p, 4.5))


class TestOPulo:
    def test_entra_menor_e_cresce(self):
        p = _plano("crescendo")

        def largura(t):
            m = _quadro(p, t)
            fora_do_fundo = np.abs(m.astype(int) - [40, 90, 160]).max(axis=2) > 30
            colunas = np.where(fora_do_fundo.any(axis=0))[0]
            return colunas.max() - colunas.min()

        assert largura(0.51) < largura(1.0)


class TestOAdesivo:
    def test_a_forma_cabe_entre_as_vizinhas(self):
        lg = leg.Legenda(1080, 1920, vertical=True)
        # Uma linha do tamanho real (até 18 caracteres no vertical): numa linha que já
        # ocupa a largura toda, o vão não pode abrir — e não abre, de propósito.
        p = _plano("de vasos azuis", adesivo_em=1)
        bloco = p.blocos[0]
        abre = lg.abertura(bloco, 1, 0)
        f = leg.fonte(lg.em)
        w = f.getlength("vasos")
        forma = w * leg.ADESIVO_FICA + lg.em * leg.FORMA_SOBRA_X
        vao = w + abre + 2 * f.getlength(" ")
        assert vao >= forma + 2 * lg.em * leg.VIZINHA_FOLGA - 0.5

    def test_estrela_pede_mais_espaco(self):
        lg = leg.Legenda(1080, 1920, vertical=True)
        bloco = _plano("de vasos azuis").blocos[0]
        assert lg.abertura(bloco, 1, 1) > lg.abertura(bloco, 1, 0)

    def test_linha_que_ocupa_a_largura_nao_abre_alem_da_borda(self):
        lg = leg.Legenda(1080, 1920, vertical=True)
        # cabe com uns 10 px de sobra: o vão abre só isso, e a linha não sai da tela
        bloco = _plano("cheio de vasos sanguíneos").blocos[0]
        larguras = [leg.fonte(lg.em).getlength(w.texto) for w in bloco.palavras]
        total = sum(larguras) + leg.fonte(lg.em).getlength(" ") * (len(larguras) - 1)
        assert total + lg.abertura(bloco, 2, 0) <= 1080 - 2 * lg.lateral + 0.5

    def test_desenha_o_adesivo_com_a_cor_dele(self):
        p = _plano("custa trinta reais", adesivo_em=1)
        quadro = _quadro(p, 1.6)
        assert _conta(quadro, leg.CORES_DO_ADESIVO[0][0]) > 200

    def test_palavra_sozinha_nao_abre(self):
        lg = leg.Legenda(1080, 1920, vertical=True)
        assert lg.abertura(_plano("sozinha").blocos[0], 0, 0) == 0.0
