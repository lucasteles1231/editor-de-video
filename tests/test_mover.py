"""As peças de mover uma camada: a transformação, a borda que some, o colar e o recorte
quadro a quadro.

O recorte é o falso (ver conftest): uma silhueta de busto no meio do quadro.
"""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from editor import mover, recorte

L, A = 180, 320                      # um quadro em pé, pequeno


class TestATransformacao:
    def test_o_caminho_entre_duas(self):
        a = mover.Transformacao(1.0, 0.0, 0.0)
        b = mover.Transformacao(0.8, 40.0, -20.0)
        assert a.ate(b, 0.0) == a and a.ate(b, 1.0) == b
        assert a.ate(b, 0.5) == mover.Transformacao(0.9, 20.0, -10.0)

    def test_empurrao_cresce_em_volta_de_um_ponto(self):
        t = mover.Transformacao(1.0, 0.0, 0.0).empurrada(0.1, 50.0, 40.0)
        assert t.escala == pytest.approx(1.1)
        assert t.ponto(50.0, 40.0) == pytest.approx((50.0, 40.0))
        menor = mover.Transformacao(1.0, 0.0, 0.0).empurrada(-0.3, 50.0, 100.0)
        assert menor.escala == pytest.approx(0.7)
        assert menor.ponto(50.0, 100.0) == pytest.approx((50.0, 100.0))

    def test_perto_de(self):
        a = mover.Transformacao(1.0, 10.0, 10.0)
        assert a.perto_de(mover.Transformacao(1.01, 12.0, 9.0), L, A)
        assert not a.perto_de(mover.Transformacao(1.3, 10.0, 10.0), L, A)


class TestAsBordas:
    def test_onde_a_pessoa_vinha_cortada(self):
        alfa = np.zeros((40, 30), np.float32)
        alfa[10:, :12] = 1.0                       # encosta na esquerda e embaixo
        assert mover.bordas_tocadas(alfa) == {"esquerda": True, "direita": False,
                                              "topo": False, "baixo": True}

    def test_a_rampa_some_so_nos_lados_pedidos(self):
        r = mover.rampa(40, 30, {"esquerda": True, "baixo": True})
        assert r[20, 0] < 0.05 and r[-1, 15] < 0.05     # some na borda
        assert r[15, 15] == pytest.approx(1.0)           # o miolo fica inteiro
        assert r[20, -1] == pytest.approx(1.0)           # a direita não foi pedida

    def test_bordas_que_entram_na_tela(self):
        esq = mover.Transformacao(0.86, 30.0, 45.0)
        assert mover.expostas(esq, L, A) == {"esquerda": True, "direita": False,
                                             "topo": True, "baixo": False}
        # uma camada menor que a tela, no canto de baixo à direita
        canto = mover.Transformacao(1.0, 100.0, 200.0)
        assert mover.expostas(canto, L, A, 80, 120) == {"esquerda": True, "direita": False,
                                                        "topo": True, "baixo": False}

    def test_a_curva_do_alfa(self):
        a = np.array([0.0, 0.15, 0.5, 0.85, 1.0], np.float32)
        c = mover.curva_do_alfa(a)
        assert c[0] == c[1] == 0.0 and c[3] == c[4] == 1.0
        assert c[2] == pytest.approx(0.5)


class TestColar:
    def test_poe_no_lugar_e_no_tamanho(self):
        tela = Image.new("RGBA", (100, 100), (0, 0, 0, 255))
        pessoa = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
        pessoa.paste((255, 255, 255, 255), (40, 40, 60, 60))     # um quadrado de 20 px
        mover.colar(tela, pessoa, mover.Transformacao(0.5, 10.0, 20.0))
        m = np.asarray(tela.convert("L")) > 128
        ys, xs = np.nonzero(m)
        assert (xs.min(), xs.max(), ys.min(), ys.max()) == (30, 39, 40, 49)

    def test_fora_da_tela_nao_quebra(self):
        tela = Image.new("RGBA", (50, 50), (0, 0, 0, 255))
        pessoa = Image.new("RGBA", (50, 50), (255, 255, 255, 255))
        mover.colar(tela, pessoa, mover.Transformacao(1.0, 80.0, 0.0))
        assert np.asarray(tela.convert("L")).max() == 0


class TestORecorteContinuo:
    def _quadro(self) -> np.ndarray:
        return np.full((A, L, 3), 128, np.uint8)

    def test_recorta_um_quadro_sim_um_nao(self):
        r = mover.RecorteContinuo()
        for _ in range(10):
            q = self._quadro()
            r.alfa(q)
            r.alfa(q)                                 # o mesmo quadro de novo: não recorta
        assert r.recortados == 5

    def test_o_alfa_e_o_da_silhueta(self):
        alfa = mover.RecorteContinuo().alfa(self._quadro())
        esperado = recorte._silhueta_falsa(*alfa.shape)
        assert ((alfa > 0.5) == (esperado > 0.5)).mean() > 0.98

    def test_suaviza_entre_recortes(self, monkeypatch):
        saidas = iter([np.ones((8, 8), np.float32), np.zeros((8, 8), np.float32)])
        monkeypatch.setattr(recorte, "mascara_pequena", lambda m, lado: next(saidas))
        monkeypatch.setattr(recorte, "regiao_da_pessoa", lambda a: None)
        r = mover.RecorteContinuo(a_cada=1, suavizar=0.4)
        r.alfa(self._quadro())
        assert r.alfa(self._quadro())[0, 0] == pytest.approx(0.4)
