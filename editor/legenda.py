"""
O desenho da legenda: uma linha por vez, palavra por palavra, no estilo dos Shorts.

- **Karaokê:** a palavra ainda não dita fica cinza, a dita fica branca, e a
  palavra-chave do bloco acende amarela no instante em que é dita.
- **Pulo:** o bloco entra a 78% do tamanho e chega a 100% em 120 ms.
- **Adesivo:** a palavra escolhida some da linha, as vizinhas se afastam para abrir
  espaço, e ela cresce num balão (ou numa estrela), inclinada — uma legenda só, com
  uma palavra que salta. Afastar as vizinhas é o que impede a forma de cobrir a
  primeira letra delas.

Tudo é medido pela fonte de verdade (DejaVu Sans Bold, embutida no pacote), então a
linha sai igual no Windows, no macOS e no Linux.
"""
from __future__ import annotations

import functools
import io
import math
import random
from importlib.resources import files

from PIL import Image, ImageDraw, ImageFont

from editor.plano import Adesivo, Bloco, Plano

CINZA = (150, 150, 150)
BRANCO = (255, 255, 255)
AMARELO = (255, 215, 0)
PRETO = (0, 0, 0)

#: O corpo da letra, em fração do lado curto do quadro.
CORPO_VERTICAL = 0.060
CORPO_HORIZONTAL = 0.050
#: A distância da linha até a borda de baixo, em fração da altura. No vertical ela
#: fica acima da interface do Shorts, do Reels e do TikTok.
MARGEM_VERTICAL = 0.156
MARGEM_HORIZONTAL = 0.07
#: O contorno preto, em fração do corpo.
CONTORNO = 0.09

POP_DE = 0.78
POP_S = 0.12

#: O adesivo: cresce até 160%, assenta em 135%; a forma passa da palavra nesta
#: proporção do corpo; as vizinhas abrem em 150 ms e ficam a esta folga da forma.
ADESIVO_CRESCE = 1.60
ADESIVO_FICA = 1.35
FORMA_SOBRA_X = 0.9
FORMA_SOBRA_Y = 0.55
VIZINHA_FOLGA = 0.18
ESTRELA_ALARGA = 1.12
ABRE_S = 0.15
#: (forma, texto, contorno do texto): amarelo, rosa, ciano e lima.
CORES_DO_ADESIVO = (
    ((255, 212, 0), PRETO, None),
    ((255, 61, 127), BRANCO, PRETO),
    ((0, 194, 255), PRETO, None),
    ((155, 225, 93), PRETO, None),
)
GIROS = (-4, 3, -3, 4)


@functools.lru_cache(maxsize=1)
def _bytes_da_fonte() -> bytes:
    return (files("editor") / "recursos" / "DejaVuSans-Bold.ttf").read_bytes()


@functools.lru_cache(maxsize=64)
def fonte(px: int) -> ImageFont.FreeTypeFont:
    """A DejaVu Sans Bold no tamanho pedido, lida da memória (funciona instalada de
    qualquer jeito, inclusive de dentro de um zip)."""
    return ImageFont.truetype(io.BytesIO(_bytes_da_fonte()), max(8, px))


