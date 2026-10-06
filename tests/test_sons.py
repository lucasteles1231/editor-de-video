"""Os efeitos sonoros: o catálogo, os arquivos da Kenney, o nivelamento e a trilha."""
from __future__ import annotations

import io
import wave
from types import SimpleNamespace

import httpx
import numpy as np
import pytest

from editor import sons

TAXA = 48_000


def _todos_os_nomes() -> set[str]:
    """Os sons nivelados daqui (os crus do Remotion ficam de fora: tocam como vêm)."""
    c = sons.catalogo()
    nomes = {n for t in c["temas"].values() for e in ("aparicao", "transicao", "corte")
             for n in t[e]}
    nomes |= {n for f in c["familias"].values() for n in f["sons"]}
    nomes |= {n for s in c["sequencias"].values() for n in s["sons"]}
    nomes |= {n for e in c["cartoes"].values() for n in e["sons"]}
    return {n for n in nomes if not sons.cru(n)}


def _wav(segundos: float, taxa: int = 44_100) -> bytes:
    t = np.arange(int(segundos * taxa)) / taxa
    som = (0.7 * np.sin(2 * np.pi * 880 * t) * 32767).astype("<i2")
    saida = io.BytesIO()
    with wave.open(saida, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taxa)
        w.writeframes(som.tobytes())
    return saida.getvalue()


class TestOCatalogo:
    def test_cada_tema_cobre_os_tres_eventos(self):
        for nome, tema in sons.catalogo()["temas"].items():
            assert tema["titulo"], nome
            # O tema com sons de cartão próprios (o de notícia) é calado de propósito na
            # aparição e na transição, como o vídeo de referência.
            eventos = ("corte",) if tema.get("cartoes") else ("aparicao", "transicao", "corte")
            for evento in eventos:
                assert sons.do_tema(nome, evento), (nome, evento)

    def test_os_sons_de_cartao_de_cada_tema_existem(self):
        c = sons.catalogo()
        cartoes = [c["cartoes"]] + [t["cartoes"] for t in c["temas"].values() if "cartoes" in t]
        for grupo in cartoes:
            for evento, info in grupo.items():
                ganhos = info.get("ganhos") or [info.get("ganho", 1.0)] * len(info["sons"])
                assert len(ganhos) == len(info["sons"]), evento
                for nome in info["sons"]:
                    assert sons.existe(nome), (evento, nome)

    def test_tema_desconhecido_cai_no_padrao(self):
        assert sons.do_tema("nao-existe", "aparicao") == sons.do_tema("padrao", "aparicao")

    def test_cada_som_existe_e_decodifica(self):
        for nome in sorted(_todos_os_nomes()):
            assert sons.existe(nome), nome
            dados = sons.amostras(nome, TAXA)
            assert len(dados) > TAXA * 0.005, nome         # o clique tem 12 ms
            assert np.isfinite(dados).all() and np.max(np.abs(dados)) <= 1.0, nome

    def test_os_longos_e_os_curtos_respeitam_o_teto(self):
        longos = set(sons.catalogo()["longos"])
        for nome in _todos_os_nomes():
            teto = sons.TETO_LONGO_S if nome in longos else sons.TETO_S
            assert len(sons.amostras(nome, TAXA)) <= round(teto * TAXA) + 1, nome

    def test_saem_nivelados_como_o_ouvido_pesa(self):
        """Nenhum passa do alvo, e quase todos chegam a 4 dB dele. Os que não chegam são
        cliques: o pico bateu no teto, e só o corpo pôde subir."""
        alvo = 20 * np.log10(sons.RMS_ALVO)
        # Os jingles ficam abaixo; as sequências ficam no volume das partes.
        longos = set(sons.catalogo()["longos"]) - set(sons.catalogo()["sequencias"])
        for nome in _todos_os_nomes():
            dados = sons.amostras(nome, TAXA)
            db = 20 * np.log10(sons.volume_percebido(dados, TAXA))
            meu_alvo = alvo + (20 * np.log10(sons.ALVO_DO_LONGO) if nome in longos else 0)
            assert db <= meu_alvo + 0.5, nome
            pico = float(np.max(np.abs(dados)))
            assert db >= meu_alvo - 4 or pico >= sons.PICO_MAXIMO - 0.06, (nome, db, pico)

    def test_o_pop_ficou_no_volume_de_antes(self):
        """Antes do nivelamento, o pop entrava com pico 1 a 35%; o padrão não pode mudar."""
        janela = int(sons.JANELA_S * TAXA)
        antes = sons._rms_mais_forte(sons.pop(TAXA), janela) * 0.35
        agora = sons._rms_mais_forte(sons.amostras("pop", TAXA), janela) * sons.GANHO
        assert 20 * np.log10(agora / antes) == pytest.approx(0, abs=0.5)

    def test_outra_taxa(self):
        assert len(sons.amostras("pluck_001", 24_000)) == pytest.approx(
            len(sons.amostras("pluck_001", TAXA)) / 2, abs=2)


