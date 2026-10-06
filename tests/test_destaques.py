"""
A legenda "destaques": as páginas de até 4 palavras, a
pílula sozinha, os destaques sem o Gemini e o desenho, palavra a palavra.
"""
from __future__ import annotations

import itertools

import numpy as np
import pytest
from PIL import Image

from editor import legenda as leg
from editor import plano
from editor.opcoes import OpcoesDeEdicao
from editor.transcricao import Palavra


def _fala(texto: str, passo: float = 0.32, dura: float = 0.26) -> list[Palavra]:
    return [Palavra(w, round(i * passo, 3), round(i * passo + dura, 3))
            for i, w in enumerate(texto.split())]


FALA = _fala("A Rockstar não vai pegar leve no GTA 6. E uma página que foi apagada acabou "
             "de provar isso. A PEGI, que classifica os jogos na Europa, publicou a ficha.")


class TestAsPaginas:
    def test_quebram_como_no_chat(self):
        paginas = plano.montar_paginas(FALA, 12.0, [(2, 5, "pilula")])
        textos = [(b.tipo, b.texto) for b in paginas]
        assert textos[:4] == [("linha", "A Rockstar"), ("pilula", "não vai pegar leve"),
                              ("linha", "no GTA 6."), ("linha", "E uma página que")]
        # até 4 palavras, a não ser quando um pedaço curto juntou
        assert all(len(b.palavras) <= 6 for b in paginas)

    def test_entram_antes_e_nunca_dividem_a_tela(self):
        paginas = plano.montar_paginas(FALA, 12.0, [])
        for b, seguinte in itertools.pairwise(paginas):
            assert b.inicio == pytest.approx(max(0.0, b.palavras[0].inicio - 0.08))
            assert b.fim <= seguinte.inicio - 0.03 + 1e-6
        assert paginas[-1].fim <= 12.0

    def test_a_pilula_perde_o_ponto(self):
        paginas = plano.montar_paginas(_fala("e tirou do ar logo depois."), 3.0,
                                       [(3, 5, "pilula")])
        assert paginas[-1].tipo == "pilula" and paginas[-1].texto == "ar logo depois"

    def test_pedaco_curto_junta_com_o_vizinho(self):
        # "Sim." sozinho piscaria (uma palavra em 0,26 s): sem página antes, junta com a
        # seguinte; e o "mesmo" que sobra no fim junta com a de antes
        paginas = plano.montar_paginas(_fala("Sim. Isso aqui é verdade mesmo"), 3.0, [])
        assert [b.texto for b in paginas] == ["Sim. Isso aqui é verdade mesmo"]

    def test_os_estilos_de_cada_palavra(self):
        paginas = plano.montar_paginas(FALA, 12.0, [(1, 1, "ciano"), (11, 14, "rosa")])
        assert paginas[0].texto == "A Rockstar não vai"
        assert paginas[0].estilos == ["", "ciano", "", ""]
        cor_de = {w.texto: e for b in paginas for w, e in zip(b.palavras, b.estilos,
                                                               strict=True)}
        assert cor_de["página"] == cor_de["apagada"] == "rosa"
        assert cor_de["provar"] == ""

    def test_destaque_fora_da_fala_e_ignorado(self):
        paginas = plano.montar_paginas(FALA, 12.0, [(-1, 2, "rosa"), (5, 999, "pilula"),
                                                    (3, 3, "verde")])
        assert all(e == "" for b in paginas for e in b.estilos)
        assert all(b.tipo == "linha" for b in paginas)


class TestSemOGemini:
    def test_nomes_em_ciano_e_numeros_em_rosa(self):
        frase = "Hoje nos Estados Unidos a nota é 17. A Rockstar e o GTA 6 também."
        marcas = plano.destaques_pelas_palavras(_fala(frase))
        texto = {a: m for a, _, m in marcas}
        palavras = frase.split(" ")
        assert (2, 3, "ciano") in marcas                     # "Estados Unidos", juntas
        assert texto[palavras.index("17.")] == "rosa"
        assert texto[palavras.index("Rockstar")] == "ciano"
        gta = palavras.index("GTA")
        assert (gta, gta + 1, "ciano") in marcas              # "GTA 6": o número é do nome
        assert 0 not in texto                                 # "Hoje" só abre a frase

    def test_o_plano_ja_sai_em_paginas(self):
        p = plano.montar(FALA, 12.0, vertical=True, cortes=[], nomes_de_icones=set(),
                         opcoes=OpcoesDeEdicao(estilo_da_legenda="destaques"))
        assert {b.tipo for b in p.blocos} == {"linha"}
        assert p.adesivos == []                  # o adesivo é da legenda clássica

    def test_a_opcao_e_conferida(self):
        assert OpcoesDeEdicao(estilo_da_legenda="destaques").problemas() == []
        assert "estilo de legenda desconhecido" in " ".join(
            OpcoesDeEdicao(estilo_da_legenda="neon").problemas())


