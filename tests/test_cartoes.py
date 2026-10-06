"""
Os cartões animados: cada modelo desenhado em três tamanhos, a lista item a item, a
linha falada do quadro acesa, os sons e o ponto para onde a câmera empurra.
"""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from editor import cartoes as c_mod
from editor.cartoes import Cartao, Item


def _cartoes() -> list[Cartao]:
    return [
        Cartao("selo", 0.0, 2.0, "SEM CENSURA", icone="alerta", cor="rosa", forte=0.0),
        Cartao("selo", 1.0, 3.0, "SEGUE PRA MAIS", icone="joinha", cor="ciano"),
        Cartao("lista", 1.0, 5.0, "REVELAÇÕES", itens=[
            Item("COCA**NA NO INVENTÁRIO", 1.0, icone="caveira"), Item("DECA**TAÇÃO", 2.0),
            Item("CENAS DE SE**", 3.0)]),
        Cartao("quadro", 1.0, 5.0, "CLASSIFICAÇÃO", itens=[
            Item("EUROPA", 1.0, "PEGI 18"), Item("EUA", 2.0, "M 17+"),
            Item("AUSTRÁLIA", 3.0, "R18+")]),
        Cartao("enquete", 1.0, 5.0, "PASSOU DO PONTO?", itens=[
            Item("TÁ CERTA", 1.5), Item("PASSOU DO PONTO", 2.5)], forte=3.5),
        Cartao("carimbo", 1.0, 4.0, "APAGADA", "404", forte=1.6),
        Cartao("destaque", 1.0, 4.0, "19 DE NOVEMBRO", "LANÇAMENTO", cor="rosa", forte=1.2),
        Cartao("flash", 1.0, 3.0, "OS FÃS PRINTARAM", forte=1.2),
    ]


def _desenhado(c: Cartao, t: float, largura: int = 540) -> np.ndarray:
    tela = Image.new("RGBA", (largura, round(largura * 9 / 16)), (0, 0, 0, 0))
    c_mod.desenhar(tela, c, t, palco=c.no_palco)
    return np.asarray(tela)


def _tinta(q: np.ndarray) -> int:
    """Quantos pixels têm alguma coisa desenhada."""
    return int((q[..., 3] > 0).sum())


class TestODesenho:
    @pytest.mark.parametrize("largura", [270, 1080, 1920])
    @pytest.mark.parametrize("c", _cartoes(), ids=lambda c: f"{c.modelo}-{c.texto[:8]}")
    def test_cada_modelo_em_cada_tamanho(self, c, largura):
        for t in (c.inicio - 0.5, c.inicio, c.inicio + 0.1, (c.inicio + c.fim) / 2,
                  c.fim - 0.05, c.fim + 0.5):
            q = _desenhado(c, t, largura)
            if not c.inicio <= t < c.fim:
                assert _tinta(q) == 0, t                     # fora do tempo, nada
        assert _tinta(_desenhado(c, (c.inicio + c.fim) / 2, largura)) > 0

    def test_cada_cartao_so_na_sua_camada(self):
        for c in _cartoes():
            tela = Image.new("RGBA", (540, 304), (0, 0, 0, 0))
            c_mod.desenhar(tela, c, (c.inicio + c.fim) / 2, palco=not c.no_palco)
            assert _tinta(np.asarray(tela)) == 0, c.modelo

    def test_a_lista_entra_item_a_item(self):
        lista = next(c for c in _cartoes() if c.modelo == "lista")
        um, dois, tres = (_tinta(_desenhado(lista, t)) for t in (1.5, 2.5, 3.5))
        assert um < dois < tres

    def test_a_linha_falada_do_quadro_acende(self):
        acesa = np.asarray(c_mod.linha_do_quadro("EUROPA", "18", "vermelho", "", 900, 100, 1.0,
                                                 True))
        apagada = np.asarray(c_mod.linha_do_quadro("EUROPA", "18", "vermelho", "", 900, 100,
                                                   1.0, False))
        # o fundo claro da linha acesa cobre a linha inteira; a apagada é só o texto
        assert _tinta(acesa) > 2 * _tinta(apagada)

    def test_o_carimbo_cai_no_momento_forte(self):
        carimbo = next(c for c in _cartoes() if c.modelo == "carimbo")
        vermelho = np.array(c_mod.CORES["vermelho"])

        def vermelhos(t: float) -> int:
            q = _desenhado(carimbo, t)
            return int((np.abs(q[..., :3].astype(int) - vermelho).max(axis=2) < 30).sum())

        assert vermelhos(1.5) == 0 and vermelhos(2.2) > 200

    def test_o_rotulo_comprido_cabe_na_mira_da_camera(self):
        # mirando o ponto forte no foco em pé, a câmera mostra de 276 a 960 do palco
        pagina = c_mod.pagina("PÁGINA DA PEGI", 1.0)
        q = np.asarray(pagina)
        # o rótulo é a tinta escura em cima do cartão (opaco; a sombra em volta, não)
        escuro = (q[..., :3].max(axis=2) < 60) & (q[..., 3] == 255)
        colunas = np.where(escuro.any(axis=0))[0]
        margem = pagina.info["margem"]
        x_no_palco = colunas - margem + (540 - c_mod.conteudo(pagina)[0] / 2)
        assert x_no_palco.min() >= 276 and x_no_palco.max() <= 960


class TestOsSons:
    def test_os_eventos_de_cada_modelo(self):
        sons = {f"{c.modelo}-{c.texto[:4]}": c_mod.eventos_de_som(c) for c in _cartoes()}
        assert sons["selo-SEM "] == [("gancho", 0.0)]               # o gancho é outro evento
        assert sons["selo-SEGU"] == [("chamada", 1.0)]          # chama a audiência
        # os três itens têm palavra censurada (a voz leva o bipe ali): só a entrada toca
        assert sons["lista-REVE"] == [("entrada", 1.0)]
        # a primeira linha entra junto com o quadro e fica com o som da entrada
        assert sons["quadro-CLAS"] == [("entrada", 1.0), ("item", 2.0), ("item", 3.0)]
        assert sons["enquete-PASS"] == [("item", 1.5), ("item", 2.5), ("comenta", 3.5)]
        assert sons["carimbo-APAG"] == [("entrada", 1.0), ("erro", 1.6)]
        assert sons["destaque-19 D"] == [("ding", 1.2)]             # uma data: ding
        assert sons["flash-OS F"] == [("flash", 1.2)]
        numero = Cartao("destaque", 0.0, 2.0, "18", forte=0.5)
        assert c_mod.eventos_de_som(numero) == [("boom", 0.5)]


class TestACamera:
    def test_o_ponto_forte(self):
        carimbo, destaque = (c for c in _cartoes() if c.modelo in ("carimbo", "destaque"))
        t, (x, y) = c_mod.ponto_forte(carimbo)
        assert t == 1.6 and 540 < x < 540 + c_mod.CARIMBO[0] and y == 304 + c_mod.CARIMBO[1]
        assert c_mod.ponto_forte(destaque) == (1.2, (540, 304))
        assert c_mod.ponto_forte(_cartoes()[0]) is None

    def test_colar_numa_tela_rgb(self):
        tela = Image.new("RGB", (100, 100), (0, 0, 0))
        sprite = Image.new("RGBA", (20, 20), (255, 0, 0, 255))
        c_mod.colar(tela, sprite, 95, 50)                       # metade para fora
        q = np.asarray(tela)
        assert q[50, 99, 0] == 255 and q[50, 80, 0] == 0
