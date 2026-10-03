"""
Os efeitos sonoros, sintetizados em código — nenhum arquivo baixado, nenhuma licença
para rastrear.

Um whoosh é ruído filtrado com envelope; um pop é um seno curto que cai de tom. Cada
um é ligeiramente diferente (pela semente) e reprodutível: o mesmo vídeo soa sempre
igual.
"""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np

#: A voz manda: os efeitos entram a 35% por baixo dela.
GANHO = 0.35
#: Nenhum efeito passa de meio segundo — mais que isso já é trilha, não pontuação.
TETO_S = 0.5


def _envelope(n: int, ataque: float, queda: float) -> np.ndarray:
    """Sobe e desce nas bordas, para o som não estalar."""
    env = np.ones(n, dtype=np.float32)
    subida, descida = max(1, int(n * ataque)), max(1, int(n * queda))
    env[:subida] = np.linspace(0.0, 1.0, subida, endpoint=False)
    env[n - descida:] = np.linspace(1.0, 0.0, descida)
    return env


def _ruido(n: int, semente: int) -> np.ndarray:
    return np.random.default_rng(semente).uniform(-1.0, 1.0, n).astype(np.float32)


def whoosh(taxa: int, semente: int = 1, dur: float = 0.34) -> np.ndarray:
    """A transição: ruído num passa-baixa que vai abrindo — algo passando, não chiado."""
    n = int(min(dur, TETO_S) * taxa)
    r = _ruido(n, semente)
    corte = 0.02 + 0.33 * np.arange(n) / max(1, n - 1)
    saida = np.empty(n, dtype=np.float32)
    anterior = 0.0
    for i in range(n):
        anterior += corte[i] * (r[i] - anterior)
        saida[i] = anterior
    return saida * _envelope(n, 0.30, 0.55) * 2.2


def pop(taxa: int, semente: int = 1, dur: float = 0.12) -> np.ndarray:
    """A aparição: um seno curto que cai de tom depressa."""
    n = int(min(dur, TETO_S) * taxa)
    base = 620 + (semente % 5) * 40
    f = base * (1.0 - 0.45 * np.arange(n) / max(1, n - 1))
    fase = np.cumsum(2 * np.pi * f / taxa)
    return (np.sin(fase) * _envelope(n, 0.02, 0.85)).astype(np.float32)


VOZES = {"whoosh": whoosh, "pop": pop}


def trilha(sons: Sequence, duracao: float, taxa: int) -> np.ndarray:
    """Uma trilha mono com todos os efeitos nos seus instantes (``som.nome``, ``som.t``)."""
    n = max(1, round(duracao * taxa))
    saida = np.zeros(n, dtype=np.float32)
    for k, som in enumerate(sons):
        fabrica = VOZES.get(som.nome)
        if fabrica is None:
            continue
        amostras = fabrica(taxa, semente=k + 1)
        i0 = round(som.t * taxa)
        if i0 >= n:
            continue
        pedaco = amostras[: n - i0]
        saida[i0:i0 + len(pedaco)] += pedaco
    return saida * GANHO


def misturar(voz: np.ndarray, efeitos: np.ndarray) -> np.ndarray:
    """A voz (amostras × canais) com os efeitos por baixo, sem passar de ±1."""
    n = voz.shape[0]
    e = np.zeros(n, dtype=np.float32)
    e[: min(n, len(efeitos))] = efeitos[:n]
    saida = voz + e[:, None]
    pico = float(np.max(np.abs(saida))) if saida.size else 0.0
    return saida / pico * 0.98 if pico > 1.0 else saida


__all__ = ["GANHO", "VOZES", "misturar", "pop", "trilha", "whoosh"]
