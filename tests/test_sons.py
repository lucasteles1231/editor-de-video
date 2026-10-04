"""Os efeitos sonoros: o catálogo, os arquivos da Kenney, o nivelamento e a trilha."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from editor import sons

TAXA = 48_000


def _todos_os_nomes() -> set[str]:
    c = sons.catalogo()
    nomes = {n for t in c["temas"].values() for e in ("aparicao", "transicao", "corte")
             for n in t[e]}
    nomes |= {n for f in c["familias"].values() for n in f["sons"]}
    nomes |= {n for s in c["sequencias"].values() for n in s["sons"]}
    return nomes


class TestOCatalogo:
    def test_cada_tema_cobre_os_tres_eventos(self):
        for nome, tema in sons.catalogo()["temas"].items():
            assert tema["titulo"], nome
            for evento in ("aparicao", "transicao", "corte"):
                assert sons.do_tema(nome, evento), (nome, evento)

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
