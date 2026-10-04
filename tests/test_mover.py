"""A pessoa que muda de lugar: as posições, o fundo sem ela e o quadro composto.

O recorte é o falso (ver conftest): uma silhueta de busto no meio do quadro.
"""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from editor import mover, plano, recorte

L, A = 180, 320                      # um quadro em pé, pequeno


def _caixas(alfa):
    pessoa, rosto = recorte.caixas(alfa)
    assert pessoa is not None and rosto is not None
    return pessoa, rosto


def _quadro_com_silhueta(fundo=(40, 90, 200), pessoa=(250, 250, 250)) -> np.ndarray:
    """O quadro pintado do jeito que o recorte falso enxerga: a silhueta é a pessoa."""
    q = np.empty((A, L, 3), np.uint8)
    q[:] = fundo
    q[recorte._silhueta_falsa(A, L) > 0.5] = pessoa
    return q


def _plano(posicao="esquerda", inicio=1.0, fim=3.0, volta_no_corte=True):
    return plano.Plano(10.0, True, [], [], [(0.0, 1.0)], [], [], [],
                       movimentos=[plano.Movimento(inicio, fim, posicao, volta_no_corte)])


def _centro_da_pessoa(img: Image.Image) -> tuple[float, float]:
    """O centro dos pixels claros (a pessoa pintada de branco)."""
    m = np.asarray(img.convert("L")) > 200
    ys, xs = np.nonzero(m)
    return xs.mean() / img.width, ys.mean() / img.height


class TestAsPosicoes:
    def setup_method(self):
        self.pessoa, self.rosto = _caixas(recorte._silhueta_falsa(A, L))

    def _rosto_depois(self, t: mover.Transformacao) -> tuple[float, float]:
        fx = (self.rosto.x0 + self.rosto.x1) / 2 * L
        fy = (self.rosto.y0 + self.rosto.y1) / 2 * A
        return (t.escala * fx + t.dx) / L, (t.escala * fy + t.dy) / A

    def test_cada_posicao_leva_o_rosto_para_o_lugar_dela(self):
        alvo = lambda pos: mover.alvo(pos, self.pessoa, self.rosto, L, A, vertical=True)  # noqa: E731
        assert self._rosto_depois(alvo("esquerda"))[0] == pytest.approx(0.34, abs=0.01)
        assert self._rosto_depois(alvo("direita"))[0] == pytest.approx(0.66, abs=0.01)
        assert self._rosto_depois(alvo("cima"))[1] == pytest.approx(0.26, abs=0.01)
        _rx, ry = self._rosto_depois(alvo("baixo"))
        assert ry > (self.rosto.y0 + self.rosto.y1) / 2 and ry <= 0.58 + 1e-6
        # perto cresce em volta do rosto: o rosto não sai do lugar
        perto = alvo("perto")
        assert perto.escala > 1
        assert self._rosto_depois(perto) == pytest.approx(
            ((self.rosto.x0 + self.rosto.x1) / 2, (self.rosto.y0 + self.rosto.y1) / 2), abs=1e-6)
        assert alvo("longe").escala < 1

    def test_deitado_os_lados_vao_mais_longe(self):
        t = mover.alvo("esquerda", self.pessoa, self.rosto, L, A, vertical=False)
        assert self._rosto_depois(t)[0] == pytest.approx(0.30, abs=0.01)

    def test_posicao_desconhecida(self):
        with pytest.raises(ValueError):
            mover.alvo("diagonal", self.pessoa, self.rosto, L, A, vertical=True)

    def test_a_meio_caminho(self):
        t = mover.Transformacao(0.8, 40.0, -20.0)
        assert t.em(0.0) == mover.Transformacao(1.0, 0.0, 0.0)
        assert t.em(1.0) == t
        assert t.em(0.5) == mover.Transformacao(0.9, 20.0, -10.0)


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
        longe = mover.Transformacao(0.7, 27.0, 40.0)
        assert mover.expostas(longe, L, A) == {"esquerda": True, "direita": True,
                                               "topo": True, "baixo": True}
        perto = mover.Transformacao(1.3, -27.0, -48.0)
        assert not any(mover.expostas(perto, L, A).values())


