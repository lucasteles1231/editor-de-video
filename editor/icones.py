"""
Os ícones: o desenho pequeno da coisa que a fala nomeia, num balão.

Os desenhos são do Tabler Icons (MIT), guardados como caminhos SVG em
``recursos/icones.json``. Eles passam pelo traço tremido do :mod:`editor.rough_draw`,
então saem desenhados à mão, e não colados por cima do vídeo.
"""
from __future__ import annotations

import functools
import json
import re
import unicodedata
from importlib.resources import files

from PIL import Image, ImageDraw

from editor import rough_draw

_ARGS = {"m": 2, "l": 2, "h": 1, "v": 1, "c": 6, "s": 4, "q": 4, "t": 2, "a": 7, "z": 0}
_TOKEN = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")

#: Abaixo disto (na caixa de 24 do Tabler) um caminho é um **ponto**: o Tabler
#: desenha o olho do porquinho como ``M15 11v.01`` e conta com a ponta redonda.
PONTO = 0.5
#: O balão: amarelo-claro, o mesmo amarelo das palavras que saltam, lavado.
BALAO = (255, 236, 150)


@functools.lru_cache(maxsize=1)
def _dados() -> dict:
    return json.loads((files("editor") / "recursos" / "icones.json").read_text("utf-8"))


def nomes() -> list[str]:
    return sorted(_dados()["icones"])


def normalizar(texto: str) -> str:
    plano = unicodedata.normalize("NFKD", texto or "")
    plano = "".join(c for c in plano if not unicodedata.combining(c))
    return re.sub(r"[\s\-]+", "_", plano.strip().lower())


def caminhos(nome: str) -> list[str]:
    return list(_dados()["icones"].get(normalizar(nome), {}).get("caminhos", []))


def transformar(d: str, k: float, tx: float, ty: float
                ) -> tuple[str, list[tuple[float, float]]]:
    """O caminho escalado por ``k`` e deslocado, e os pontos por onde ele passa."""
    toks = _TOKEN.findall(d)
    partes: list[str] = []
    pontos: list[tuple[float, float]] = []
    x = y = x0 = y0 = 0.0
    cmd, i = "", 0
    while i < len(toks):
        t = toks[i]
        if t.isalpha():
            cmd, i = t, i + 1
            if cmd in "Zz":
                partes.append("Z")
                x, y = x0, y0
            continue
        if not cmd or cmd in "Zz":
            raise ValueError(f"número sem comando em {d[:40]!r}")
        n = _ARGS[cmd.lower()]
        if i + n > len(toks) or any(a.isalpha() for a in toks[i:i + n]):
            raise ValueError(f"'{cmd}' com argumentos a menos em {d[:40]!r}")
        a = [float(v) for v in toks[i:i + n]]
        i += n
        rel, c = cmd.islower(), cmd.lower()
        bx, by = (x, y) if rel else (0.0, 0.0)
        if c == "h":
            x = bx + a[0] if rel else a[0]
            partes.append(f"{cmd}{a[0] * k + (0 if rel else tx):.2f}")
        elif c == "v":
            y = by + a[0] if rel else a[0]
            partes.append(f"{cmd}{a[0] * k + (0 if rel else ty):.2f}")
        elif c == "a":
            rx, ry, rot, fa, fs, ex, ey = a
            x, y = bx + ex, by + ey
            partes.append(f"{cmd}{rx * k:.2f} {ry * k:.2f} {rot:g} {int(fa)} {int(fs)} "
                          f"{ex * k + (0 if rel else tx):.2f} {ey * k + (0 if rel else ty):.2f}")
        else:
            vals = []
            for j in range(0, n, 2):
                vals += [a[j] * k + (0 if rel else tx), a[j + 1] * k + (0 if rel else ty)]
            x, y = bx + a[n - 2], by + a[n - 1]
            partes.append(cmd + " ".join(f"{v:.2f}" for v in vals))
        if c == "m":
            x0, y0 = x, y
            cmd = "l" if rel else "L"          # pares a mais depois de um M são L
        pontos.append((x * k + tx, y * k + ty))
    return " ".join(partes), pontos


def desenhar(d: ImageDraw.ImageDraw, nome: str, cx: float, cy: float, *, lado: float,
             semente: int = 1, largura: float = 6.0, cor=rough_draw.TINTA) -> bool:
    """O ícone com o centro em ``(cx, cy)`` e ``lado`` px. ``False`` se ele não existe."""
    lista = caminhos(nome)
    if not lista:
        return False
    k = lado / 24.0
    for j, c in enumerate(lista):
        novo, pts = transformar(c, k, cx - lado / 2, cy - lado / 2)
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        if pts and max(max(xs) - min(xs), max(ys) - min(ys)) < PONTO * k:
            r = largura * 0.65
            d.ellipse([pts[0][0] - r, pts[0][1] - r, pts[0][0] + r, pts[0][1] + r], fill=cor)
            continue
        rough_draw.caminho(d, novo, semente=semente * 31 + j, largura=largura, cor=cor)
    return True


@functools.lru_cache(maxsize=32)
def balao(nome: str, raio: int, semente: int = 1) -> Image.Image:
    """O ícone no balão, numa imagem RGBA quadrada — desenhado uma vez e guardado."""
    lado = 2 * raio + 24
    im = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c = lado / 2
    d.ellipse([c - raio, c - raio, c + raio, c + raio], fill=(*BALAO, 255))
    traco = max(3.0, raio * 0.047)
    rough_draw.elipse(d, c, c, 2 * raio, 2 * raio, semente=semente, largura=traco)
    desenhar(d, nome, c, c, lado=raio * 1.23, semente=semente,
             largura=max(3.0, raio * 0.068))
    return im


#: O tempo de vida do balão: entra pulando (passa de 115%), fica, sai encolhendo.
ENTRA_S = 0.17
SAI_S = 0.33


def escala(t: float, dura: float) -> float:
    """O tamanho do balão ``t`` segundos depois de aparecer; 0 quando já foi."""
    if t < 0 or t >= dura:
        return 0.0
    if t < ENTRA_S:
        return 0.6 + 0.55 * (t / ENTRA_S) if t < ENTRA_S * 0.7 else 1.15 - 0.15 * (
            (t - ENTRA_S * 0.7) / (ENTRA_S * 0.3))
    if t > dura - SAI_S:
        return max(0.0, (dura - t) / SAI_S)
    return 1.0


__all__ = ["BALAO", "balao", "caminhos", "desenhar", "escala", "nomes", "normalizar",
           "transformar"]
