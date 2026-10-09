"""
As imagens do README, feitas pelo próprio editor.

    uv run python docs/gerar_imagens.py exemplo.mp4
    uv run python docs/gerar_imagens.py --so-noticia     # só a montagem com cenas e o tour

``exemplo.mp4`` é qualquer vídeo com fala; ele não vai para o repositório. O do README é
"Man doing podcast", de cottonbro studio (Pexels, licença livre), recortado em 9:16 e
com uma narração de teste por cima. A transcrição é a do Whisper de verdade, porque é
isso que o README mostra.

Gera em ``docs/img/``:

- ``banner.png``: 1280×640, que serve também de prévia social do repositório;
- ``antes-depois.png``: o mesmo instante, original e editado;
- ``quadro-legenda.png``, ``quadro-adesivo.png``, ``quadro-icone.png`` e
  ``quadro-montagem.png``. Este sai de uma montagem em camadas: o fundo é uma gravação
  de tela do próprio editor, feita pelo Playwright, e a pessoa do exemplo vai por cima,
  recortada pelo MODNet;
- ``interface-montagem.png``: o passo 1 na montagem, com o fundo, um personagem de
  palito (desenhado aqui mesmo, sem licença de ninguém) e a narração do exemplo;
- ``interface-noticia.png``, ``interface-matriz.png`` e ``interface-tour.png``: o passo 1
  com a biblioteca de cenas (clipes feitos das próprias imagens do README, com uma
  matriz), o palito e dois áudios; a tabela de revisão da matriz; e o tour no passo que
  explica os dois jeitos de usar. Não precisam do exemplo;
- ``interface*.png``: a página, pelo Playwright (precisa do Chromium:
  ``uv run playwright install chromium``), como ela chega para quem instala: sem chave
  nenhuma. A chave de quem gera as imagens nem é lida, porque o final dela apareceria;
- ``thumb-ideias.png`` e ``thumb-abas.png``: as ideias de thumbnail e a prévia com as
  abas. Saem da IA de teste; com ``--ia-de-verdade``, do Gemini, com a chave salva no
  editor (gasta um ou dois pedidos da cota);
- ``funcoes/*.svg``: os ícones das funções, do Tabler (baixados do unpkg).
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from editor import icones, legenda, render, saida, video  # noqa: E402
from editor.opcoes import OpcoesDeEdicao  # noqa: E402

IMG = RAIZ / "docs" / "img"

# As cores da interface (web/src/estilo.css).
PAPEL = (255, 252, 245)
TINTA = (26, 26, 26)
AMARELO = (255, 212, 0)
ROSA = (255, 61, 127)
CIANO = (0, 194, 255)
LIMA = (155, 225, 93)
ROXO = (179, 107, 255)
CINZA = (160, 160, 160)

#: Tudo é desenhado no dobro do tamanho e reduzido no fim: o Pillow não suaviza borda.
S = 2


# ── o vídeo de exemplo ─────────────────────────────────────────────────────


def editar(exemplo: Path, pasta: Path) -> tuple[Path, dict]:
    import json

    destino = pasta / "exemplo-editado.mp4"
    r = render.editar(exemplo, destino, OpcoesDeEdicao(), saida.OpcoesDeSaida())
    print(f"  editado: {r.duracao_original:.1f} s → {r.duracao_final:.1f} s")
    return r.video, json.loads(Path(r.plano).read_text(encoding="utf-8"))


def no_original(t: float, trechos: list[list[float]]) -> float:
    """O instante do vídeo original que virou ``t`` no editado."""
    acumulado = 0.0
    for ini, fim in trechos:
        if t <= acumulado + (fim - ini):
            return ini + (t - acumulado)
        acumulado += fim - ini
    return trechos[-1][1]


def instantes(plano: dict) -> dict[str, float]:
    """Os três momentos dos quadros de exemplo, tirados do que a edição decidiu."""
    adesivo = plano["adesivos"][0]
    no_adesivo = (adesivo["inicio"], adesivo["fim"])
    icone = next((i for i in plano["icones"]
                  if not no_adesivo[0] - 0.5 <= i["inicio"] <= no_adesivo[1]),
                 plano["icones"][0])
    ocupados = [no_adesivo] + [(i["inicio"], i["fim"]) for i in plano["icones"]]

    def livre(t: float) -> bool:
        return not any(a - 0.1 <= t <= b + 0.1 for a, b in ocupados)

    # Karaokê: um bloco de três palavras ou mais, a chave já dita e a última ainda não
    # (de preferência com a chave no meio: branco, amarelo e cinza na mesma linha).
    legenda_t = None
    for no_meio in (True, False):
        for b in plano["blocos"]:
            ws, k = b["palavras"], b["chave"]
            if len(ws) < 3 or not (1 if no_meio else 0) <= k < len(ws) - 1:
                continue
            t = ws[-1]["inicio"] - 0.04
            if t > ws[k]["inicio"] + 0.1 and livre(t) and t - b["inicio"] > 0.2:
                legenda_t = t
                break
        if legenda_t is not None:
            break
    return {"adesivo": adesivo["inicio"] + 0.45, "icone": icone["inicio"] + 0.55,
            "legenda": legenda_t if legenda_t is not None else plano["blocos"][1]["inicio"] + 0.3}


def editar_montagem(exemplo: Path, tela: Path, pasta: Path) -> tuple[Path, dict]:
    """A montagem em camadas: a gravação de tela no fundo e a pessoa do exemplo por cima,
    recortada pelo MODNet, num quadro em pé."""
    import json

    from editor.montagem import Montagem

    destino = pasta / "exemplo-montado.mp4"
    m = Montagem(tela, pessoa=exemplo, recorte="modnet", formato="vertical")
    r = render.editar(None, destino, OpcoesDeEdicao(), saida.OpcoesDeSaida(), montagem=m)
    print(f"  montado: {r.duracao_final:.1f} s em {r.segundos:.0f} s")
    return r.video, json.loads(Path(r.plano).read_text(encoding="utf-8"))


def desenhar_palito(caminho: Path) -> Path:
    """Um palito falando, em GIF transparente: 8 quadros, a boca e os braços mexendo."""
    import math

    quadros = []
    largura, altura = 300, 420
    tinta, branco = (26, 26, 26, 255), (255, 255, 255, 255)
    for k in range(8):
        im = Image.new("RGBA", (largura, altura), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        cx, cy, r = largura // 2, 95, 62
        braco = 20 * math.sin(k / 8 * 2 * math.pi)
        for cor, grossura in ((tinta, 18), (branco, 10)):
            d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=cor, width=grossura)
            d.line((cx, cy + r, cx, 290), fill=cor, width=grossura)
            d.line((cx, 190, cx - 80, 250 + braco), fill=cor, width=grossura)
            d.line((cx, 190, cx + 80, 230 - braco), fill=cor, width=grossura)
            d.line((cx, 290, cx - 60, 400), fill=cor, width=grossura)
            d.line((cx, 290, cx + 60, 400), fill=cor, width=grossura)
        d.ellipse((cx - r + 9, cy - r + 9, cx + r - 9, cy + r - 9), fill=branco)
        for ox in (-22, 22):
            d.ellipse((cx + ox - 7, cy - 18, cx + ox + 7, cy - 4), fill=tinta)
        boca = (4, 16, 8, 20, 6, 14, 3, 18)[k]
        d.ellipse((cx - 16, cy + 20, cx + 16, cy + 20 + boca), fill=tinta)
        quadros.append(im)
    quadros[0].save(caminho, save_all=True, append_images=quadros[1:], duration=110, loop=0,
                    disposal=2)
    return caminho


def biblioteca_de_exemplo(pasta: Path) -> Path:
    """Uma biblioteca de cenas para as capturas: clipes de 2 s, em 16:9, feitos das
    próprias imagens do README, e a matriz deles (``cenas.json``) na mesma pasta."""
    import av
    import numpy as np

    cenas = pasta / "cenas"
    (cenas / "clipes").mkdir(parents=True, exist_ok=True)
    fontes = {"estudio-microfone": ("quadro-legenda.png", "Homem fala ao microfone num estúdio",
                                    ["podcast", "close"]),
              "adesivo-amarelo": ("quadro-adesivo.png", "A palavra salta num balão amarelo",
                                  ["podcast", "legenda"]),
              "icone-moeda": ("quadro-icone.png", "Uma moeda aparece ao lado de quem fala",
                              ["dinheiro", "podcast"]),
              "tela-do-editor": ("quadro-montagem.png", "A tela do editor gravada, com a pessoa "
                                 "por cima", ["tela", "tutorial"]),
              "antes-e-depois": ("antes-depois.png", "O mesmo quadro, antes e depois",
                                 ["comparacao"]),
              "capa-do-editor": ("banner.png", "A capa do editor de vídeo", ["cartela"])}
    matriz = []
    for k, (nome, (imagem, descricao, categorias)) in enumerate(fontes.items()):
        with Image.open(IMG / imagem) as im:
            im = im.convert("RGB")
            alto = min(im.height, round(im.width * 9 / 16))
            topo = (im.height - alto) // 2
            quadro_ = np.asarray(im.crop((0, topo, im.width, topo + alto)).resize((640, 360)))
        arquivo = cenas / "clipes" / f"{nome}.mp4"
        with av.open(str(arquivo), "w") as c:
            v = c.add_stream("libx264", rate=30, options={"crf": "28", "preset": "ultrafast"})
            v.width, v.height, v.pix_fmt = 640, 360, "yuv420p"
            for i in range(60):
                f = av.VideoFrame.from_ndarray(quadro_, format="rgb24")
                f.pts = i
                for pacote in v.encode(f):
                    c.mux(pacote)
            for pacote in v.encode():
                c.mux(pacote)
        matriz.append({"id": f"c{k + 1:02d}", "arquivo": f"clipes/{nome}.mp4",
                       "descricao": descricao, "categorias": categorias,
                       "periodo": "n/a" if nome in ("tela-do-editor", "capa-do-editor")
                       else "interno", "energia": "alta" if k == 0 else "media",
                       "monetizacao": "evitar" if nome == "antes-e-depois" else "ok",
                       "obs": "texto na tela" if nome == "capa-do-editor" else ""})
    (cenas / "cenas.json").write_text(json.dumps(matriz, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    return cenas


def partes_de_narracao(pasta: Path) -> list[Path]:
    """Dois "parágrafos" de narração de teste (um tom com pausas): na captura, só os nomes
    e as durações aparecem."""
    import wave

    import numpy as np

    partes = []
    for k, segundos in ((1, 6.0), (2, 8.5)):
        t = np.arange(int(segundos * video.TAXA)) / video.TAXA
        som = 0.2 * np.sin(2 * np.pi * 220 * t) * ((t % 1.2) < 0.9)
        caminho = pasta / f"Parágrafo {k}.wav"
        with wave.open(str(caminho), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(video.TAXA)
            w.writeframes((som * 32767).astype("<i2").tobytes())
        partes.append(caminho)
    return partes


def narracao(exemplo: Path, caminho: Path) -> Path:
    """O áudio do exemplo em WAV, como uma narração gravada à parte."""
    import wave

    import numpy as np

    mono = video.ler_audio(exemplo).mean(axis=1)
    with wave.open(str(caminho), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(video.TAXA)
        w.writeframes((np.clip(mono, -1, 1) * 32767).astype("<i2").tobytes())
    return caminho


def no_movimento(plano: dict) -> float:
    """Um instante com a pessoa fora do lugar: de preferência num lado, com o ícone do
    outro, que é o que mais mostra a função."""
    movimentos = plano["movimentos"]
    if not movimentos:
        raise SystemExit("a edição com a pessoa mudando de lugar não moveu ninguém")
    lado = [m for m in movimentos if m["posicao"] in ("esquerda", "direita")]
    m = (lado or movimentos)[0]
    icone = next((i for i in plano["icones"] if m["inicio"] <= i["inicio"] < m["fim"]), None)
    if icone is not None:
        return min(icone["inicio"] + 0.55, m["fim"] - 0.05)
    return (m["inicio"] + m["fim"]) / 2


def quadro(caminho: Path, t: float) -> Image.Image:
    return Image.fromarray(video.quadro_em(caminho, t)).convert("RGB")


# ── desenho ────────────────────────────────────────────────────────────────


def arredondar(im: Image.Image, raio: int) -> Image.Image:
    """Cantos arredondados (com transparência), suavizados."""
    grande = Image.new("L", (im.width * 4, im.height * 4), 0)
    ImageDraw.Draw(grande).rounded_rectangle([0, 0, grande.width - 1, grande.height - 1],
                                             raio * 4, fill=255)
    saida_ = im.convert("RGBA")
    saida_.putalpha(grande.resize(im.size, Image.LANCZOS))
    return saida_


def adesivo(texto: str, px: int, *, estilo: int, giro: float) -> Image.Image:
    """Uma palavra no adesivo do editor (a mesma forma e as mesmas cores da legenda)."""
    cor_forma, cor_texto, cor_contorno = legenda.CORES_DO_ADESIVO[estilo % 4]
    f = legenda.fonte(px)
    largura = f.getlength(texto) + px * legenda.FORMA_SOBRA_X
    altura = px + px * legenda.FORMA_SOBRA_Y
    lado = int(max(largura * 1.3, altura * 2.2) + 40)
    camada = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    d = ImageDraw.Draw(camada)
    meio = lado / 2
    pontos = [(meio + x, meio + y) for x, y in legenda.forma(largura, altura, estilo)]
    d.polygon([(x + px * 0.12, y + px * 0.14) for x, y in pontos], fill=(0, 0, 0, 150))
    traco = max(2, round(px * 0.08))
    d.polygon(pontos, fill=(*cor_forma, 255), outline=(0, 0, 0, 255), width=traco)
    d.text((meio, meio), texto, font=f, fill=cor_texto, anchor="mm",
           stroke_width=traco if cor_contorno else 0, stroke_fill=cor_contorno or cor_texto)
    return camada.rotate(giro, resample=Image.BICUBIC)


def colar(fundo: Image.Image, im: Image.Image, cx: float, cy: float) -> None:
    fundo.alpha_composite(im, (round(cx - im.width / 2), round(cy - im.height / 2)))


def pilula(d: ImageDraw.ImageDraw, x: float, y: float, texto: str, px: int,
           fundo: tuple[int, int, int], tinta=TINTA, borda=TINTA) -> float:
    """Uma etiqueta com borda; devolve onde a próxima começa."""
    f = legenda.fonte(px)
    w = f.getlength(texto)
    folga_x, alto = px * 0.75, px * 1.9
    d.rounded_rectangle([x, y, x + w + 2 * folga_x, y + alto], alto / 2, fill=fundo,
                        outline=borda, width=max(2, px // 9))
    d.text((x + folga_x, y + alto / 2), texto, font=f, fill=tinta, anchor="lm")
    return x + w + 2 * folga_x


def celular(tela: Image.Image, altura: int) -> Image.Image:
    """A tela dentro de um celular, com a sombra dura amarela da interface."""
    w = round(altura * tela.width / tela.height)
    tela = tela.resize((w, altura), Image.LANCZOS)
    borda, raio = round(altura * 0.028), round(altura * 0.075)
    W, H = w + 2 * borda, altura + 2 * borda
    corpo = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(corpo)
    d.rounded_rectangle([0, 0, W - 1, H - 1], raio, fill=(8, 8, 8, 255),
                        outline=(*PAPEL, 255), width=max(3, borda // 3))
    mascara = Image.new("L", (w, altura), 0)
    ImageDraw.Draw(mascara).rounded_rectangle([0, 0, w - 1, altura - 1], raio - borda, fill=255)
    corpo.paste(tela, (borda, borda), mascara)
    pilha = round(altura * 0.018)
    d.rounded_rectangle([W / 2 - pilha * 4, borda + pilha, W / 2 + pilha * 4, borda + pilha * 3],
                        pilha, fill=(8, 8, 8, 255))
    desloca = round(altura * 0.03)
    tudo = Image.new("RGBA", (W + desloca, H + desloca), (0, 0, 0, 0))
    sombra = Image.new("RGBA", corpo.size, (*AMARELO, 255))
    tudo.paste(sombra, (desloca, desloca), corpo.getchannel("A"))
    tudo.alpha_composite(corpo, (0, 0))
    return tudo


def banner(tela: Image.Image) -> Image.Image:
    W, H = 1280 * S, 640 * S
    im = Image.new("RGBA", (W, H), (*TINTA, 255))
    d = ImageDraw.Draw(im)
    x0 = 76 * S

    # A marca, como no topo da página: "editor" no adesivo, "de vídeo" ao lado.
    px = 64 * S
    f = legenda.fonte(px)
    largura_do_selo = f.getlength("editor") + px * legenda.FORMA_SOBRA_X
    colar(im, adesivo("editor", px, estilo=0, giro=4), x0 + largura_do_selo / 2, 150 * S)
    d.text((x0 + largura_do_selo + 16 * S, 150 * S), "de vídeo", font=f, fill=PAPEL, anchor="lm")

    # A frase da página, com a palavra-chave em amarelo como na legenda.
    f = legenda.fonte(40 * S)
    y = 268 * S
    x = x0
    for palavra, cor in (("Seu", PAPEL), ("vídeo", PAPEL), ("falado,", PAPEL),
                         ("editado", legenda.AMARELO)):
        d.text((x, y), palavra, font=f, fill=cor, anchor="ls")
        x += f.getlength(palavra + " ")
    d.text((x0, y + 56 * S), "no estilo dos Shorts.", font=f, fill=PAPEL, anchor="ls")

    # O que ele faz, em etiquetas com as cores da interface.
    linhas = [[("legenda karaokê", AMARELO), ("corta silêncio", ROSA), ("zoom", CIANO)],
              [("adesivos", LIMA), ("ícones", ROXO), ("sons", AMARELO), ("thumbnail", ROSA)]]
    y = 372 * S
    for linha in linhas:
        x = x0
        for texto, cor in linha:
            x = pilula(d, x, y, texto, 22 * S, cor) + 12 * S
        y += 58 * S

    f = legenda.fonte(20 * S)
    d.text((x0, 540 * S), "100% local  ·  Windows e macOS  ·  código aberto",
           font=f, fill=CINZA, anchor="ls")

    # O celular com um quadro editado, inclinado, e os ícones em volta.
    fone = celular(tela, 520 * S).rotate(-4, resample=Image.BICUBIC, expand=True)
    colar(im, fone, 1012 * S, 322 * S)
    for nome, cx, cy, raio, semente in (("foguete", 836, 150, 48, 3),
                                        ("coracao", 1190, 490, 44, 5),
                                        ("lampada", 1196, 126, 40, 7)):
        colar(im, icones.balao(nome, raio * S, semente), cx * S, cy * S)

    return arredondar(im.resize((1280, 640), Image.LANCZOS), 22)


def antes_depois(antes: Image.Image, depois: Image.Image) -> Image.Image:
    alto = 620 * S
    larg = round(alto * antes.width / antes.height)
    W, H = 2 * larg + 300 * S, alto + 150 * S
    im = Image.new("RGBA", (W, H), (*TINTA, 255))
    d = ImageDraw.Draw(im)
    xs = (60 * S, W - 60 * S - larg)
    lados = ((xs[0], antes, "antes", PAPEL), (xs[1], depois, "depois", AMARELO))
    for x, quadro_, texto, cor in lados:
        foto = arredondar(quadro_.resize((larg, alto), Image.LANCZOS), 18 * S)
        im.alpha_composite(foto, (x, 110 * S))
        f = legenda.fonte(26 * S)
        w = f.getlength(texto) + 40 * S
        pilula(d, x + (larg - w) / 2, 40 * S, texto, 26 * S, cor)
    # A seta, com o traço tremido dos ícones.
    from editor import rough_draw

    meio_y = 110 * S + alto / 2
    a, b = xs[0] + larg + 50 * S, xs[1] - 50 * S
    rough_draw.caminho(d, f"M {a} {meio_y} L {b} {meio_y}", semente=4, largura=7 * S,
                       cor=AMARELO)
    rough_draw.caminho(d, f"M {b - 38 * S} {meio_y - 34 * S} L {b} {meio_y} L {b - 38 * S} "
                          f"{meio_y + 34 * S}", semente=5, largura=7 * S, cor=AMARELO)
    return arredondar(im.resize((W // S, H // S), Image.LANCZOS), 22)


# ── as capturas da interface ───────────────────────────────────────────────


#: Todas as imagens das prévias já chegaram (o recorte e o quadro levam segundos logo
#: depois da edição, e a captura saía com a pessoa faltando). Um cartão ainda esperando
#: o recorte não tem imagem nenhuma, então ele precisa ter sido desenhado antes.
CARREGADAS = """() => !document.querySelector('.carregando-ideia')
  && [...document.querySelectorAll('.ideia')].every((b) => b.querySelector('svg'))
  && [...document.querySelectorAll('.ideias svg image, .thumb-area svg image')].every((i) => {
    const href = i.getAttribute('href') || '';
    if (!href || href.startsWith('data:')) return true;
    const url = new URL(href, location.href).href;
    return performance.getEntriesByName(url).some((e) => e.responseEnd > 0);
  })"""


def gravar_tela(exemplo: Path, pasta: Path) -> Path:
    """Uma gravação de tela do próprio editor (o fundo sem pessoa da montagem): a página
    abre, recebe o exemplo e rola até o fim e de volta."""
    import shutil

    import uvicorn
    from playwright.sync_api import sync_playwright

    from editor import chaves, servidor

    config = chaves.pasta_de_config
    chaves.pasta_de_config = lambda: pasta / "config"
    porta, token = 8930, "gravacao-do-readme"
    app = servidor.criar_app(token, porta=porta, pasta_saida=pasta / "saida-da-gravacao")
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=porta, log_level="warning"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.05)
    destino = pasta / "tela.webm"
    try:
        with sync_playwright() as p:
            nav = p.chromium.launch()
            ctx = nav.new_context(viewport={"width": 1280, "height": 720},
                                  record_video_dir=str(pasta / "gravacao"),
                                  record_video_size={"width": 1280, "height": 720})
            ctx.add_init_script("localStorage.setItem('editor-tour-visto', '1')")
            pagina = ctx.new_page()
            pagina.goto(f"http://127.0.0.1:{porta}/?t={token}")
            pagina.wait_for_timeout(1200)
            pagina.set_input_files("#passo-envio input[type=file]", str(exemplo))
            pagina.locator(".ficha").wait_for(timeout=60_000)
            pagina.wait_for_timeout(1500)
            for _ in range(65):
                pagina.mouse.wheel(0, 40)
                pagina.wait_for_timeout(110)
            for _ in range(30):
                pagina.mouse.wheel(0, -90)
                pagina.wait_for_timeout(110)
            pagina.wait_for_timeout(1000)
            gravado = pagina.video.path()
            ctx.close()
            nav.close()
        shutil.copy(gravado, destino)
    finally:
        srv.should_exit = True
        chaves.pasta_de_config = config
    print("  gravação de tela do editor")
    return destino


SEM_TOUR = ("localStorage.setItem('editor-tour-visto', '1');"
            "performance.setResourceTimingBufferSize(10000);")


def salvar(png: bytes, nome: str, largura: int = 1600) -> None:
    caminho = IMG / nome
    caminho.write_bytes(png)
    with Image.open(caminho) as im:
        im = im.convert("RGB")
        if im.width > largura:
            im = im.resize((largura, round(im.height * largura / im.width)), Image.LANCZOS)
        arredondar(im, 14).save(caminho, optimize=True)
    print(f"  {nome}")


@contextlib.contextmanager
def servidor_isolado(pasta: Path):
    """O servidor do editor como ele chega para quem instala: sem chave nenhuma (a de quem
    gera as imagens nem é lida, porque o final dela apareceria). Devolve o endereço e a
    pasta de configuração de verdade, para quem quiser a IA de verdade depois."""
    import uvicorn

    from editor import chaves, servidor

    config_de_verdade = chaves.pasta_de_config
    chaves.pasta_de_config = lambda: pasta / "config"
    for nome in ("GEMINI_API_KEY", "PEXELS_API_KEY", "EDITOR_IA", "EDITOR_PEXELS"):
        os.environ.pop(nome, None)
    porta, token = 8931, "imagens-do-readme"
    app = servidor.criar_app(token, porta=porta, pasta_saida=pasta / "saida")
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=porta, log_level="warning"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{porta}/?t={token}", config_de_verdade
    finally:
        chaves.pasta_de_config = config_de_verdade
        srv.should_exit = True


def capturas_da_noticia(nav, url: str, pasta: Path) -> None:
    """O passo 1 com a biblioteca de cenas, o palito por cima e dois áudios; e o tour, no
    passo que explica os dois jeitos de usar."""
    cenas = biblioteca_de_exemplo(pasta)
    partes = partes_de_narracao(pasta)
    palito = desenhar_palito(pasta / "palito.gif")
    ctx = nav.new_context(viewport={"width": 1280, "height": 1500}, device_scale_factor=2,
                          color_scheme="light")
    ctx.add_init_script(SEM_TOUR)
    pagina = ctx.new_page()
    pagina.goto(url)
    pagina.get_by_role("button", name="Um fundo e, por cima").click()
    pagina.get_by_role("button", name="Biblioteca de cenas").click()
    pagina.set_input_files('[data-envio="cenas"] input', str(cenas))
    pagina.get_by_label("dados da biblioteca de cenas").wait_for(timeout=60_000)
    pagina.get_by_role("button", name="Personagem animado").click()
    pagina.set_input_files('[data-envio="personagem"] input', str(palito))
    pagina.get_by_label("dados do personagem").wait_for(timeout=60_000)
    pagina.set_input_files('[data-envio="audio"] input', [str(p) for p in partes])
    pagina.get_by_label("os áudios separados").get_by_text("Parágrafo 2").wait_for(
        timeout=60_000)
    onde = pagina.get_by_role("group", name="onde você vai postar")
    onde.get_by_role("button", name=re.compile("^YouTube Shorts")).click()
    onde.get_by_role("button", name=re.compile("^YouTube( recomendado)?$")).click()
    pagina.get_by_role("button", name=re.compile("^Notícia com cenas")).click()
    pagina.wait_for_timeout(1200)
    # O cabeçalho fica preso no topo e cobriria o começo do passo na captura do elemento.
    estilo = pagina.add_style_tag(content=".cabecalho { position: static !important; }")
    salvar(pagina.locator("#passo-envio").screenshot(), "interface-noticia.png", 1200)

    # A tabela de revisão, com a matriz em uso.
    pagina.get_by_role("button", name="Revisar a matriz").click()
    revisao = pagina.get_by_role("region", name="revisão da matriz")
    revisao.locator("img").first.wait_for()
    pagina.wait_for_function("[...document.querySelectorAll('.revisao img')]"
                             ".slice(0, 3).every(i => i.complete && i.naturalWidth > 0)")
    pagina.wait_for_timeout(500)
    salvar(revisao.screenshot(), "interface-matriz.png", 1200)
    revisao.get_by_role("button", name="Fechar").click()
    estilo.evaluate("e => e.remove()")

    # O tour, no primeiro passo: os dois jeitos de usar.
    pagina.set_viewport_size({"width": 1280, "height": 800})
    pagina.evaluate("window.scrollTo(0, 0)")
    pagina.get_by_role("button", name="Tour").click()
    pagina.locator(".driver-popover-title").get_by_text("Dois jeitos de usar").wait_for()
    pagina.wait_for_timeout(900)
    salvar(pagina.screenshot(), "interface-tour.png")
    ctx.close()


def capturas(exemplo: Path, pasta: Path, *, ia_de_verdade: bool = False,
             tela: Path | None = None, com_ideias: bool = True) -> None:
    from playwright.sync_api import sync_playwright

    from editor import chaves

    with servidor_isolado(pasta) as (url, config_de_verdade):
        _capturas(exemplo, pasta, url, config_de_verdade, ia_de_verdade=ia_de_verdade,
                  tela=tela, com_ideias=com_ideias, sync_playwright=sync_playwright,
                  chaves=chaves)


def _capturas(exemplo: Path, pasta: Path, url: str, config_de_verdade, *,
              ia_de_verdade: bool, tela: Path | None, com_ideias: bool, sync_playwright,
              chaves) -> None:
    sem_tour = SEM_TOUR

    def enviar(pagina) -> None:
        pagina.goto(url)
        pagina.set_input_files("#passo-envio input[type=file]", str(exemplo))
        pagina.locator(".ficha").wait_for(timeout=60_000)
        pagina.wait_for_function("document.querySelector('video.tela')?.readyState >= 2")
        pagina.wait_for_timeout(1500)                   # a prévia da thumbnail desenha

    with sync_playwright() as p:
        nav = p.chromium.launch()
        try:
            for tema in ("dark", "light"):
                ctx = nav.new_context(viewport={"width": 1280, "height": 800},
                                      device_scale_factor=2, color_scheme=tema)
                ctx.add_init_script(sem_tour)
                pagina = ctx.new_page()
                enviar(pagina)
                nome = "interface-escuro.png" if tema == "dark" else "interface.png"
                salvar(pagina.screenshot(), nome)
                if tema == "dark":
                    ctx.close()
                    continue

                # A edição andando, e depois o resultado e a thumbnail.
                pagina.get_by_role("button", name="Editar vídeo").click()
                pagina.wait_for_function(
                    "[...document.querySelectorAll('.etapas li')]"
                    ".some(li => /desenhar/i.test(li.textContent)"
                    " && li.className.includes('atual'))",
                    timeout=180_000)
                pagina.wait_for_timeout(1200)
                salvar(pagina.locator("#botao-editar").screenshot(), "interface-progresso.png", 900)
                pagina.locator(".miniaturas img").first.wait_for(timeout=300_000)
                pagina.wait_for_timeout(1500)            # o painel rola até o resultado
                pagina.evaluate("window.scrollTo(0, document.querySelector('#passo-thumb')"
                                ".getBoundingClientRect().top + window.scrollY - 104)")
                # O script grava numa pasta temporária, para não encher a pasta de vídeos
                # de quem gera as imagens; a captura mostra a pasta padrão do macOS.
                pagina.evaluate("document.querySelector('.salvo-em code').textContent = "
                                "'~/Movies/editor-de-video'")
                pagina.wait_for_timeout(800)
                salvar(pagina.screenshot(), "interface-resultado.png")
                ctx.close()

            # O passo 1 na montagem: o fundo, o personagem de palito e a narração.
            if tela is not None:
                ctx = nav.new_context(viewport={"width": 1280, "height": 1400},
                                      device_scale_factor=2, color_scheme="light")
                ctx.add_init_script(sem_tour)
                pagina = ctx.new_page()
                pagina.goto(url)
                pagina.get_by_role("button", name="Um fundo e, por cima").click()
                pagina.set_input_files('[data-envio="fundo"] input', str(tela))
                pagina.get_by_label("dados do fundo").wait_for(timeout=60_000)
                pagina.get_by_role("button", name="Personagem animado").click()
                pagina.set_input_files('[data-envio="personagem"] input',
                                       str(desenhar_palito(pasta / "palito.gif")))
                pagina.get_by_label("dados do personagem").wait_for(timeout=60_000)
                pagina.get_by_role("group", name="de onde vem o áudio").get_by_role(
                    "button", name="Áudio separado").click()
                pagina.set_input_files('[data-envio="audio"] input',
                                       str(narracao(exemplo, pasta / "narracao.wav")))
                pagina.get_by_label("os áudios separados").wait_for(timeout=60_000)
                pagina.wait_for_timeout(1200)
                salvar(pagina.locator("#passo-envio").screenshot(), "interface-montagem.png", 1200)
                ctx.close()

            # A montagem com a biblioteca de cenas, e o tour.
            capturas_da_noticia(nav, url, pasta)

            # A thumbnail com IA: as três ideias e a prévia com as abas.
            if not com_ideias:
                return
            if ia_de_verdade:
                chaves.pasta_de_config = config_de_verdade
            else:
                os.environ["EDITOR_IA"] = "falsa"
            ctx = nav.new_context(viewport={"width": 1280, "height": 1500},
                                  device_scale_factor=2, color_scheme="light")
            ctx.add_init_script(sem_tour)
            pagina = ctx.new_page()
            enviar(pagina)
            pagina.get_by_role("button", name="Editar vídeo").click()
            pagina.wait_for_function(
                "document.querySelectorAll('.ideia').length === 3"
                " || document.querySelector('.painel-ia .aviso.erro')", timeout=300_000)
            erro = pagina.locator(".painel-ia .aviso.erro")
            if erro.count():
                raise SystemExit(f"o Gemini não deu ideias: {erro.first.inner_text()}")
            pagina.locator("#painel-ia").scroll_into_view_if_needed()
            pagina.wait_for_function(CARREGADAS, timeout=120_000)
            pagina.wait_for_timeout(800)
            salvar(pagina.locator(".ideias").screenshot(), "thumb-ideias.png")
            pagina.get_by_role("tab", name="Fundo").click()
            pagina.locator(".thumb-area").scroll_into_view_if_needed()
            pagina.wait_for_function(CARREGADAS, timeout=120_000)
            pagina.wait_for_timeout(800)
            salvar(pagina.locator(".thumb-area").screenshot(), "thumb-abas.png")
            ctx.close()
        finally:
            chaves.pasta_de_config = config_de_verdade
            os.environ.pop("EDITOR_IA", None)
            nav.close()


def so_noticia() -> None:
    """Só as imagens da montagem com cenas e do tour, e os ícones: sem o vídeo de exemplo."""
    from playwright.sync_api import sync_playwright

    icones_das_funcoes()
    with tempfile.TemporaryDirectory() as tmp, servidor_isolado(Path(tmp)) as (url, _), \
            sync_playwright() as p:
        nav = p.chromium.launch()
        try:
            capturas_da_noticia(nav, url, Path(tmp))
        finally:
            nav.close()


# ── os ícones das funções ──────────────────────────────────────────────────

TABLER = "https://unpkg.com/@tabler/icons@3.48.0/icons/outline/{}.svg"

#: Função → (ícone do Tabler, cor do fundo).
FUNCOES = {
    "cortes": ("scissors", AMARELO), "legenda": ("badge-cc", ROSA),
    "adesivos": ("sticker", CIANO), "zoom": ("zoom-in", LIMA),
    "pessoa": ("arrows-move", ROSA), "icones": ("icons", ROXO),
    "sons": ("volume", AMARELO), "thumbnail": ("photo", ROSA), "local": ("lock", CIANO),
    "cenas": ("movie", LIMA), "cartoes": ("layout-cards", CIANO), "voz": ("microphone", ROXO),
}


def icones_das_funcoes() -> None:
    pasta = IMG / "funcoes"
    pasta.mkdir(parents=True, exist_ok=True)
    for nome, (tabler, cor) in FUNCOES.items():
        with urllib.request.urlopen(TABLER.format(tabler), timeout=30) as r:
            svg = r.read().decode("utf-8")
        miolo = re.search(r"<svg[^>]*>(.*)</svg>", svg, re.S).group(1)
        miolo = re.sub(r'<path stroke="none" d="M0 0h24v24H0z" fill="none"\s*/>', "", miolo).strip()
        hexa = "#{:02x}{:02x}{:02x}".format(*cor)
        (pasta / f"{nome}.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="44" height="44" viewBox="0 0 44 44">'
            '<rect x="4" y="4" width="38" height="38" rx="10" fill="#1a1a1a"/>'
            f'<rect x="1.5" y="1.5" width="38" height="38" rx="10" fill="{hexa}" '
            'stroke="#1a1a1a" stroke-width="2.5"/>'
            '<g transform="translate(8.5 8.5)" fill="none" stroke="#1a1a1a" stroke-width="2" '
            f'stroke-linecap="round" stroke-linejoin="round">{miolo}</g></svg>\n',
            encoding="utf-8")
    print(f"  funcoes/ ({len(FUNCOES)} ícones)")


# ── tudo ───────────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    ap.add_argument("exemplo", type=Path, nargs="?", help="um vídeo com fala")
    ap.add_argument("--so-noticia", action="store_true",
                    help="só a montagem com cenas, o tour e os ícones (sem o exemplo)")
    ap.add_argument("--sem-capturas", action="store_true", help="pula as capturas da página")
    ap.add_argument("--ia-de-verdade", action="store_true",
                    help="as ideias de thumbnail vêm do Gemini, com a chave salva no editor")
    ap.add_argument("--sem-ideias", action="store_true",
                    help="não refaz as capturas das ideias de thumbnail (guarda a cota)")
    args = ap.parse_args()
    IMG.mkdir(parents=True, exist_ok=True)
    if args.so_noticia:
        so_noticia()
        return 0
    if args.exemplo is None:
        ap.error("falta o vídeo de exemplo (ou use --so-noticia)")
    with tempfile.TemporaryDirectory() as tmp:
        pasta = Path(tmp)
        editado, plano = editar(args.exemplo, pasta)
        ts = instantes(plano)
        print("  instantes:", {k: round(v, 2) for k, v in ts.items()})
        quadros = {k: quadro(editado, t) for k, t in ts.items()}
        for k, im in quadros.items():
            pequeno = im.resize((540, round(540 * im.height / im.width)), Image.LANCZOS)
            arredondar(pequeno, 22).save(IMG / f"quadro-{k}.png", optimize=True)
            print(f"  quadro-{k}.png")
        tela = gravar_tela(args.exemplo, pasta)
        montado, plano_montado = editar_montagem(args.exemplo, tela, pasta)
        quadros["montagem"] = quadro(montado, no_movimento(plano_montado))
        montagem_ = quadros["montagem"]
        pequeno = montagem_.resize((540, round(540 * montagem_.height / montagem_.width)),
                                   Image.LANCZOS)
        arredondar(pequeno, 22).save(IMG / "quadro-montagem.png", optimize=True)
        print("  quadro-montagem.png")
        original = quadro(args.exemplo, no_original(ts["adesivo"], plano["trechos"]))
        antes_depois(original, quadros["adesivo"]).save(IMG / "antes-depois.png", optimize=True)
        print("  antes-depois.png")
        banner(quadros["adesivo"]).save(IMG / "banner.png", optimize=True)
        print("  banner.png")
        icones_das_funcoes()
        if not args.sem_capturas:
            capturas(args.exemplo, pasta, ia_de_verdade=args.ia_de_verdade, tela=tela,
                     com_ideias=not args.sem_ideias)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