class TestATrilha:
    def _sons(self):
        return [SimpleNamespace(nome="pop", t=0.1), SimpleNamespace(nome="handleCoins", t=1.0),
                SimpleNamespace(nome="teclas", t=2.0, ganho=0.5)]

    def test_mistura_arquivo_sintetizado_e_sequencia(self):
        trilha = sons.trilha(self._sons(), 3.0, TAXA)
        assert len(trilha) == 3 * TAXA
        for ini, fim in ((0.1, 0.3), (1.0, 1.3), (2.0, 2.4)):
            assert np.abs(trilha[int(ini * TAXA):int(fim * TAXA)]).max() > 0.05, ini
        assert np.abs(trilha[int(0.6 * TAXA):int(0.9 * TAXA)]).max() < 1e-6

    def test_a_mesma_entrada_da_a_mesma_trilha(self):
        assert np.array_equal(sons.trilha(self._sons(), 3.0, TAXA),
                              sons.trilha(self._sons(), 3.0, TAXA))

    def test_o_volume_escala(self):
        cheio = sons.trilha(self._sons(), 3.0, TAXA)
        assert np.allclose(sons.trilha(self._sons(), 3.0, TAXA, volume=0.5), cheio * 0.5)

    def test_o_ganho_do_som_conta(self):
        um = [SimpleNamespace(nome="tick_002", t=0.0)]
        baixo = [SimpleNamespace(nome="tick_002", t=0.0, ganho=0.45)]
        assert np.allclose(sons.trilha(baixo, 1.0, TAXA), sons.trilha(um, 1.0, TAXA) * 0.45)

    def test_nome_desconhecido_e_o_fim_do_video_nao_quebram(self):
        trilha = sons.trilha([SimpleNamespace(nome="nao-existe", t=0.1),
                              SimpleNamespace(nome="jingles_NES12", t=0.9)], 1.0, TAXA)
        assert len(trilha) == TAXA

    def test_a_demonstracao_de_cada_tema(self):
        for tema in sons.temas():
            demo = sons.demonstracao(tema, TAXA)
            assert len(demo) > 3 * TAXA and np.abs(demo).max() > 0.05, tema


