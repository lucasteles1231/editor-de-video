"""
A janela e a câmera: a geometria nos três formatos, as transições (sempre partindo de
onde a anterior estava), a câmera que nunca mostra a borda do palco, o diretor e o
quadro composto.
"""
from __future__ import annotations

import itertools

import numpy as np
import pytest
from PIL import Image

from editor import animacao as a
from editor import janela
from editor.cartoes import Cartao, Item
from editor.janela import Direcao, Geometria, Plano
from editor.transcricao import Palavra

FORMATOS = [(1080, 1920), (1080, 1080), (1920, 1080), (720, 1280)]


class TestAGeometria:
    @pytest.mark.parametrize(("largura", "altura"), FORMATOS)
    def test_tudo_cabe_no_quadro(self, largura, altura):
        geo = Geometria(largura, altura)
        for nome, (x, y, w, h, legenda) in geo.janelas.items():
            assert x >= 0 and x + w <= largura + 1e-6, nome
            assert y >= 0 and y + h <= altura + 1e-6, nome
            assert 0 < legenda < altura, nome
        for cx, tamanho in geo.lugares.values():
            assert 0 < cx < largura and 0 < tamanho < altura
        assert geo.palco[0] / geo.palco[1] == pytest.approx(16 / 9, abs=0.01)

    def test_em_pe_as_medidas_do_chat(self):
        geo = Geometria(1080, 1920)
        assert geo.formato == "em_pe"
        assert geo.janelas["padrao"][1:4] == (640, 1080, 608)
        assert geo.janelas["foco"][1:4] == (400, 1080, 960)
        assert geo.lugares["centro"] == (540, 600)
        # o personagem fica enfiado 5% atrás da borda de cima da janela
        e = geo.estado(Plano(0.0, "padrao", "centro"))
        assert e.piso == pytest.approx(640 + 600 * 0.05)

    def test_os_formatos(self):
        assert Geometria(1080, 1080).formato == "quadrado"
        assert Geometria(1920, 1080).formato == "deitado"
        deitado = Geometria(1920, 1080)
        # deitado, a janela é a tela inteira nos dois planos
        assert deitado.janelas["padrao"][:4] == deitado.janelas["foco"][:4] == (0, 0, 1920, 1080)

    def test_a_legenda_acompanha_a_janela(self):
        geo = Geometria(1080, 1920)
        padrao = geo.estado(Plano(0.0, "padrao"))
        foco = geo.estado(Plano(0.0, "foco"))
        assert foco.legenda > padrao.legenda
        assert foco.legenda > foco.y + foco.altura           # embaixo da janela


class TestATransicao:
    GEO = Geometria(1080, 1920)

    def test_leva_11_quadros_na_curva(self):
        d = Direcao([Plano(0.0, "padrao"), Plano(1.0, "foco")], self.GEO)
        antes, _ = d.em(0.99)
        meio, _ = d.em(1.0 + a.TRANSICAO / 2)
        depois, _ = d.em(1.0 + a.TRANSICAO + 0.01)
        assert antes.altura == 608 and depois.altura == 960
        assert meio.altura == pytest.approx(608 + (960 - 608) * a.CAMERA(0.5), abs=0.5)

    def test_parte_de_onde_a_anterior_estava(self):
        # a segunda deixa chega no meio da primeira transição: não há pulo
        t2 = 1.0 + a.TRANSICAO * 0.4
        d = Direcao([Plano(0.0, "padrao"), Plano(1.0, "foco"), Plano(t2, "padrao")], self.GEO)
        logo_antes, _ = d.em(t2 - 1e-4)
        logo_depois, _ = d.em(t2 + 1e-4)
        assert logo_depois.altura == pytest.approx(logo_antes.altura, abs=1.0)

    def test_o_pulinho_so_na_troca_de_lugar(self):
        d = Direcao([Plano(0.0, "padrao", "centro"), Plano(1.0, "foco", "esquerda"),
                     Plano(2.0, "padrao", "esquerda")], self.GEO)
        _, pulo = d.em(1.0 + a.TRANSICAO / 2)
        assert pulo == pytest.approx(1.0, abs=0.01)
        _, sem = d.em(2.0 + a.TRANSICAO / 2)
        assert sem == 0.0


class TestACamera:
    @pytest.mark.parametrize("zoom", [1.0, 1.3, 2.0])
    @pytest.mark.parametrize("foco", [(0, 0), (1080, 608), (540, 304), (1000, 20)])
    @pytest.mark.parametrize(("largura", "altura"), FORMATOS)
    def test_nunca_sai_do_palco(self, zoom, foco, largura, altura):
        # Um palco todo branco: se a câmera passasse da borda dele, a sobra sairia preta
        # (ou o recorte daria erro).
        geo = Geometria(largura, altura)
        palco = Image.new("RGB", geo.palco, (255, 255, 255))
        for nome in ("padrao", "foco"):
            estado = geo.estado(Plano(0.0, nome, zoom=zoom, foco=foco))
            q = np.asarray(janela.camera(palco, estado))
            assert q.shape[:2] == (round(estado.altura), round(estado.largura))
            assert q.min() >= 250, (nome, zoom, foco)

    def test_o_zoom_mira_o_ponto(self):
        palco = Image.new("RGB", (1080, 608), (255, 0, 0))
        palco.paste((0, 0, 255), (540, 0, 1080, 608))           # a metade da direita, azul
        estado = Geometria(1080, 1920).estado(Plano(0.0, "padrao", zoom=2.0,
                                                    foco=(1000, 300)))
        q = np.asarray(janela.camera(palco, estado))
        assert q[..., 2].mean() > 200 and q[..., 0].mean() < 50