def _plano(blocos: list[plano.Bloco]) -> plano.Plano:
    return plano.Plano(12.0, True, blocos, [], [(0.0, 1.0)], [], [], [])


def _quadro(p: plano.Plano, t: float, base: float | None = 1430,
            tamanho=(1080, 1920)) -> np.ndarray:
    img = Image.new("RGB", tamanho, (40, 30, 60))
    leg.Legenda(*tamanho, vertical=tamanho[1] > tamanho[0]).desenhar(img, p, t, base=base)
    return np.asarray(img)


def _conta(q: np.ndarray, cor, tolerancia: int = 20) -> int:
    return int((np.abs(q.astype(int) - np.array(cor[:3])).max(axis=2) <= tolerancia).sum())


class TestODesenho:
    def test_as_palavras_entram_uma_a_uma(self):
        p = _plano(plano.montar_paginas(_fala("tudo isso aqui agora"), 3.0, []))
        fundo = (40, 30, 60)
        tintas = [q.size // 3 - _conta(q, fundo, 2) for q in
                  (_quadro(p, t) for t in (0.05, 0.40, 0.72, 1.05))]
        assert tintas[0] < tintas[1] < tintas[2] < tintas[3]

    def test_a_palavra_dita_acende(self):
        p = _plano(plano.montar_paginas(_fala("o frio atinge"), 3.0, [(2, 2, "rosa")]))
        dita = _quadro(p, 0.75)              # "atinge" (0,64 a 0,90) sendo dita
        depois = _quadro(p, 1.2)
        # a comum dita fica âmbar; depois, branca
        assert _conta(_quadro(p, 0.40), leg.DITA[""]) > 500
        assert _conta(depois, leg.DITA[""]) < 50
        assert _conta(dita, leg.DITA["rosa"]) > 500 and _conta(depois, leg.DITA["rosa"]) > 500

    def test_a_pilula_amarela(self):
        p = _plano(plano.montar_paginas(_fala("passou do ponto?"), 3.0, [(0, 2, "pilula")]))
        q = _quadro(p, 0.6)
        assert _conta(q, leg.PILULA, 6) > 20_000
        colunas = np.where((np.abs(q.astype(int) - np.array(leg.PILULA)).max(axis=2) <= 6)
                           .any(axis=0))[0]
        assert colunas.min() > 0 and colunas.max() < 1079        # dentro do quadro

    def test_nunca_passa_de_duas_linhas(self):
        b = plano.montar_paginas(_fala("Algumas armas causam decapitação"), 3.0, [])[0]
        legenda = leg.Legenda(1080, 1920, vertical=True)
        px = legenda.corpo_da_pagina(b)
        assert len(legenda.linhas_da_pagina(b, px)) <= 2

    def test_nunca_sai_por_baixo_do_quadro(self):
        # duas linhas, com a faixa encostada no pé de um quadro quadrado
        paginas = plano.montar_paginas(_fala("que classifica os jogos lá fora"), 3.0, [])
        legenda = leg.Legenda(720, 720, vertical=False)
        assert len(legenda.linhas_da_pagina(paginas[0], legenda.corpo_da_pagina(paginas[0]))) == 2
        q = _quadro(_plano(paginas), 1.0, base=700, tamanho=(720, 720))
        fundo = np.array((40, 30, 60))
        com_tinta = np.where((np.abs(q.astype(int) - fundo).max(axis=2) > 2).any(axis=1))[0]
        assert com_tinta.max() < 719                        # nem a sombra chega na borda
        branco = np.where((q.min(axis=2) > 200).any(axis=1))[0]
        assert branco.max() < 700                           # e o texto fica bem dentro

    @pytest.mark.parametrize("tamanho", [(1080, 1920), (1080, 1080), (1920, 1080)])
    def test_em_cada_formato(self, tamanho):
        p = _plano(plano.montar_paginas(FALA, 12.0, [(1, 1, "ciano"), (2, 5, "pilula")]))
        for t in (0.2, 1.0, 3.0):
            for base in (None, tamanho[1] * 0.75):
                q = _quadro(p, t, base, tamanho)
                assert q.shape == (tamanho[1], tamanho[0], 3)
