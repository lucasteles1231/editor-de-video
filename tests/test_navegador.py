"""
A página num navegador de verdade (Playwright): o tour, uma edição inteira e a
thumbnail gerada no navegador — no Chromium (Chrome e Edge), no Firefox e no WebKit
(o motor do Safari, que o macOS abre por padrão).

Cada motor que não estiver instalado é pulado:
    uv run playwright install chromium firefox webkit
"""
from __future__ import annotations

import threading
import time

import pytest
from PIL import Image

from tests.conftest import fazer_video

pytestmark = pytest.mark.navegador

playwright = pytest.importorskip("playwright.sync_api")
expect = playwright.expect

PORTA, TOKEN = 8911, "token-do-navegador"


def _instalado(motor: str) -> bool:
    try:
        with playwright.sync_playwright() as p:
            getattr(p, motor).launch().close()
        return True
    except Exception:
        return False


@pytest.fixture(scope="module", params=["chromium", "firefox", "webkit"])
def navegador(request):
    if not _instalado(request.param):
        pytest.skip(f"{request.param} do Playwright não instalado")
    with playwright.sync_playwright() as p:
        nav = getattr(p, request.param).launch()
        yield nav
        nav.close()


@pytest.fixture
def endereco(tmp_path):
    import uvicorn

    from editor import servidor

    app = servidor.criar_app(TOKEN, porta=PORTA, pasta_saida=tmp_path / "saida")
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORTA, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    while not srv.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{PORTA}/?t={TOKEN}"
    srv.should_exit = True
    thread.join(5)


def test_tour_edicao_e_thumbnail(navegador, endereco, tmp_path):
    pagina = navegador.new_page(viewport={"width": 1366, "height": 900})
    erros: list[str] = []
    pagina.on("pageerror", lambda e: erros.append(str(e)))
    pagina.on("console", lambda m: m.type == "error" and erros.append(m.text))
    pagina.goto(endereco)

    # O tour abre sozinho na primeira visita e passa pelos sete passos. Cada passo é
    # esperado antes do clique seguinte: o balão anima entre um e outro, e no CI (mais
    # lento) o texto ainda dizia "6 de 7" logo depois do sexto clique.
    progresso = pagina.locator(".driver-popover-progress-text")
    expect(progresso).to_have_text("1 de 7", timeout=10_000)
    for passo in range(2, 8):
        pagina.locator(".driver-popover-next-btn").click()
        expect(progresso).to_have_text(f"{passo} de 7")
    pagina.locator(".driver-popover-next-btn").click()      # "Começar a editar"
    pagina.locator(".driver-popover").wait_for(state="detached")

    # envia, edita e espera a thumbnail desenhada no navegador
    video = fazer_video(tmp_path / "meu video.mp4", segundos=4.0)
    pagina.set_input_files("#passo-envio input[type=file]", str(video))
    pagina.locator(".ficha").wait_for(timeout=20_000)
    pagina.get_by_role("button", name="Editar vídeo").click()
    pagina.locator(".miniaturas img").first.wait_for(timeout=120_000)

    saida = tmp_path / "saida"
    pngs = list(saida.glob("*-thumb-1280x720.png"))
    assert len(pngs) == 1 and list(saida.glob("*-editado.mp4"))
    with Image.open(pngs[0]) as im:
        assert im.size == (1280, 720)
        # não é um retângulo vazio: o título tem branco e o adesivo tem amarelo
        cores = im.convert("RGB").getcolors(1_000_000)
        assert len(cores) > 500
    assert erros == [], erros
