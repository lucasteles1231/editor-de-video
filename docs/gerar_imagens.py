"""
As imagens do README, feitas pelo próprio editor.

    uv run python docs/gerar_imagens.py exemplo.mp4

``exemplo.mp4`` é qualquer vídeo com fala; ele não vai para o repositório. O do README é
"Man doing podcast", de cottonbro studio (Pexels, licença livre), recortado em 9:16 e
com uma narração de teste por cima. A transcrição é a do Whisper de verdade, porque é
isso que o README mostra.

Gera em ``docs/img/``:

- ``banner.png``: 1280×640, que serve também de prévia social do repositório;
- ``antes-depois.png``: o mesmo instante, original e editado;
- ``quadro-legenda.png``, ``quadro-adesivo.png`` e ``quadro-icone.png``;
- ``interface*.png``: a página, pelo Playwright (precisa do Chromium:
  ``uv run playwright install chromium``);
- ``funcoes/*.svg``: os ícones das funções, do Tabler (baixados do unpkg).
"""
from __future__ import annotations

import argparse
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


def capturas(exemplo: Path, pasta: Path) -> None:
    import uvicorn
    from playwright.sync_api import sync_playwright

    from editor import servidor

    porta, token = 8931, "imagens-do-readme"
    app = servidor.criar_app(token, porta=porta, pasta_saida=pasta / "saida")
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=porta, log_level="warning"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.05)
    url = f"http://127.0.0.1:{porta}/?t={token}"
    sem_tour = "localStorage.setItem('editor-tour-visto', '1')"

    def salvar(png: bytes, nome: str, largura: int = 1600) -> None:
        caminho = IMG / nome
        caminho.write_bytes(png)
        with Image.open(caminho) as im:
            im = im.convert("RGB")
            if im.width > largura:
                im = im.resize((largura, round(im.height * largura / im.width)), Image.LANCZOS)
            arredondar(im, 14).save(caminho, optimize=True)
        print(f"  {nome}")

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

                # O tour, no passo das opções de saída.
                pagina.get_by_role("button", name="Tour").click()
                for _ in range(3):
                    pagina.locator(".driver-popover-next-btn").click()
                    pagina.wait_for_timeout(500)
                pagina.wait_for_timeout(900)
                salvar(pagina.screenshot(), "interface-tour.png")
                pagina.keyboard.press("Escape")
                pagina.locator(".driver-popover").wait_for(state="detached")

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
        finally:
            nav.close()
            srv.should_exit = True


# ── os ícones das funções ──────────────────────────────────────────────────

TABLER = "https://unpkg.com/@tabler/icons@3.48.0/icons/outline/{}.svg"

#: Função → (ícone do Tabler, cor do fundo).
FUNCOES = {
    "cortes": ("scissors", AMARELO), "legenda": ("badge-cc", ROSA),
    "adesivos": ("sticker", CIANO), "zoom": ("zoom-in", LIMA), "icones": ("icons", ROXO),
    "sons": ("volume", AMARELO), "thumbnail": ("photo", ROSA), "local": ("lock", CIANO),
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
    ap.add_argument("exemplo", type=Path, help="um vídeo com fala")
    ap.add_argument("--sem-capturas", action="store_true", help="pula as capturas da página")
    args = ap.parse_args()
    IMG.mkdir(parents=True, exist_ok=True)
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
        original = quadro(args.exemplo, no_original(ts["adesivo"], plano["trechos"]))
        antes_depois(original, quadros["adesivo"]).save(IMG / "antes-depois.png", optimize=True)
        print("  antes-depois.png")
        banner(quadros["adesivo"]).save(IMG / "banner.png", optimize=True)
        print("  banner.png")
        icones_das_funcoes()
        if not args.sem_capturas:
            capturas(args.exemplo, pasta)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