class TestOFundo:
    @pytest.mark.parametrize("onde", [0.32, 0.6])          # a cabeça e o meio do tronco
    def test_o_fundo_de_video_nao_tem_a_pessoa(self, onde):
        """Só desfocar deixava um fantasma dela; a região é preenchida pelo que há em volta."""
        largura, altura = 360, 640
        q = np.empty((altura, largura, 3), np.uint8)
        q[:] = (40, 90, 200)
        alfa = recorte._silhueta_falsa(altura, largura)
        q[alfa > 0.5] = (250, 30, 30)
        fundo = np.asarray(mover.fundo_sem_a_pessoa(Image.fromarray(q), alfa, largura, altura))
        r, _g, b = fundo[int(altura * onde), largura // 2].astype(int)
        assert b > 2 * r, "o vermelho da pessoa vazou para o fundo"
        assert fundo.mean() < q.mean()                      # e ele fica mais escuro

    def test_fundo_de_cor(self):
        f = np.asarray(mover.fundo_de_cor("lima", L, A)).astype(int)
        assert f.shape == (A, L, 3)
        assert f[int(A * 0.4), L // 2].sum() > f[0, 0].sum()    # mais claro atrás do rosto


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


class TestOQuadro:
    def test_fora_do_trecho_e_o_quadro_de_sempre(self):
        p = mover.Pessoa(_plano(), L, A)
        assert p.quadro(_quadro_com_silhueta(), 0.5) is None
        assert p.quadro(_quadro_com_silhueta(), 3.5) is None

    def test_a_pessoa_vai_para_a_esquerda_e_volta(self):
        p = mover.Pessoa(_plano("esquerda"), L, A)
        q = _quadro_com_silhueta()
        img = p.quadro(q, 2.0)
        assert img is not None and img.size == (L, A)
        cx, _ = _centro_da_pessoa(img)
        assert cx < 0.45, f"o centro da pessoa ficou em {cx:.2f}"
        assert p.lado_livre(2.0) == 1                  # o ícone vai para a direita
        assert p.quadro(q, 3.2) is None and p.lado_livre(3.2) == 0

    def test_o_primeiro_quadro_e_igual_ao_de_sempre(self):
        """A pessoa parte do lugar dela, e o fundo ainda é o quadro normal."""
        p = mover.Pessoa(_plano("longe"), L, A)
        q = _quadro_com_silhueta()
        img = np.asarray(p.quadro(q, 1.0)).astype(int)
        assert np.abs(img - q.astype(int)).mean() < 2.0

    def test_longe_encolhe_e_cor_pinta_o_fundo(self):
        p = mover.Pessoa(_plano("longe"), L, A, fundo="cor", cor="roxo")
        img = p.quadro(_quadro_com_silhueta(), 2.5)
        m = np.asarray(img.convert("L")) > 200
        assert m.mean() < (recorte._silhueta_falsa(A, L) > 0.5).mean()   # menor
        canto = np.asarray(img)[A // 10, L // 10].astype(int)
        assert canto[2] > canto[1]                       # roxo, não o azul do quadro

    def test_volta_deslizando_quando_nao_acaba_num_corte(self):
        p = mover.Pessoa(_plano("esquerda", 1.0, 3.0, volta_no_corte=False), L, A)
        q = _quadro_com_silhueta()
        meio = _centro_da_pessoa(p.quadro(q, 2.0))[0]
        quase_no_fim = _centro_da_pessoa(p.quadro(q, 2.98))[0]
        assert meio < quase_no_fim < 0.5 + 0.02

    def test_sem_pessoa_fica_no_lugar(self, monkeypatch):
        monkeypatch.setattr(recorte, "mascara_pequena",
                            lambda m, lado: np.zeros((64, 32), np.float32))
        p = mover.Pessoa(_plano(), L, A)
        assert p.quadro(_quadro_com_silhueta(), 2.0) is None

    def test_recorta_um_quadro_sim_um_nao(self):
        p = mover.Pessoa(_plano("perto", 0.0, 9.0), L, A)
        quadros = [_quadro_com_silhueta() for _ in range(10)]
        for k, q in enumerate(quadros):
            p.quadro(q, 0.5 + k / 30)
            p.quadro(q, 0.5 + k / 30 + 0.001)          # o mesmo quadro de novo: não recorta
        assert p.recortados == 5

    def test_empurrao_cresce_em_volta_do_rosto(self):
        t = mover.Transformacao(1.0, 0.0, 0.0).empurrada(0.1, 50.0, 40.0)
        assert t.escala == pytest.approx(1.1)
        assert (t.escala * 50 + t.dx, t.escala * 40 + t.dy) == pytest.approx((50.0, 40.0))


def test_as_opcoes_conferem_o_fundo_e_a_cor():
    from editor import opcoes

    assert opcoes.OpcoesDeEdicao(mover_pessoa=True).problemas() == []
    assert opcoes.OpcoesDeEdicao(fundo_da_pessoa="foto").problemas()
    assert opcoes.OpcoesDeEdicao(cor_do_fundo="bege").problemas()
    assert set(mover.CORES) == set(opcoes.CORES)       # as mesmas cores da thumbnail
    vindo_da_pagina = opcoes.OpcoesDeEdicao.de_dict({"mover_pessoa": True, "cor_do_fundo": "lima"})
    assert vindo_da_pagina.mover_pessoa and vindo_da_pagina.cor_do_fundo == "lima"