def _carimbo(inicio=2.0, forte=2.6, fim=5.0) -> Cartao:
    return Cartao("carimbo", inicio, fim, "APAGADA", "404", forte=forte)


class TestODiretor:
    def test_comeca_no_foco_e_termina_no_padrao(self):
        planos = janela.dirigir(20.0, [], [(0.0, 1.0)])
        assert (planos[0].t, planos[0].janela, planos[0].lugar) == (0.0, "foco", "esquerda")
        assert (planos[-1].janela, planos[-1].lugar) == ("padrao", "centro")
        assert planos[-1].t == pytest.approx(18.0)

    def test_no_carimbo_empurra_ate_o_ponto_e_volta(self):
        c = _carimbo()
        planos = janela.dirigir(20.0, [c], [(0.0, 1.0)])
        no_cartao = [p for p in planos if 2.0 <= p.t <= 5.0]
        assert (no_cartao[0].janela, no_cartao[0].lugar) == ("padrao", "centro")
        forte = next(p for p in no_cartao if p.t == pytest.approx(2.6))
        assert forte.janela == "foco" and forte.foco is not None
        # a mira fica entre o rótulo e o carimbo, e o rótulo continua inteiro na tela
        assert 540 < forte.foco[0] < 695
        assert no_cartao[-1].janela == "padrao" and no_cartao[-1].t == pytest.approx(4.2)

    def test_o_destaque_empurra_no_padrao(self):
        c = Cartao("destaque", 2.0, 6.0, "18", "NOTA", forte=2.5)
        forte = next(p for p in janela.dirigir(20.0, [c], [(0.0, 1.0)])
                     if p.t == pytest.approx(2.5))
        assert forte.janela == "padrao" and forte.zoom == janela.ZOOM_DO_DESTAQUE

    def test_a_lista_troca_o_lado_a_cada_item(self):
        c = Cartao("lista", 3.0, 9.0, itens=[Item("UM", 3.0), Item("DOIS", 4.5),
                                              Item("TRÊS", 6.0)])
        planos = [p for p in janela.dirigir(20.0, [c], [(0.0, 1.0)]) if 3.0 <= p.t <= 9.0]
        assert all(p.janela == "foco" for p in planos)
        lados = [p.lugar for p in planos]
        assert all(x != y for x, y in itertools.pairwise(lados))

    def test_os_zooms_do_plano_viram_foco_e_padrao_fora_dos_cartoes(self):
        c = _carimbo()
        zooms = [(0.0, 1.0), (3.0, 1.12), (8.0, 1.12), (11.0, 1.0)]
        planos = janela.dirigir(20.0, [c], zooms)
        assert not any(p.t == 3.0 for p in planos)              # dentro do cartão: não
        assert next(p for p in planos if p.t == 8.0).janela == "foco"
        assert next(p for p in planos if p.t == 11.0).janela == "padrao"

    def test_planos_colados_ficam_com_o_mais_importante(self):
        planos = janela.dirigir(20.0, [_carimbo(2.0, 2.3)], [(0.0, 1.0)])
        tempos = [p.t for p in planos]
        assert all(b - a_ >= janela.PLANO_MINIMO_S for a_, b in itertools.pairwise(tempos))

    def test_deitado_o_foco_e_um_empurrao(self):
        planos = janela.dirigir(20.0, [], [(0.0, 1.0)], deitado=True)
        assert planos[0].janela == "foco" and planos[0].zoom == pytest.approx(1.12)


class TestOQuadro:
    class _Fundo:
        def em(self, _t):
            q = np.zeros((360, 640, 3), np.uint8)
            q[..., 2] = 200
            return q

    @pytest.mark.parametrize(("largura", "altura"), [(540, 960), (540, 540), (960, 540)])
    def test_compoe_em_cada_formato(self, largura, altura):
        c = _carimbo(0.5, 0.8, 3.0)
        m = janela.MontadorDeJanela(largura, altura, fundo=self._Fundo(), fundo_na_saida=True,
                                    planos=janela.dirigir(4.0, [c], [(0.0, 1.0)],
                                                          deitado=largura > altura),
                                    cartoes=[c])
        for t in (0.2, 1.0, 2.5):
            img, estado = m.quadro(t, t)
            assert img.size == (largura, altura) and img.mode == "RGB"
            assert estado.legenda > 0

    def test_a_boca_so_mexe_na_fala(self):
        falas = janela.falas([Palavra("a", 0.0, 0.3), Palavra("b", 0.4, 0.7),
                              Palavra("c", 2.0, 2.3)])
        # 100 ms entre "a" e "b": um trecho só; 1,3 s até "c": outro
        assert falas == [(0.0, 0.7), (2.0, 2.3)]
        m = janela.MontadorDeJanela(540, 960, fundo=self._Fundo(), fundo_na_saida=True,
                                    falas=falas)
        assert m.falando(0.5) and m.falando(2.35) and not m.falando(1.2)
