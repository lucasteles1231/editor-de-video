"""As curvas de animação e a censura, com os números do projeto Remotion do canal."""
from __future__ import annotations

from itertools import pairwise

import pytest

from editor import animacao as a
from editor import censura

Q = a.QUADRO


class TestAsCurvas:
    def test_bezier_nas_pontas_e_crescente(self):
        for curva in (a.SAIDA, a.POUSO, a.CAMERA):
            assert curva(0) == 0 and curva(1) == 1
            valores = [curva(i / 20) for i in range(21)]
            assert all(x <= y + 1e-9 for x, y in pairwise(valores))
        # a curva da câmera é simétrica: devagar, rápido, devagar
        assert a.CAMERA(0.5) == pytest.approx(0.5, abs=1e-3)
        assert a.CAMERA(0.1) < 0.05

    def test_pop(self):
        assert a.pop(0.0, 0.0) == pytest.approx(0.4)
        assert a.pop(5 * Q, 0.0) == pytest.approx(1.08)
        assert a.pop(10 * Q, 0.0) == pytest.approx(1.0)
        assert a.pop(-1.0, 0.0) == pytest.approx(0.4)

    def test_carimbo_cai_de_grande(self):
        assert a.carimbo(0.0, 0.0) == pytest.approx(2.4)
        assert a.carimbo(4 * Q, 0.0) == pytest.approx(0.94)
        assert a.carimbo(8 * Q, 0.0) == pytest.approx(1.0)

    def test_escala_em_logaritmo(self):
        # no meio do caminho (sem curva), a escala é a média geométrica
        assert a.interpolar(0.5, [0, 1], [0.4, 1.6], escala=True) == pytest.approx(0.8)

    def test_entradas_e_saidas(self):
        assert a.aparece(0.0, 0.0) == 0 and a.aparece(4 * Q, 0.0) == 1
        assert a.some_no_fim(1.0 - 5 * Q, 1.0) == 1 and a.some_no_fim(1.0 - Q, 1.0) == 0
        assert a.da_esquerda(0.0, 0.0) == pytest.approx(-1.1)
        assert a.da_esquerda(9 * Q, 0.0) == 0
        assert a.flash(Q, 0.0) == 1 and a.flash(12 * Q, 0.0) == 0

    def test_tremida_some(self):
        assert a.tremida(-0.1, 0.0) == (0.0, 0.0)
        assert a.tremida(8 * Q, 0.0) == (0.0, 0.0)
        dx, dy = a.tremida(Q, 0.0)
        assert abs(dx) > 1 and abs(dy) > 1


class TestACensura:
    @pytest.mark.parametrize(("palavra", "esperado"), [
        ("SEXO", "SE**"),
        ("cocaína", "coca**na"),
        ("decapitação", "deca**tação"),
        ("desmembramentos", "desmem***mentos"),
        ("sexual", "se**al"),
        ("DECAPITAÇÃO", "DECA**TAÇÃO"),
    ])
    def test_os_exemplos_do_chat(self, palavra, esperado):
        assert censurar_igual(palavra) == esperado

    def test_silabas(self):
        assert censura.silabas("problema") == ["pro", "ble", "ma"]
        assert censura.silabas("quero") == ["que", "ro"]
        assert censura.silabas("pão") == ["pão"]
        assert censura.silabas("sol") == ["sol"]

    def test_a_escondida_nunca_e_a_primeira(self):
        assert censura.silaba_escondida(1) == 0
        assert censura.silaba_escondida(2) == 1
        assert censura.silaba_escondida(5) == 2

    def test_proibida_com_plural_acento_e_pontuacao(self):
        lista = censura.lista("cocaína, sexo; decapitação")
        assert lista == ["cocaína", "sexo", "decapitação"]
        assert censura.proibida("Cocaína,", lista)
        assert censura.proibida("SEXOS", lista)
        assert censura.proibida("decapitacao", lista)
        assert not censura.proibida("sexta", lista)

    def test_censurar_texto(self):
        assert censura.censurar_texto("CENAS DE SEXO!", ["sexo"]) == "CENAS DE SE**!"
        assert censura.censurar_texto("nada aqui", []) == "nada aqui"


def censurar_igual(palavra: str) -> str:
    return censura.censurar(palavra)
