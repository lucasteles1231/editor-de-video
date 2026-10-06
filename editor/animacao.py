"""
As curvas de animação do vídeo de referência, um vídeo de notícia feito à mão no
Remotion, portadas com os mesmos números (a linha do tempo e a direção dele).

Lá elas eram contadas em quadros de 30 fps; aqui, em segundos (``QUADRO`` = 1/30), para
valer em qualquer fps de saída. O ``interpolate`` do Remotion aplica a curva em cada
trecho, e o ``"perceptual-scale"`` interpola a escala em logaritmo: de 0,4 a 1,08 a
metade do caminho é 0,66, e não 0,74, que é o que o olho sente como meio.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Sequence

#: Um quadro do Remotion: as durações do chat foram medidas em quadros de 30 fps.
QUADRO = 1 / 30
#: Uma mudança de plano de câmera: 11 quadros.
TRANSICAO = 11 * QUADRO


def bezier(x1: float, y1: float, x2: float, y2: float) -> Callable[[float], float]:
    """A curva cúbica de Bézier do CSS e do Remotion (``Easing.bezier``)."""

    def coord(t: float, a: float, b: float) -> float:
        return 3 * a * t * (1 - t) ** 2 + 3 * b * t * t * (1 - t) + t ** 3

    def derivada(t: float, a: float, b: float) -> float:
        return 3 * a * (1 - t) ** 2 + 6 * (b - a) * t * (1 - t) + 3 * (1 - b) * t * t

    def curva(x: float) -> float:
        if x <= 0:
            return 0.0
        if x >= 1:
            return 1.0
        t = x
        for _ in range(8):                       # Newton
            d = derivada(t, x1, x2)
            if abs(d) < 1e-6:
                break
            t -= (coord(t, x1, x2) - x) / d
        if not 0 <= t <= 1 or abs(coord(t, x1, x2) - x) > 1e-5:
            lo, hi = 0.0, 1.0                     # bisseção, se o Newton escapar
            for _ in range(40):
                t = (lo + hi) / 2
                if coord(t, x1, x2) < x:
                    lo = t
                else:
                    hi = t
        return coord(t, y1, y2)

    return curva


#: O pop, a entrada pela esquerda e o "print": chega rápido e assenta.
SAIDA = bezier(0.16, 1, 0.3, 1)
#: O pouso do carimbo.
POUSO = bezier(0.33, 1, 0.68, 1)
#: A câmera e a janela (``direcao.ts``).
CAMERA = bezier(0.65, 0, 0.35, 1)


def interpolar(x: float, xs: Sequence[float], ys: Sequence[float],
               curva: Callable[[float], float] | None = None, *, escala: bool = False
               ) -> float:
    """O ``interpolate`` do Remotion, com os dois lados presos. Com ``escala``, o caminho
    é em logaritmo (``output: "perceptual-scale"``)."""
    if x <= xs[0]:
        return float(ys[0])
    if x >= xs[-1]:
        return float(ys[-1])
    for k in range(len(xs) - 1):
        if xs[k] <= x <= xs[k + 1]:
            p = (x - xs[k]) / max(1e-9, xs[k + 1] - xs[k])
            if curva is not None:
                p = curva(p)
            a, b = ys[k], ys[k + 1]
            if escala:
                return math.exp(math.log(a) + (math.log(b) - math.log(a)) * p)
            return a + (b - a) * p
    return float(ys[-1])


def pop(t: float, em: float) -> float:
    """A escala de quem entra: 0,4 → 1,08 → 1 em 10 quadros."""
    return interpolar(t, [em, em + 5 * QUADRO, em + 10 * QUADRO], [0.4, 1.08, 1.0], SAIDA,
                      escala=True)


def carimbo(t: float, em: float) -> float:
    """A escala do carimbo, que cai de grande: 2,4 → 0,94 → 1 em 8 quadros."""
    return interpolar(t, [em, em + 4 * QUADRO, em + 8 * QUADRO], [2.4, 0.94, 1.0], POUSO,
                      escala=True)


def aparece(t: float, em: float, quadros: float = 4) -> float:
    """A opacidade de quem entra."""
    return interpolar(t, [em, em + quadros * QUADRO], [0.0, 1.0])


def some_no_fim(t: float, fim: float, quadros: float = 5) -> float:
    """A opacidade nos últimos quadros: nada sai de corte seco."""
    return interpolar(t, [fim - quadros * QUADRO, fim - QUADRO], [1.0, 0.0])


def da_esquerda(t: float, em: float) -> float:
    """O deslocamento de quem entra pela esquerda, em frações da própria largura: −1,1
    → 0 em 9 quadros."""
    return interpolar(t, [em, em + 9 * QUADRO], [-1.1, 0.0], SAIDA)


def tremida(t: float, em: float, quadros: float = 8, forca: float = 14.0
            ) -> tuple[float, float]:
    """A tremida de um impacto, em pixels (num quadro de 1080 de largura), que some aos
    poucos."""
    k = (t - em) / QUADRO
    if k < 0 or k >= quadros:
        return 0.0, 0.0
    queda = 1 - k / quadros
    return math.sin(k * 2.7) * forca * queda, math.cos(k * 3.1) * forca * 0.6 * queda


def flash(t: float, em: float) -> float:
    """A opacidade do flash branco de uma foto: acende em 1 quadro e apaga em 11."""
    return interpolar(t, [em, em + QUADRO, em + 12 * QUADRO], [0.0, 1.0, 0.0])


__all__ = ["CAMERA", "POUSO", "QUADRO", "SAIDA", "TRANSICAO", "aparece", "bezier", "carimbo",
           "da_esquerda", "flash", "interpolar", "pop", "some_no_fim", "tremida"]