class TestOTemaDeNoticia:
    """Os sons do vídeo de referência (os do Remotion), nos volumes dele."""

    def test_os_sons_dos_cartoes_vem_do_tema(self):
        assert sons.do_cartao("flash", "noticia") == (["remotion-obturador"], [0.55])
        assert sons.do_cartao("erro", "noticia") == (["remotion-erro-xp", "remotion-disco"],
                                                     [0.3, 0.22])
        assert sons.do_cartao("gancho", "noticia") == ([], [])      # calado de propósito
        assert sons.do_cartao("selo", "noticia") == ([], [])        # a etiqueta que explica
        assert sons.do_cartao("chamada", "noticia") == (["remotion-whoosh"], [0.3])
        # os outros temas ficam com os da Kenney
        assert sons.do_cartao("flash", "gameplay") == (["obturador"], [0.9])
        assert sons.do_cartao("gancho", "padrao") == (["impactPunch_heavy_000"], [0.9])

    def test_os_crus_tocam_como_vem(self):
        # o clique do Remotion: o pico em −3 dBFS como no arquivo (meio dB para lá ou para
        # cá, da troca de 44,1 para 48 kHz), sem nivelar e sem o GANHO por cima
        dados = sons.amostras("remotion-clique", TAXA)
        assert 20 * np.log10(np.abs(dados).max()) == pytest.approx(-3.0, abs=0.6)
        trilha = sons.trilha([SimpleNamespace(nome="remotion-clique", t=0.0, ganho=0.42)],
                             1.0, TAXA)
        assert np.abs(trilha).max() == pytest.approx(np.abs(dados).max() * 0.42, rel=0.01)

    def test_sem_internet_toca_a_reserva(self):
        sons._amostras.cache_clear()
        try:
            assert np.array_equal(sons.amostras("remotion-boom", TAXA),
                                  sons.amostras("impactPunch_heavy_000", TAXA))
            assert not list(sons.pasta_dos_baixados().glob("*.wav"))
        finally:
            sons._amostras.cache_clear()

    def test_baixa_uma_vez_inteiro_e_guarda(self, monkeypatch):
        pedidos: list[str] = []

        def remotion(pedido: httpx.Request) -> httpx.Response:
            pedidos.append(str(pedido.url))
            return httpx.Response(200, content=_wav(1.3))

        monkeypatch.setattr(sons, "_transporte", httpx.MockTransport(remotion))
        sons._amostras.cache_clear()
        try:
            dados = sons.amostras("remotion-ding", TAXA)
            assert pedidos == ["https://remotion.media/ding.wav"]
            assert (sons.pasta_dos_baixados() / "remotion-ding.wav").is_file()
            # inteiro (cru: até 2 s, e não o meio segundo dos outros) e sem nivelar
            assert len(dados) == pytest.approx(1.3 * TAXA, abs=100)
            assert np.abs(dados).max() == pytest.approx(0.7, abs=0.02)
            sons._amostras.cache_clear()
            sons.amostras("remotion-ding", TAXA)
            assert len(pedidos) == 1                  # da segunda vez, vem do disco
        finally:
            sons._amostras.cache_clear()

    def test_sem_som_de_transicao(self):
        from editor import plano

        assert plano.montar_sons([], [], [(0.0, 1.0), (2.0, 1.12), (5.0, 1.0)],
                                 tema="noticia", sons_por_palavra=False) == []

    def test_os_cartoes_no_plano(self):
        from editor import plano
        from editor.cartoes import Cartao, Item

        cartoes = [Cartao("selo", 0.0, 2.0, "SEM CENSURA", forte=0.0),
                   Cartao("carimbo", 2.5, 5.0, "APAGADA", "404", forte=3.0),
                   Cartao("carimbo", 6.0, 8.0, "REMOVIDA", "FICHA", forte=6.5),
                   Cartao("quadro", 9.0, 14.0, "PAÍSES", itens=[Item("EUROPA", 9.0, "18"),
                                                               Item("EUA", 10.0, "17+")])]
        sons_ = plano.com_sons_dos_cartoes([], cartoes, tema="noticia")
        assert [(s.nome, s.t, s.ganho) for s in sons_] == [
            ("remotion-whoosh", 2.5, 0.28), ("remotion-erro-xp", 3.0, 0.3),
            ("remotion-whoosh", 6.0, 0.28), ("remotion-disco", 6.5, 0.22),
            ("remotion-whoosh", 9.0, 0.28), ("remotion-clique", 10.0, 0.42)]
        # com um bipe na palavra da linha (meio segundo depois de ela entrar), sem clique
        com_bipe = plano.com_sons_dos_cartoes([], cartoes, [(10.5, 10.7)], tema="noticia")
        assert "remotion-clique" not in [s.nome for s in com_bipe]
        assert "remotion-whoosh" in [s.nome for s in com_bipe]