def _suave(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return 1 - (1 - x) ** 3


def eh_estrela(estilo: int) -> bool:
    return estilo % 4 == 1


def forma(largura: float, altura: float, estilo: int) -> list[tuple[float, float]]:
    """O contorno atrás da palavra, centrado em (0, 0): balão tremido ou estrela."""
    rnd = random.Random(estilo + 7)
    pontos = []
    if eh_estrela(estilo):
        n = 26
        for i in range(n):
            a = 2 * math.pi * i / n
            r = 1.0 if i % 2 == 0 else 0.82 + rnd.uniform(-0.03, 0.03)
            pontos.append((math.cos(a) * largura / 2 * r * ESTRELA_ALARGA,
                           math.sin(a) * altura / 2 * r * 1.35))
    else:
        n = 44
        for i in range(n):
            a = 2 * math.pi * i / n
            c, s = math.cos(a), math.sin(a)
            tremido = 1 + rnd.uniform(-0.025, 0.025)
            pontos.append((abs(c) ** 0.35 * math.copysign(1, c) * largura / 2 * tremido,
                           abs(s) ** 0.35 * math.copysign(1, s) * altura / 2 * tremido))
    return pontos


class Legenda:
    """Desenha a legenda de um plano num quadro de ``largura`` × ``altura``."""

    def __init__(self, largura: int, altura: int, *, vertical: bool, tamanho: float = 1.0):
        self.largura, self.altura = largura, altura
        curto = min(largura, altura)
        self.em = max(12, round(curto * (CORPO_VERTICAL if vertical else CORPO_HORIZONTAL)
                                * tamanho))
        margem = MARGEM_VERTICAL if vertical else MARGEM_HORIZONTAL
        sobe, desce = fonte(self.em).getmetrics()
        #: A linha de base: o pé da linha (descendente incluída) fica na margem.
        self.base = altura - altura * margem - desce
        self.meio = self.base - (sobe - desce) / 2
        self.lateral = curto * 0.04

    # ── layout ───────────────────────────────────────────────────────────

    def _larguras(self, bloco: Bloco, px: int) -> tuple[list[float], float]:
        f = fonte(px)
        return [f.getlength(p.texto) for p in bloco.palavras], f.getlength(" ")

    def abertura(self, bloco: Bloco, indice: int, estilo: int) -> float:
        """Quanto o vão da palavra que salta precisa crescer para a forma caber entre
        as vizinhas — limitado pelo que ainda cabe na largura do quadro."""
        larguras, espaco = self._larguras(bloco, self.em)
        if len(larguras) == 1:
            return 0.0
        nucleo = fonte(self.em).getlength(bloco.palavras[indice].texto.rstrip(".,!?;:…"))
        largura_forma = nucleo * ADESIVO_FICA + self.em * FORMA_SOBRA_X
        if eh_estrela(estilo):
            largura_forma *= ESTRELA_ALARGA
        precisa = largura_forma + 2 * (self.em * VIZINHA_FOLGA - espaco)
        total = sum(larguras) + espaco * (len(larguras) - 1)
        sobra = self.largura - 2 * self.lateral - total
        return max(0.0, min(precisa - larguras[indice], sobra))

    # ── desenho ──────────────────────────────────────────────────────────

    def desenhar(self, img: Image.Image, plano: Plano, t: float) -> None:
        for i, bloco in enumerate(plano.blocos):
            if bloco.inicio <= t < bloco.fim:
                adesivo = next((a for a in plano.adesivos if a.bloco == i), None)
                self._bloco(img, bloco, t, adesivo)
                return

    def _bloco(self, img: Image.Image, bloco: Bloco, t: float, adesivo: Adesivo | None) -> None:
        idade = t - bloco.inicio
        px = self.em
        if idade < POP_S:
            px = max(8, round(self.em * (POP_DE + (1 - POP_DE) * _suave(idade / POP_S))))
        larguras, espaco = self._larguras(bloco, px)
        salta = adesivo is not None and t >= adesivo.inicio
        vao = 0.0
        if salta:
            vao = self.abertura(bloco, adesivo.palavra, adesivo.estilo) * (px / self.em)
            vao *= _suave((t - adesivo.inicio) / ABRE_S)
        total = sum(larguras) + espaco * (len(larguras) - 1) + vao
        x = (self.largura - total) / 2
        d = ImageDraw.Draw(img)
        f = fonte(px)
        contorno = max(2, round(px * CONTORNO))
        centro_do_adesivo = None
        for i, (p, w) in enumerate(zip(bloco.palavras, larguras, strict=True)):
            if salta and i == adesivo.palavra:
                centro_do_adesivo = x + (w + vao) / 2
                x += w + vao + espaco
                continue
            dita = t >= p.inicio
            cor = (AMARELO if i == bloco.chave else BRANCO) if dita else CINZA
            d.text((x, self.base), p.texto, font=f, fill=cor, anchor="ls",
                   stroke_width=contorno, stroke_fill=PRETO)
            x += w + espaco
        if centro_do_adesivo is not None:
            self._adesivo(img, bloco.palavras[adesivo.palavra].texto, adesivo,
                          centro_do_adesivo, t - adesivo.inicio, bloco.fim - t)

    def _adesivo(self, img: Image.Image, texto: str, adesivo: Adesivo, cx: float,
                 idade: float, falta: float) -> None:
        nucleo = texto.rstrip(".,!?;:…")
        # A palavra: cresce a 160% em 120 ms e assenta em 135%.
        if idade < 0.12:
            escala = 1.0 + (ADESIVO_CRESCE - 1.0) * _suave(idade / 0.12)
        elif idade < 0.21:
            escala = ADESIVO_CRESCE + (ADESIVO_FICA - ADESIVO_CRESCE) * _suave(
                (idade - 0.12) / 0.09)
        else:
            escala = ADESIVO_FICA
        # A forma: nasce do zero, passa de 112% e volta a 100%.
        if idade < 0.15:
            cresce = 1.12 * _suave(idade / 0.15)
        elif idade < 0.22:
            cresce = 1.12 - 0.12 * _suave((idade - 0.15) / 0.07)
        else:
            cresce = 1.0
        if falta < 0.09:                                  # sai junto com a linha
            cresce *= max(0.0, falta / 0.09)
        if cresce <= 0.01:
            return
        cor_forma, cor_texto, cor_contorno = CORES_DO_ADESIVO[adesivo.estilo % 4]
        f = fonte(max(8, round(self.em * escala)))
        largura_texto = f.getlength(nucleo)
        largura = (fonte(self.em).getlength(nucleo) * ADESIVO_FICA + self.em * FORMA_SOBRA_X)
        altura = self.em * ADESIVO_FICA + self.em * FORMA_SOBRA_Y
        lado = int(max(largura * 1.4, altura * 2.2) + 40)
        camada = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
        dc = ImageDraw.Draw(camada)
        meio = lado / 2
        pontos = [(meio + px * cresce, meio + py * cresce)
                  for px, py in forma(largura, altura, adesivo.estilo)]
        sombra = [(px + self.em * 0.15, py + self.em * 0.17) for px, py in pontos]
        dc.polygon(sombra, fill=(0, 0, 0, 112))
        traco = max(2, round(self.em * 0.09))
        dc.polygon(pontos, fill=(*cor_forma, 255), outline=(0, 0, 0, 255), width=traco)
        if cresce > 0.5:
            dc.text((meio - largura_texto / 2, meio), nucleo, font=f, fill=cor_texto,
                    anchor="lm", stroke_width=traco if cor_contorno else 0,
                    stroke_fill=cor_contorno or cor_texto)
        camada = camada.rotate(GIROS[adesivo.estilo % 4], resample=Image.BICUBIC)
        destino = (round(cx - meio), round(self.meio - meio))
        img.paste(camada, destino, camada)


__all__ = ["AMARELO", "BRANCO", "CINZA", "Legenda", "eh_estrela", "fonte", "forma"]
