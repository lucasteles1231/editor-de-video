"""
Traço desenhado à mão, com o `rough` (porte para Python do Rough.js), direto no Pillow.

O `rough` só exporta SVG, mas expõe antes a lista de operações; as curvas viram
sequências de pontos e o Pillow as desenha. Nenhum rasterizador de SVG é preciso.
"""
from __future__ import annotations

import rough
from PIL import ImageDraw
from rough.core import Options

TINTA = (25, 25, 25)

#: Tremido de quem desenha à mão: o traço é curvado e desenhado duas vezes.
_ESTILO = {"roughness": 2.4, "bowing": 1.8, "stroke_width": 3.2}


def _linhas(ops, passos: int = 14) -> list[list[tuple[float, float]]]:
    """Lista de operações do `rough` → polilinhas que o Pillow sabe desenhar."""
    linhas: list[list[tuple[float, float]]] = []
    atual: list[tuple[float, float]] = []
    ponto = (0.0, 0.0)
    for op in ops:
        d = op.data
        if op.op == "move":
            if len(atual) > 1:
                linhas.append(atual)
            ponto = (d[0], d[1])
            atual = [ponto]
        elif op.op == "bcurveTo":
            p0, p1, p2, p3 = ponto, (d[0], d[1]), (d[2], d[3]), (d[4], d[5])
            for i in range(1, passos + 1):
                t = i / passos
                u = 1 - t
                atual.append((u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0]
                              + t**3 * p3[0],
                              u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1]
                              + t**3 * p3[1]))
            ponto = p3
        elif op.op == "lineTo":
            ponto = (d[0], d[1])
            atual.append(ponto)
    if len(atual) > 1:
        linhas.append(atual)
    return linhas


def _tracar(d: ImageDraw.ImageDraw, desenho, largura: float, cor) -> None:
    for conjunto in desenho.sets:
        for linha in _linhas(conjunto.ops):
            d.line(linha, fill=cor, width=max(1, round(largura)), joint="curve")


def _opcoes(semente: int, largura: float, roughness: float | None = None,
            bowing: float | None = None) -> Options:
    o = Options()
    o.roughness = _ESTILO["roughness"] if roughness is None else roughness
    o.bowing = _ESTILO["bowing"] if bowing is None else bowing
    o.stroke_width = largura
    o.seed = semente
    return o


def elipse(d: ImageDraw.ImageDraw, cx: float, cy: float, w: float, h: float, *,
           semente: int = 1, largura: float = 4.5, cor=TINTA) -> None:
    _tracar(d, rough.RoughGenerator().ellipse(cx, cy, w, h, _opcoes(semente, largura)),
            largura, cor)


def caminho(d: ImageDraw.ImageDraw, svg: str, *, semente: int = 1, largura: float = 6.0,
            cor=TINTA) -> None:
    """Um caminho SVG já na escala do quadro, com um tremido mais calmo: num ícone de
    200 px o tremido de uma parede desmancha o desenho."""
    _tracar(d, rough.RoughGenerator().path(svg, _opcoes(semente, largura, 1.0, 0.6)),
            largura, cor)


__all__ = ["TINTA", "caminho", "elipse"]
