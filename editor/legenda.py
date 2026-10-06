"""
O desenho da legenda: uma linha por vez, palavra por palavra, no estilo dos Shorts.

- **Karaokê:** a palavra ainda não dita fica cinza, a dita fica branca, e a
  palavra-chave do bloco acende amarela no instante em que é dita.
- **Pulo:** o bloco entra a 78% do tamanho e chega a 100% em 120 ms.
- **Adesivo:** a palavra escolhida some da linha, as vizinhas se afastam para abrir
  espaço, e ela cresce num balão (ou numa estrela), inclinada — uma legenda só, com
  uma palavra que salta. Afastar as vizinhas é o que impede a forma de cobrir a
  primeira letra delas.
- **Destaques** (o outro estilo, o da legenda do vídeo de referência): páginas
  de até 4 palavras em até duas linhas, na Inter Black com contorno escuro. Cada palavra
  entra 80 ms antes de ser dita, com um pulo; a dita sobe 7 px e acende (âmbar, ou a cor
  do destaque com um brilho). A frase de efeito vem sozinha numa pílula amarela.

Tudo é medido pela fonte de verdade (DejaVu Sans Bold, embutida no pacote), então a
linha sai igual no Windows, no macOS e no Linux.
"""
from __future__ import annotations

import functools
import io
import math
import random
from importlib.resources import files

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from editor import animacao as a
from editor.cartoes import colar
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

#: A legenda "destaques", em pixels de um quadro de 1080 (``FullPage.tsx``): as cores de
#: cada destaque parado e dito, o contorno, a largura e o corpo.
TINTA = (16, 2, 31)
PARADA = {"": (255, 255, 255, 235), "rosa": (255, 77, 157, 255), "ciano": (45, 226, 230, 255)}
DITA = {"": (255, 209, 102, 255), "rosa": (255, 77, 157, 255), "ciano": (45, 226, 230, 255)}
PILULA = (255, 209, 102)
TEXTO_DA_PILULA = (18, 0, 31)
LARGURA_DA_PAGINA = 940
LARGURA_DA_PAGINA_DEITADA = 1240
CORPO_DA_LINHA = (56, 92)
CORPO_DA_PILULA = (56, 96)
#: Quanto a palavra dita sobe; a entrada (opacidade em 80 ms, pulo em 260 ms) e o
#: tempo da saída (os últimos quadros da página).
SOBE_DITA = 7
ENTRA_S = 0.08


@functools.lru_cache(maxsize=1)
def _bytes_da_fonte() -> bytes:
    return (files("editor") / "recursos" / "DejaVuSans-Bold.ttf").read_bytes()


@functools.lru_cache(maxsize=64)
def fonte(px: int) -> ImageFont.FreeTypeFont:
    """A DejaVu Sans Bold no tamanho pedido, lida da memória (funciona instalada de
    qualquer jeito, inclusive de dentro de um zip)."""
    return ImageFont.truetype(io.BytesIO(_bytes_da_fonte()), max(8, px))


@functools.lru_cache(maxsize=1)
def _bytes_da_inter() -> bytes:
    return (files("editor") / "recursos" / "Inter-Black.ttf").read_bytes()


@functools.lru_cache(maxsize=64)
def inter(px: int) -> ImageFont.FreeTypeFont:
    """A Inter Black, a fonte da legenda em destaques."""
    return ImageFont.truetype(io.BytesIO(_bytes_da_inter()), max(8, px))


@functools.lru_cache(maxsize=512)
def palavra_com_contorno(texto: str, px: int, cor: tuple, brilho: bool) -> Image.Image:
    """A palavra com o contorno escuro e a sombra embaixo (``text-shadow`` do chat), e o
    brilho da cor quando ``brilho``. ``info["origem"]`` é onde fica o pé da primeira
    letra (a linha de base, à esquerda)."""
    f = inter(px)
    k = px / 92
    contorno = max(2, round(6.5 * k))
    sombra_y, sombra_raio = 12 * k, 13 * k
    brilho_raio = 17 * k
    margem = round(max(sombra_raio * 2 + sombra_y, brilho_raio * 2.5 if brilho else 0)) + 2
    x0, y0, x1, y1 = f.getbbox(texto, anchor="ls", stroke_width=contorno)
    largura, altura = round(x1 - x0) + 2 * margem, round(y1 - y0) + 2 * margem
    origem = (margem - x0, margem - y0)
    img = Image.new("RGBA", (largura, altura), (0, 0, 0, 0))
    sombra = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sombra).text((origem[0], origem[1] + sombra_y), texto, font=f,
                                fill=(0, 0, 0, 178), anchor="ls", stroke_width=contorno,
                                stroke_fill=(0, 0, 0, 178))
    img.alpha_composite(sombra.filter(ImageFilter.GaussianBlur(sombra_raio)))
    if brilho:
        halo = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(halo).text(origem, texto, font=f, fill=cor, anchor="ls",
                                  stroke_width=contorno, stroke_fill=cor)
        img.alpha_composite(halo.filter(ImageFilter.GaussianBlur(brilho_raio)))
    ImageDraw.Draw(img).text(origem, texto, font=f, fill=cor, anchor="ls",
                             stroke_width=contorno, stroke_fill=(*TINTA, 255))
    img.info["origem"] = origem
    return img


