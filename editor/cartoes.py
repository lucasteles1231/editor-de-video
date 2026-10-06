"""
Os cartões animados: as animações do vídeo de referência, feitas à mão no Remotion,
como modelos que o Gemini preenche com o que é dito, desenhados aqui no Pillow com as
mesmas medidas e as mesmas curvas (:mod:`editor.animacao`).

| Modelo | O que é | No vídeo do chat |
|---|---|---|
| selo | etiqueta inclinada que entra com pop | "SEM CENSURA", "COMENTA AÍ" |
| lista | itens que entram pela esquerda, um por palavra | as revelações |
| quadro | linhas (nome · valor) que entram uma a uma; a falada acende | as classificações |
| enquete | dois botões e o "COMENTA AÍ" | "tá certa ou passou do ponto?" |
| carimbo | um cartão que leva um carimbo vermelho, com tremida | a página 404 "APAGADA" |
| destaque | um número ou data grande que cai com carimbo | o "18", "19 DE NOVEMBRO" |
| flash | o flash de uma foto e um selo | "OS FÃS PRINTARAM" |

As medidas são as do Remotion, num palco de 1080 de largura, e escalam com ele. O
carimbo, o quadro e o destaque ficam **no palco**: andam com a câmera, que empurra até
eles. O selo, a lista, a enquete e o flash ficam **na janela**: parados e legíveis,
qualquer que seja o zoom.

O emoji colorido não existe no Pillow; no lugar dele vai um dos ícones do editor, no
traço de caneta.
"""
from __future__ import annotations

import functools
import io
import re
from dataclasses import dataclass, field
from importlib.resources import files

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from editor import animacao as a
from editor import icones

MODELOS = ("selo", "lista", "quadro", "enquete", "carimbo", "destaque", "flash")
NO_PALCO = frozenset({"carimbo", "quadro", "destaque"})
#: O palco em que as medidas foram feitas (1080 × 608, o 16:9 da janela do chat).
REFERENCIA = 1080

TINTA = (16, 2, 31)
BRANCO = (255, 255, 255)
#: A paleta do canal (``timeline.ts``), pelos nomes de cor do editor.
CORES = {
    "amarelo": (255, 209, 102), "rosa": (255, 77, 157), "ciano": (45, 226, 230),
    "lima": (31, 191, 95), "laranja": (255, 159, 67), "roxo": (138, 63, 252),
    "vermelho": (232, 34, 46),
}
#: As cores em que o texto vai escuro.
CLARAS = frozenset({"amarelo", "ciano"})
#: O centro do carimbo, a partir do centro do cartão (no chat: 695 × 400 no palco).
CARIMBO = (155, 96)
#: A ordem das cores dos itens de uma lista e dos valores de um quadro.
RODIZIO = ("rosa", "laranja", "vermelho", "ciano", "roxo")


@dataclass
class Item:
    texto: str
    em: float
    valor: str = ""
    icone: str = ""


@dataclass
class Cartao:
    modelo: str
    inicio: float
    fim: float
    texto: str = ""
    rotulo: str = ""
    icone: str = ""
    cor: str = "amarelo"
    itens: list[Item] = field(default_factory=list)
    #: O momento forte (o carimbo, o número caindo, o flash, o "comenta").
    forte: float | None = None

    @property
    def no_palco(self) -> bool:
        return self.modelo in NO_PALCO

    def para_json(self) -> dict:
        return {"modelo": self.modelo, "inicio": round(self.inicio, 3),
                "fim": round(self.fim, 3), "texto": self.texto, "rotulo": self.rotulo,
                "icone": self.icone, "cor": self.cor, "forte": self.forte,
                "itens": [{"texto": i.texto, "valor": i.valor, "icone": i.icone,
                           "em": round(i.em, 3)} for i in self.itens]}


# ── as fontes e os pedaços ───────────────────────────────────────────────


@functools.lru_cache(maxsize=2)
def _bytes(nome: str) -> bytes:
    return (files("editor") / "recursos" / nome).read_bytes()


