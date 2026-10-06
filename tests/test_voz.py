"""A voz: o volume (BS.1770), a junção das partes, a limpeza, o estúdio e o bipe."""
from __future__ import annotations

import numpy as np
import pytest

from editor import voz
from editor.transcricao import Palavra

T = voz.TAXA


def _seno(hz: float, amplitude: float, segundos: float) -> np.ndarray:
    t = np.arange(int(segundos * T)) / T
    return (amplitude * np.sin(2 * np.pi * hz * t)).astype(np.float32)


def _fala(segundos: float, ganho: float, semente: int = 1, chiado: float = 0.0) -> np.ndarray:
    """Um sinal que lembra fala: rajadas de ruído colorido de 0,3 s com pausas de 0,15 s."""
    rng = np.random.default_rng(semente)
    n = int(segundos * T)
    x = np.convolve(rng.standard_normal(n), np.ones(12) / 12, mode="same").astype(np.float32)
    t = np.arange(n) / T
    envelope = ((t % 0.45) < 0.3).astype(np.float32)
    return (x * envelope * ganho + rng.standard_normal(n).astype(np.float32) * chiado)


class TestOVolume:
    def test_um_seno_de_1khz(self):
        # A BS.1770 mede um seno de 1 kHz em 0 dBFS como −3,01 LUFS (mono).
        assert voz.lufs(_seno(1000, 0.1, 3.0)) == pytest.approx(-23.0, abs=0.3)

    def test_silencio(self):
        assert voz.lufs(np.zeros(T * 2, np.float32)) == -70.0

    def test_nivelar_e_limitar(self):
        x = voz.nivelar(_fala(4.0, 0.05), -15.0)
        assert voz.lufs(x) == pytest.approx(-15.0, abs=0.2)
        y = voz.limitar(x * 4, -1.5)
        assert 20 * np.log10(np.abs(y).max()) <= -1.49

    def test_filtrar_mantem_o_comprimento(self):
        x = _fala(1.0, 0.1)
        assert len(voz.filtrar(x, voz.NITIDA)) == len(x)
        assert len(voz.filtrar(x, voz.CORO_ESQUERDA)) == len(x)


class TestAsPartes:
    def test_aparar_as_pontas(self):
        x = np.concatenate([np.zeros(T, np.float32), _fala(1.0, 0.1), np.zeros(T, np.float32)])
        aparado, corte = voz.aparar(x)
        assert corte == pytest.approx(1.0 - voz.MARGEM_S, abs=0.02)
        assert len(aparado) / T == pytest.approx(1.0 + 2 * voz.MARGEM_S, abs=0.05)

    def test_juntar_nivelando(self):
        # cinco partes com até 6 dB de diferença saem a menos de 1 dB umas das outras
        ganhos = [0.05, 0.1, 0.05, 0.07, 0.07]
        partes = [_fala(2.0, g, semente=k) for k, g in enumerate(ganhos)]
        junto, onde = voz.juntar(partes, "limpa")
        volumes = [voz.lufs(junto[int(p.inicio * T):int((p.inicio + p.duracao) * T)])
                   for p in onde]
        assert max(volumes) - min(volumes) < 1.0
        assert onde[1].inicio == pytest.approx(onde[0].duracao + voz.PAUSA_S, abs=1e-3)

    def test_as_palavras_vao_para_o_tempo_do_junto(self):
        partes = [voz.Parte(0.0, 0.5, 2.0), voz.Parte(2.3, 0.2, 1.5)]
        palavras = [[Palavra("oi", 0.6, 0.9)], [Palavra("tchau", 0.4, 0.8)]]
        juntas = voz.palavras_nas_partes(palavras, partes)
        assert [(w.texto, w.inicio, w.fim) for w in juntas] == [
            ("oi", 0.1, 0.4), ("tchau", 2.5, 2.9)]

    def test_a_limpa_baixa_o_chiado(self):
        x = _fala(4.0, 0.1, chiado=0.01)
        limpa = voz.tirar_ruido(x)
        pausas = (np.arange(len(x)) / T % 0.45) > 0.33
        assert np.sqrt(np.mean(limpa[pausas] ** 2)) < np.sqrt(np.mean(x[pausas] ** 2)) / 2


class TestOEstilo:
    def test_os_tres_niveis(self):
        x, _ = voz.juntar([_fala(3.0, 0.05)], "limpa")
        for nivel in voz.NIVEIS:
            y = voz.tratar(x, nivel)
            assert y.ndim == 2 and y.shape[1] == 2 and len(y) == len(x)
            if nivel != "original":
                assert voz.lufs(y) == pytest.approx(voz.FINAL_LUFS, abs=0.5)
                assert 20 * np.log10(np.abs(y).max()) <= voz.PICO_DB + 0.01

    def test_o_estudio_abre_em_estereo(self):
        x, _ = voz.juntar([_fala(3.0, 0.05)], "estudio")
        y = voz.tratar(x, "estudio")
        assert not np.allclose(y[:, 0], y[:, 1])


class TestOBipe:
    def test_zera_a_voz_so_dentro(self):
        x = np.stack([_seno(200, 0.3, 2.0)] * 2, axis=1)
        y = voz.bipar(x, [(0.5, 0.8)])
        dentro, fora = y[int(0.55 * T):int(0.75 * T)], y[int(1.2 * T):int(1.5 * T)]
        assert np.allclose(fora, x[int(1.2 * T):int(1.5 * T)])
        # dentro, sobra o bipe de 1 kHz: a voz de 200 Hz some
        espectro = np.abs(np.fft.rfft(dentro[:, 0]))
        freqs = np.fft.rfftfreq(len(dentro), 1 / T)
        assert freqs[espectro.argmax()] == pytest.approx(1000, abs=10)

    def test_a_silaba_escondida(self):
        # "sexo" falado de 1,0 a 1,5 s: a sílaba escondida ("xo") fica na segunda metade
        x = np.zeros(3 * T, np.float32)
        x[int(1.0 * T):int(1.5 * T)] = _fala(0.5, 0.2)[: int(0.5 * T)]
        trechos = voz.trechos_do_bipe([Palavra("sexo", 1.0, 1.5)], x, ["sexo"])
        assert len(trechos) == 1
        a, b = trechos[0]
        assert 1.1 < a < 1.35 and b <= 1.65
        assert voz.trechos_do_bipe([Palavra("sexta", 1.0, 1.5)], x, ["sexo"]) == []