@functools.lru_cache(maxsize=64)
def pilula(texto: str, px: int) -> Image.Image:
    """A placa da frase de efeito: amarela, cantos de 26, com o brilho amarelo em volta
    (``0 0 70px``) e o texto escuro em maiúsculas."""
    f = inter(px)
    k = px / 96
    x0, _y0, x1, _y1 = f.getbbox(texto, anchor="ls")
    sobe, desce = f.getmetrics()
    largura = round(x1 - x0 + 2 * 38 * k)
    altura = round(sobe + desce * 0.6 + 2 * 18 * k)
    margem = round(70 * k)
    img = Image.new("RGBA", (largura + 2 * margem, altura + 2 * margem), (0, 0, 0, 0))
    halo = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(halo).rounded_rectangle([margem, margem, margem + largura, margem + altura],
                                           round(26 * k), fill=(*PILULA, 115))
    img.alpha_composite(halo.filter(ImageFilter.GaussianBlur(35 * k)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([margem, margem, margem + largura, margem + altura], round(26 * k),
                        fill=(*PILULA, 255))
    d.text((margem + largura / 2 - (x0 + x1) / 2, margem + altura / 2 + (sobe - desce) / 2
            - desce * 0.2), texto, font=f, fill=(*TEXTO_DA_PILULA, 255), anchor="ls")
    return img


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
        self.tamanho = tamanho
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

    def desenhar(self, img: Image.Image, plano: Plano, t: float, base: float | None = None
                 ) -> None:
        """A linha do momento. ``base`` muda a altura dela (na janela, a legenda fica na
        faixa abaixo da janela e acompanha quando ela cresce)."""
        for i, bloco in enumerate(plano.blocos):
            if bloco.inicio <= t < bloco.fim:
                if bloco.tipo != "classica":
                    self._pagina(img, bloco, t, base)
                    return
                adesivo = next((a for a in plano.adesivos if a.bloco == i), None)
                if base is None:
                    self._bloco(img, bloco, t, adesivo)
                    return
                antes = self.base, self.meio
                self.base, self.meio = base, base - (antes[0] - antes[1])
                try:
                    self._bloco(img, bloco, t, adesivo)
                finally:
                    self.base, self.meio = antes
                return

    # ── os destaques ─────────────────────────────────────────────────────

    def _escala_dos_destaques(self) -> float:
        return min(self.largura, self.altura) / 1080 * self.tamanho

    def corpo_da_pagina(self, bloco: Bloco) -> int:
        """O corpo da página (``sizeFor`` do chat): a pílula numa linha, a página comum em
        até duas; quanto mais letras, menor, entre os limites."""
        k = self._escala_dos_destaques()
        pilula_ = bloco.tipo == "pilula"
        texto = bloco.texto.upper() if pilula_ else bloco.texto
        util = self._largura_da_pagina()
        disponivel = util - 76 * k if pilula_ else 2 * util
        menor, maior = CORPO_DA_PILULA if pilula_ else CORPO_DA_LINHA
        cabe = math.floor(disponivel / (max(1, len(texto)) * (0.68 if pilula_ else 0.55)))
        px = max(round(menor * k), min(round(maior * k), cabe))
        if pilula_:                      # e a pílula nunca passa da largura
            while px > 12 and inter(px).getlength(texto) > disponivel:
                px -= 2
        else:                            # nem a página de duas linhas
            while px > round(menor * k) and len(self.linhas_da_pagina(bloco, px)) > 2:
                px -= 2
        return px

    def _largura_da_pagina(self) -> float:
        k = self._escala_dos_destaques()
        maximo = LARGURA_DA_PAGINA if self.largura <= self.altura else LARGURA_DA_PAGINA_DEITADA
        return min(self.largura - 2 * 60 * k, maximo * k)

    def linhas_da_pagina(self, bloco: Bloco, px: int) -> list[list[tuple[int, float]]]:
        """As palavras da página em linhas (``flex-wrap``): cada uma com o vão de 0,16 em
        de cada lado, e a linha quebrando quando não cabe mais."""
        f = inter(px)
        util = self._largura_da_pagina()
        linhas: list[list[tuple[int, float]]] = [[]]
        usado = 0.0
        for i, w in enumerate(bloco.palavras):
            caixa = f.getlength(w.texto) + 0.32 * px
            if linhas[-1] and usado + caixa > util:
                linhas.append([])
                usado = 0.0
            linhas[-1].append((i, caixa))
            usado += caixa
        return linhas

    def _pagina(self, img: Image.Image, bloco: Bloco, t: float, base: float | None) -> None:
        k = self._escala_dos_destaques()
        px = self.corpo_da_pagina(bloco)
        quadros = max(1, round((bloco.fim - bloco.inicio) / a.QUADRO))
        sai = max(1, min(4, round(quadros * 0.18)))
        saida = min(1.0, max(0.0, (bloco.fim - t) / (sai * a.QUADRO)))
        sobe, desce = inter(px).getmetrics()
        n = 1 if bloco.tipo == "pilula" else len(self.linhas_da_pagina(bloco, px))
        altura = n * px * 1.05 + (40 * k if bloco.tipo == "pilula" else 0)
        if base is not None:          # na janela: o meio da faixa
            centro = base - (self.base - self.meio)
        else:                         # sem ela: o pé da página na linha de sempre
            centro = self.base + desce - n * px * 1.05 / 2
        # Nunca abaixo do quadro, com a sombra: no quadrado, a faixa embaixo da janela não
        # cabe duas linhas, e a página sobe por cima da borda dela (a segunda linha saía
        # cortada).
        sombra = (12 + 26) * px / 92
        centro = min(centro, self.altura - 4 - sombra - altura / 2)
        if bloco.tipo == "pilula":
            self._pilula(img, bloco, t, px, centro, quadros, saida)
        else:
            self._linhas(img, bloco, t, px, k, centro, saida, sobe, desce)

    def _pilula(self, camada: Image.Image, bloco: Bloco, t: float, px: int, centro: float,
                quadros: int, saida: float) -> None:
        pico = max(2, min(5, round(quadros * 0.22)))
        assenta = max(3, min(11, round(quadros * 0.45)))
        quadro = (t - bloco.inicio) / a.QUADRO
        escala = a.interpolar(quadro, [0, pico, assenta], [0.68, 1.06, 1.0], a.SAIDA,
                              escala=True)
        placa = pilula(bloco.texto.upper(), px)
        colar(camada, placa, self.largura / 2, centro, escala=escala, giro=-1.6,
              opacidade=saida)

    def _linhas(self, camada: Image.Image, bloco: Bloco, t: float, px: int, k: float,
                centro: float, saida: float, sobe: int, desce: int) -> None:
        linhas = self.linhas_da_pagina(bloco, px)
        altura_da_linha = px * 1.05
        topo = centro - len(linhas) * altura_da_linha / 2
        estilos = bloco.estilos or [""] * len(bloco.palavras)
        for n, linha in enumerate(linhas):
            x = (self.largura - sum(c for _, c in linha)) / 2
            pe = topo + n * altura_da_linha + (altura_da_linha - sobe - desce) / 2 + sobe
            for i, caixa in linha:
                w = bloco.palavras[i]
                desde = t - w.inicio + ENTRA_S
                if desde < 0:
                    x += caixa
                    continue
                opacidade = min(1.0, desde / ENTRA_S) * saida
                escala = a.interpolar(desde, [0.0, 0.12, 0.26], [0.55, 1.08, 1.0], a.SAIDA,
                                      escala=True)
                dita = w.inicio <= t < w.fim
                estilo = estilos[i] if estilos[i] in PARADA else ""
                cor = DITA[estilo] if dita else PARADA[estilo]
                sprite = palavra_com_contorno(w.texto, px, cor, dita and estilo != "")
                ox, oy = sprite.info["origem"]
                largura_texto = caixa - 0.32 * px
                # o centro da palavra (o pulo é em volta dele), na linha de base
                cx = x + caixa / 2
                cy = pe - (sobe - desce) / 2 - (SOBE_DITA * k if dita else 0.0)
                dx = sprite.width / 2 - ox - largura_texto / 2
                dy = sprite.height / 2 - oy + (sobe - desce) / 2
                colar(camada, sprite, cx + dx * escala, cy + dy * escala, escala=escala,
                      opacidade=opacidade)
                x += caixa

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