@functools.lru_cache(maxsize=64)
def anton(px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(io.BytesIO(_bytes("Anton-Regular.ttf")), max(8, px))


@functools.lru_cache(maxsize=64)
def negrito(px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(io.BytesIO(_bytes("DejaVuSans-Bold.ttf")), max(8, px))


def _cor(nome: str) -> tuple[int, int, int]:
    return CORES.get(nome, CORES["amarelo"])


def _texto_sobre(nome: str) -> tuple[int, int, int]:
    return TINTA if nome in CLARAS else BRANCO


def _sombra(img: Image.Image, raio: float, deslocamento: float, opacidade: float = 0.5
            ) -> Image.Image:
    """A sombra embaixo de um sprite: a forma dele, escura e borrada."""
    margem = round(raio * 2 + deslocamento)
    base = Image.new("RGBA", (img.width + 2 * margem, img.height + 2 * margem), (0, 0, 0, 0))
    sombra = Image.new("RGBA", img.size, (0, 0, 0, round(255 * opacidade)))
    sombra.putalpha(img.getchannel("A").point(lambda v: round(v * opacidade)))
    base.paste(sombra, (margem, margem + round(deslocamento)), sombra)
    base = base.filter(ImageFilter.GaussianBlur(raio))
    base.alpha_composite(img, (margem, margem))
    base.info["margem"] = margem
    return base


def no_canto(sprite: Image.Image, x: float, y: float) -> tuple[float, float]:
    """O centro em que o sprite fica com o canto de cima à esquerda do conteúdo (sem a
    sombra) em ``(x, y)``."""
    m = sprite.info.get("margem", 0)
    return x + sprite.width / 2 - m, y + sprite.height / 2 - m


def conteudo(sprite: Image.Image) -> tuple[int, int]:
    """A largura e a altura do conteúdo, sem a sombra."""
    m = sprite.info.get("margem", 0)
    return sprite.width - 2 * m, sprite.height - 2 * m


def _pilula(largura: int, altura: int, raio: int, cor, *, borda_esquerda=None, espessura=0,
            borda_de_baixo=None, contorno=None) -> Image.Image:
    img = Image.new("RGBA", (largura, altura), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, largura - 1, altura - 1], raio, fill=cor)
    if borda_de_baixo is not None and espessura:
        d.rounded_rectangle([0, 0, largura - 1, altura - 1], raio, fill=borda_de_baixo)
        d.rounded_rectangle([0, 0, largura - 1, altura - 1 - espessura], raio, fill=cor)
    if borda_esquerda is not None and espessura:
        mascara = Image.new("L", (largura, altura), 0)
        ImageDraw.Draw(mascara).rounded_rectangle([0, 0, largura - 1, altura - 1], raio,
                                                  fill=255)
        faixa = Image.new("RGBA", (largura, altura), (0, 0, 0, 0))
        ImageDraw.Draw(faixa).rectangle([0, 0, espessura - 1, altura - 1], fill=borda_esquerda)
        faixa.putalpha(Image.composite(faixa.getchannel("A"), Image.new("L", faixa.size, 0),
                                       mascara))
        img.alpha_composite(faixa)
    if contorno is not None:
        d.rounded_rectangle([0, 0, largura - 1, altura - 1], raio, outline=contorno[0],
                            width=contorno[1])
    return img


def _icone(img: Image.Image, nome: str, cx: float, cy: float, lado: float, cor) -> None:
    if nome and nome in _icones_existentes():
        icones.desenhar(ImageDraw.Draw(img), nome, cx, cy, lado=lado,
                        largura=max(2.0, lado * 0.09), cor=cor)


@functools.lru_cache(maxsize=1)
def _icones_existentes() -> frozenset[str]:
    return frozenset(icones.nomes())


# ── os sprites (desenhados uma vez) ──────────────────────────────────────


@functools.lru_cache(maxsize=64)
def selo(texto: str, cor: str, icone: str, px: int) -> Image.Image:
    """A etiqueta: ``padding: 6px 26px 10px``, cantos de 18, Anton e sombra."""
    f = anton(px)
    k = px / 58
    largura_do_texto = f.getlength(texto)
    lado_do_icone = px * 0.9 if icone else 0
    largura = round(26 * k + lado_do_icone + (14 * k if icone else 0) + largura_do_texto + 26 * k)
    altura = round(px * 1.15 + 16 * k)
    img = _pilula(largura, altura, round(18 * k), (*_cor(cor), 255))
    d = ImageDraw.Draw(img)
    x = 26 * k
    if icone:
        _icone(img, icone, x + lado_do_icone / 2, altura / 2, lado_do_icone, _texto_sobre(cor))
        x += lado_do_icone + 14 * k
    d.text((x, altura / 2 - 2 * k), texto, font=f, fill=_texto_sobre(cor), anchor="lm")
    return _sombra(img, 14 * k, 14 * k)


@functools.lru_cache(maxsize=64)
def item_da_lista(texto: str, cor: str, icone: str, k: float) -> Image.Image:
    """Um item: 96 de altura, fundo escuro, borda colorida de 12 à esquerda."""
    f = anton(round(60 * k))
    lado = 54 * k if icone else 0
    largura = round(22 * k + lado + (16 * k if icone else 0) + f.getlength(texto) + 30 * k)
    altura = round(96 * k)
    img = _pilula(largura, altura, round(16 * k), (*TINTA, 230),
                  borda_esquerda=(*_cor(cor), 255), espessura=round(12 * k))
    d = ImageDraw.Draw(img)
    x = 22 * k + 12 * k
    if icone:
        _icone(img, icone, x + lado / 2, altura / 2, lado, BRANCO)
        x += lado + 16 * k
    d.text((x, altura / 2 - 2 * k), texto, font=f, fill=BRANCO, anchor="lm")
    return _sombra(img, 12 * k, 12 * k, 0.45)


@functools.lru_cache(maxsize=32)
def botao(texto: str, cor: str, icone: str, k: float) -> Image.Image:
    """O botão da enquete: 800 × 112, cantos de 26 e a borda de baixo mais escura."""
    base = _cor(cor)
    escura = tuple(round(c * 0.55) for c in base)
    largura, altura = round(800 * k), round(112 * k)
    img = _pilula(largura, altura, round(26 * k), (*base, 255), borda_de_baixo=(*escura, 255),
                  espessura=round(10 * k))
    d = ImageDraw.Draw(img)
    f = anton(round(66 * k))
    lado = 60 * k if icone else 0
    total = f.getlength(texto) + (lado + 18 * k if icone else 0)
    x = (largura - total) / 2
    if icone:
        _icone(img, icone, x + lado / 2, (altura - 10 * k) / 2, lado, BRANCO)
        x += lado + 18 * k
    d.text((x, (altura - 10 * k) / 2), texto, font=f, fill=BRANCO, anchor="lm")
    return _sombra(img, 18 * k, 18 * k)


@functools.lru_cache(maxsize=16)
def pagina(rotulo: str, k: float) -> Image.Image:
    """O cartão do carimbo: uma janela de navegador clara (840 × 480), com o rótulo
    grande no meio."""
    largura, altura = round(840 * k), round(480 * k)
    img = _pilula(largura, altura, round(26 * k), (246, 243, 251, 255))
    d = ImageDraw.Draw(img)
    barra = round(72 * k)
    d.rounded_rectangle([0, 0, largura - 1, barra], round(26 * k), fill=(228, 222, 238))
    d.rectangle([0, barra // 2, largura - 1, barra], fill=(228, 222, 238))
    for j, c in enumerate(((255, 95, 87), (254, 188, 46), (40, 200, 64))):
        cx, cy, r = 36 * k + j * 32 * k, barra / 2, 10 * k
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c)
    x0 = 36 * k + 3 * 32 * k
    d.rounded_rectangle([x0, barra / 2 - 22 * k, largura - 26 * k, barra / 2 + 22 * k],
                        round(22 * k), fill=BRANCO)
    endereco = "".join(c if c.isalnum() else "-" for c in rotulo.lower()).strip("-")[:30]
    _icone(img, "cadeado", x0 + 28 * k, barra / 2, 26 * k, (107, 99, 128))
    d.text((x0 + 50 * k, barra / 2), endereco or "pagina", font=negrito(round(24 * k)),
           fill=(107, 99, 128), anchor="lm")
    # Estreito o bastante para continuar inteiro quando a câmera empurra até o carimbo
    # (no foco em pé, ela mostra 63% da largura do palco, de 276 a 960).
    f = anton(round(210 * k))
    while f.getlength(rotulo) > largura * 0.6 and f.size > 40:
        f = anton(f.size - 8)
    # No alto do miolo: o carimbo cai embaixo, à direita, e não cobre o rótulo (no chat,
    # o "APAGADA" cobriu o "404" inteiro até ser mudado de lugar).
    d.text((largura / 2, barra + (altura - barra) * 0.42), rotulo, font=f, fill=TINTA,
           anchor="mm")
    return _sombra(img, 30 * k, 30 * k, 0.6)


@functools.lru_cache(maxsize=16)
def carimbo_vermelho(texto: str, k: float) -> Image.Image:
    """O carimbo do chat: Anton 104, borda vermelha de 11, cantos de 20, fundo branco a
    82% e girado 13°."""
    f = anton(round(104 * k))
    borda = round(11 * k)
    largura = round(f.getlength(texto) + 2 * 26 * k + 2 * borda)
    altura = round(104 * k * 1.15 + 2 * borda)
    img = Image.new("RGBA", (largura, altura), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    vermelho = (*CORES["vermelho"], 255)
    d.rounded_rectangle([0, 0, largura - 1, altura - 1], round(20 * k),
                        fill=(255, 255, 255, 209), outline=vermelho, width=borda)
    d.text((largura / 2, altura / 2), texto, font=f, fill=vermelho, anchor="mm")
    return img.rotate(13, resample=Image.BICUBIC, expand=True)


@functools.lru_cache(maxsize=16)
def placa(texto: str, rotulo: str, cor: str, k: float) -> Image.Image:
    """O destaque: o número ou a data grande numa placa da cor, com um brilho em volta
    (o "18" do chat), e o rótulo pequeno em cima."""
    # Estreita o bastante para caber na janela com o zoom de 1,3 da câmera em cima dela.
    f = anton(round(170 * k))
    while f.getlength(texto) > 600 * k and f.size > 50:
        f = anton(f.size - 6)
    largura = round(max(f.getlength(texto) + 90 * k, 230 * k))
    altura = round(f.size * 1.3)
    corpo = _pilula(largura, altura, round(26 * k), (*_cor(cor), 255))
    ImageDraw.Draw(corpo).text((largura / 2, altura / 2), texto, font=f,
                               fill=_texto_sobre(cor), anchor="mm")
    m = round(50 * k)
    topo = round(64 * k) if rotulo else 0
    fr = negrito(round(34 * k))
    larg_total = max(largura + 2 * m, round(fr.getlength(rotulo) + 40 * k) if rotulo else 0)
    img = Image.new("RGBA", (larg_total, altura + 2 * m + topo), (0, 0, 0, 0))
    x0 = (larg_total - largura) // 2
    alfa = Image.new("L", img.size, 0)
    alfa.paste(corpo.getchannel("A").point(lambda v: round(v * 0.55)), (x0, m + topo))
    brilho = Image.new("RGBA", img.size, (*_cor(cor), 255))
    brilho.putalpha(alfa.filter(ImageFilter.GaussianBlur(35 * k)))
    img.alpha_composite(brilho)
    img.alpha_composite(corpo, (x0, m + topo))
    if rotulo:
        ImageDraw.Draw(img).text((larg_total / 2, m + topo - 14 * k), rotulo, font=fr,
                                 fill=CORES["amarelo"], anchor="ms")
    return img


@functools.lru_cache(maxsize=16)
def fundo_do_quadro(titulo: str, linhas: int, k: float) -> Image.Image:
    """O fundo do quadro: 1000 × 560, escuro, com o título em cima."""
    largura, altura = round(1000 * k), round(560 * k)
    img = _pilula(largura, altura, round(26 * k), (20, 8, 36, 240),
                  contorno=((255, 255, 255, 31), max(1, round(2 * k))))
    if titulo:
        ImageDraw.Draw(img).text((30 * k, 26 * k), titulo, font=negrito(round(30 * k)),
                                 fill=CORES["amarelo"], anchor="la")
    return _sombra(img, 30 * k, 30 * k, 0.6)


@functools.lru_cache(maxsize=64)
def linha_do_quadro(texto: str, valor: str, cor: str, icone: str, largura: float,
                    altura: float, k: float, acesa: bool) -> Image.Image:
    img = Image.new("RGBA", (round(largura), round(altura)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if acesa:
        d.rounded_rectangle([0, 0, img.width - 1, img.height - 1], round(18 * k),
                            fill=(255, 255, 255, 26))
    x = 18 * k
    if icone:
        _icone(img, icone, x + 40 * k, altura / 2, 56 * k, BRANCO)
        x += 100 * k
    tamanho = round(min(66 * k, altura * 0.6))
    d.text((x, altura / 2), texto, font=anton(tamanho), fill=BRANCO, anchor="lm")
    if valor:
        fv = anton(round(tamanho * 0.9))
        lv = fv.getlength(valor) + 48 * k
        pil = _pilula(round(lv), round(altura * 0.72), round(14 * k), (*_cor(cor), 255))
        ImageDraw.Draw(pil).text((lv / 2, pil.height / 2), valor, font=fv,
                                 fill=_texto_sobre(cor), anchor="mm")
        img.alpha_composite(pil, (round(img.width - lv - 18 * k), round((altura - pil.height) / 2)))
    return img


# ── colar com transformação ──────────────────────────────────────────────


def transformar(sprite: Image.Image, *, escala: float = 1.0, giro: float = 0.0,
                opacidade: float = 1.0) -> Image.Image | None:
    """O sprite na escala, girado (graus, sentido horário) e com a opacidade; ``None`` se
    não sobra nada para desenhar."""
    if opacidade <= 0.004 or escala <= 0.01:
        return None
    img = sprite
    if abs(escala - 1) > 1e-3:
        img = img.resize((max(1, round(img.width * escala)), max(1, round(img.height * escala))),
                         Image.BILINEAR)
    if abs(giro) > 0.05:
        img = img.rotate(-giro, resample=Image.BICUBIC, expand=True)
    if opacidade < 0.999:
        img = img.copy()
        img.putalpha(img.getchannel("A").point(lambda v: round(v * opacidade)))
    return img


def colar(tela: Image.Image, sprite: Image.Image, cx: float, cy: float, *, escala: float = 1.0,
          giro: float = 0.0, opacidade: float = 1.0) -> None:
    """O sprite com o centro em ``(cx, cy)``, na escala, girado e com a opacidade. Numa
    tela RGB, ele é colado pela transparência dele; numa RGBA, composto."""
    img = transformar(sprite, escala=escala, giro=giro, opacidade=opacidade)
    if img is None:
        return
    if tela.mode != "RGBA":
        tela.paste(img, (round(cx - img.width / 2), round(cy - img.height / 2)), img)
        return
    if _cabe(tela, img, cx, cy):
        tela.alpha_composite(img, (round(cx - img.width / 2), round(cy - img.height / 2)))
    else:
        _colar_cortado(tela, img, cx, cy)


def _cabe(tela: Image.Image, img: Image.Image, cx: float, cy: float) -> bool:
    x, y = round(cx - img.width / 2), round(cy - img.height / 2)
    return x >= 0 and y >= 0 and x + img.width <= tela.width and y + img.height <= tela.height


def _colar_cortado(tela: Image.Image, img: Image.Image, cx: float, cy: float) -> None:
    x, y = round(cx - img.width / 2), round(cy - img.height / 2)
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(tela.width, x + img.width), min(tela.height, y + img.height)
    if x1 <= x0 or y1 <= y0:
        return
    tela.alpha_composite(img.crop((x0 - x, y0 - y, x1 - x, y1 - y)), (x0, y0))


def escurecer(tela: Image.Image, opacidade: float) -> None:
    """O escurecido atrás dos cartões do palco (``rgba(6, 2, 14, 0.55)``)."""
    if opacidade > 0.004:
        tela.alpha_composite(Image.new("RGBA", tela.size, (6, 2, 14, round(140 * opacidade))))


# ── o desenho em cada instante ───────────────────────────────────────────


def desenhar(tela: Image.Image, c: Cartao, t: float, *, palco: bool) -> None:
    """Desenha o cartão no instante ``t``. ``palco`` diz em que camada se está: os
    cartões do palco só aparecem nela, e os da janela, na outra. A ``tela`` é o palco
    (16:9) ou a janela, em RGBA; as medidas escalam pela largura dela."""
    if c.no_palco != palco or not c.inicio <= t < c.fim:
        return
    k = tela.width / REFERENCIA
    saida = a.some_no_fim(t, c.fim)
    {"selo": _selo, "lista": _lista, "quadro": _quadro, "enquete": _enquete,
     "carimbo": _carimbo, "destaque": _destaque, "flash": _flash}[c.modelo](tela, c, t, k, saida)


def _selo(tela, c: Cartao, t, k, saida) -> None:
    gancho = c.forte is not None and abs(c.forte - c.inicio) < 1e-3
    px = round((80 if gancho else 58) * k)
    s = selo(c.texto, c.cor, c.icone, px)
    escala = a.carimbo(t, c.inicio) if gancho else a.pop(t, c.inicio)
    opac = a.aparece(t, c.inicio, 1 if gancho else 2) * saida
    cx, cy = no_canto(s, 36 * k, 36 * k)
    colar(tela, s, cx, cy, escala=escala, giro=-5 if gancho else -3, opacidade=opac)


def _lista(tela, c: Cartao, t, k, saida) -> None:
    y = 32 * k
    if c.texto:
        s = selo(c.texto, "roxo", "", round(40 * k))
        colar(tela, s, *no_canto(s, 32 * k, y), escala=a.pop(t, c.inicio), giro=-2,
              opacidade=a.aparece(t, c.inicio, 2) * saida)
        y += conteudo(s)[1] + 16 * k
    for j, item in enumerate(c.itens):
        s = item_da_lista(item.texto, RODIZIO[j % len(RODIZIO)], item.icone, round(k, 3))
        if t >= item.em:
            cx, cy = no_canto(s, 32 * k, y)
            colar(tela, s, cx + a.da_esquerda(t, item.em) * conteudo(s)[0], cy,
                  opacidade=a.aparece(t, item.em, 2) * saida)
        y += 96 * k + 16 * k


def _quadro(tela, c: Cartao, t, k, saida) -> None:
    escurecer(tela, a.aparece(t, c.inicio, 5) * saida)
    fundo = fundo_do_quadro(c.texto, len(c.itens), round(k, 3))
    escala = a.pop(t, c.inicio)
    cx, cy = tela.width / 2, tela.height / 2
    colar(tela, fundo, cx, cy, escala=escala, opacidade=saida)
    if escala < 0.98:
        return
    n = max(1, len(c.itens))
    topo = 24 * k + (66 * k if c.texto else 20 * k)
    altura = min(112 * k, (560 * k - (topo - 24 * k) - 24 * k) / n)
    largura = 940 * k
    for j, item in enumerate(c.itens):
        if t < item.em:
            continue
        proximo = c.itens[j + 1].em if j + 1 < len(c.itens) else float("inf")
        acesa = item.em <= t < proximo
        s = linha_do_quadro(item.texto, item.valor, ("vermelho", "amarelo", "roxo", "ciano",
                                                     "rosa")[j % 5],
                            item.icone, largura, altura, round(k, 3), acesa)
        dx = a.da_esquerda(t, item.em) * s.width
        y = cy - 280 * k + topo + j * altura
        colar(tela, s, tela.width / 2 + dx, y + altura / 2,
              opacidade=a.aparece(t, item.em, 3) * saida)


def _enquete(tela, c: Cartao, t, k, saida) -> None:
    comenta = c.forte if c.forte is not None else c.fim
    texto, cor, em = (("VOCÊ DECIDE", "roxo", c.inicio) if t < comenta
                      else ("COMENTA AÍ", "amarelo", comenta))
    s = selo(texto, cor, "", round(58 * k))
    colar(tela, s, *no_canto(s, 36 * k, 36 * k), escala=a.pop(t, em), giro=-3,
          opacidade=a.aparece(t, em, 2) * saida)
    for j, item in enumerate(c.itens[:2]):
        if t < item.em:
            continue
        b = botao(item.texto, "lima" if j == 0 else "vermelho", "certo" if j == 0 else "errado",
                  round(k, 3))
        largura, altura = conteudo(b)
        x = (tela.width - largura) / 2
        y = tela.height - (176 if j == 0 else 40) * k - altura
        colar(tela, b, *no_canto(b, x, y), escala=a.pop(t, item.em),
              opacidade=a.aparece(t, item.em, 2) * saida)


def _carimbo(tela, c: Cartao, t, k, saida) -> None:
    escurecer(tela, a.aparece(t, c.inicio, 5) * saida)
    forte = c.forte if c.forte is not None else c.inicio + 0.5
    dx, dy = a.tremida(t, forte, 9, 16)
    cartao = pagina(c.rotulo or "PÁGINA", round(k, 3))
    cx, cy = tela.width / 2 + dx * k, tela.height / 2 + dy * k
    colar(tela, cartao, cx, cy, escala=a.pop(t, c.inicio), opacidade=saida)
    if t >= forte:
        # Onde o chat deixou o carimbo: embaixo, à direita do rótulo.
        marca = carimbo_vermelho(c.texto, round(k, 3))
        colar(tela, marca, cx + CARIMBO[0] * k, cy + CARIMBO[1] * k,
              escala=a.carimbo(t, forte), opacidade=a.aparece(t, forte, 1) * saida)


def _destaque(tela, c: Cartao, t, k, saida) -> None:
    forte = c.forte if c.forte is not None else c.inicio
    escurecer(tela, a.aparece(t, c.inicio, 5) * saida * 0.8)
    if t < forte:
        return
    p = placa(c.texto, c.rotulo, c.cor, round(k, 3))
    colar(tela, p, tela.width / 2, tela.height / 2, escala=a.carimbo(t, forte),
          opacidade=a.aparece(t, forte, 1) * saida)


def _flash(tela, c: Cartao, t, k, saida) -> None:
    forte = c.forte if c.forte is not None else c.inicio
    luz = a.flash(t, forte)
    if luz > 0.004:
        tela.alpha_composite(Image.new("RGBA", tela.size, (255, 255, 255, round(255 * luz))))
    depois = forte + 4 * a.QUADRO
    if t >= depois and c.texto:
        s = selo(c.texto, c.cor if c.cor != "vermelho" else "amarelo", c.icone or "camera",
                 round(58 * k))
        largura, altura = conteudo(s)
        colar(tela, s, *no_canto(s, tela.width - 40 * k - largura,
                                 tela.height - 30 * k - altura),
              escala=a.pop(t, depois), giro=4, opacidade=a.aparece(t, depois, 2) * saida)


#: Um item que entra até este tanto depois do cartão fica com o som da entrada dele.
JUNTO_DA_ENTRADA_S = 0.15
#: O selo que chama a audiência ("SEGUE PRA MAIS", "COMENTA AÍ") é outro momento de som:
#: no vídeo de referência, só ele tinha whoosh; a etiqueta que explica entrava calada.
CHAMADA = re.compile(r"SEGU|SIGA|INSCREV|COMENT|CURT|COMPARTILH|SININHO|ATIV|LINK|SALV")


def eventos_de_som(c: Cartao) -> list[tuple[str, float]]:
    """Os momentos de som de um cartão e quando tocam (``recursos/sons.json``: a seção
    "cartoes", ou a do tema): o selo (o do gancho é outro evento), a entrada da lista e do
    quadro, cada item depois do primeiro, o erro do carimbo, o número (boom) ou a data
    (ding), o flash e o "comenta" da enquete.

    Como no vídeo de referência, um item com palavra censurada não leva clique: a voz já
    leva o bipe ali."""
    forte = c.forte if c.forte is not None else c.inicio
    if c.modelo == "selo":
        gancho = c.forte is not None and abs(c.forte - c.inicio) < 1e-3
        evento = "gancho" if gancho else "chamada" if CHAMADA.search(c.texto) else "selo"
        return [(evento, c.inicio)]
    if c.modelo in ("lista", "quadro"):
        return [("entrada", c.inicio)] + [
            ("item", i.em) for i in c.itens
            if i.em - c.inicio > JUNTO_DA_ENTRADA_S and "*" not in i.texto]
    if c.modelo == "enquete":
        return ([("item", i.em) for i in c.itens if "*" not in i.texto]
                + ([("comenta", c.forte)] if c.forte else []))
    if c.modelo == "carimbo":
        return [("entrada", c.inicio), ("erro", forte)]
    if c.modelo == "destaque":
        data = " DE " in f" {c.texto} " or "/" in c.texto
        return [("ding" if data else "boom", forte)]
    if c.modelo == "flash":
        return [("flash", forte)]
    return []


def ponto_forte(c: Cartao) -> tuple[float, tuple[float, float]] | None:
    """O instante e o ponto (no palco de 1080 × 608) para onde a câmera empurra. No
    carimbo, o meio do caminho entre o rótulo e o carimbo: mirando o carimbo, como no
    chat, um rótulo maior que "404" saía cortado ("ÁGINA")."""
    if c.modelo == "carimbo":
        return ((c.forte if c.forte is not None else c.inicio + 0.5),
                (540 + CARIMBO[0] / 2, 304 + CARIMBO[1]))
    if c.modelo == "destaque":
        return (c.forte if c.forte is not None else c.inicio), (540, 304)
    return None


__all__ = ["CORES", "MODELOS", "NO_PALCO", "Cartao", "Item", "colar", "desenhar",
           "escurecer", "eventos_de_som", "ponto_forte", "transformar"]
