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

    # Envia, edita e espera a thumbnail desenhada no navegador. A IA e o recorte são os
    # falsos (conftest): três ideias fixas e uma silhueta de busto, sem rede nem modelo.
    video = fazer_video(tmp_path / "meu video.mp4", segundos=4.0)
    pagina.set_input_files("#passo-envio input[type=file]", str(video))
    pagina.locator(".ficha").wait_for(timeout=20_000)
    # No vídeo único, mover a pessoa não aparece: só a montagem tem para onde levá-la.
    expect(pagina.locator("label.interruptor", has_text="Mover a pessoa")).to_have_count(0)
    with pagina.expect_request(lambda r: r.url.split("?")[0].endswith("/api/tarefas")
                               and r.method == "POST") as pedido:
        pagina.get_by_role("button", name="Editar vídeo").click()
    assert "video_id" in pedido.value.post_data_json
    pagina.locator(".miniaturas img").first.wait_for(timeout=120_000)

    # as três ideias viram cartões, e a primeira já é a thumbnail
    ideias = pagina.locator(".ideia")
    expect(ideias).to_have_count(3)
    expect(ideias.nth(0)).to_have_attribute("aria-pressed", "true")
    chamada = pagina.get_by_label("chamada", exact=False).first
    expect(chamada).to_have_value("Corta as pausas sozinho")

    saida = tmp_path / "saida"
    pngs = list(saida.glob("*-thumb-1280x720.png"))
    assert len(pngs) == 1 and list(saida.glob("*-editado.mp4"))
    with Image.open(pngs[0]) as im:
        assert im.size == (1280, 720)
        # não é um retângulo vazio: tem o recorte, o contorno branco e a cor de destaque
        cores = im.convert("RGB").getcolors(1_000_000)
        assert len(cores) > 500
        assert any(r > 250 and g > 250 and b > 250 for _, (r, g, b) in cores)
    primeira = pngs[0].read_bytes()

    # escolher outra ideia e gerar de novo troca a thumbnail
    ideias.nth(2).click()
    expect(ideias.nth(2)).to_have_attribute("aria-pressed", "true")
    pagina.get_by_role("button", name="Gerar as thumbnails de novo").click()
    pagina.wait_for_function("document.querySelector('.miniaturas img') !== null")
    pagina.wait_for_timeout(300)
    expect(pagina.get_by_role("button", name="Gerar as thumbnails de novo")).to_be_enabled(
        timeout=60_000)
    assert pngs[0].read_bytes() != primeira

    # A primeira ideia (falsa) traz a mão apontando: ela está na prévia.
    ideias.nth(0).click()
    previa = pagina.locator(".previa-thumb")
    expect(previa.locator('svg image[href*="/maos/"]').first).to_be_attached()

    # Arrastar a pessoa na prévia muda a posição dela (e "voltar ao automático" acende).
    # A prévia tem de estar na tela: fora dela, o Firefox não entrega o arrasto (e o
    # Chromium entrega, o que escondia o erro do teste).
    previa.scroll_into_view_if_needed()
    caixa = previa.bounding_box()
    x0, y0 = caixa["x"] + caixa["width"] * 0.8, caixa["y"] + caixa["height"] * 0.75
    pagina.mouse.move(x0, y0)
    pagina.mouse.down()
    pagina.mouse.move(x0 - caixa["width"] * 0.2, y0, steps=6)
    pagina.mouse.up()
    pagina.get_by_role("tab", name="Pessoa").click()
    expect(pagina.get_by_role("button", name="Voltar ao automático")).to_be_enabled()

    # As fontes do fundo: a foto do Pexels (falso), a gerada (falsa) e a enviada.
    pagina.get_by_role("tab", name="Fundo").click()
    imagem_no_fundo = previa.locator('svg image[href*="/api/imagens/"]').first
    pagina.get_by_role("button", name="Pexels", exact=True).click()
    pagina.get_by_label("buscar no Pexels").fill("estúdio")
    pagina.get_by_role("button", name="Buscar", exact=True).click()
    pagina.locator(".fotos-pexels button").first.click()
    expect(imagem_no_fundo).to_be_attached()

    pagina.get_by_role("button", name="Gerar com IA").click()
    pagina.get_by_label("descrição do fundo").fill("um estúdio com luz neon")
    pagina.get_by_role("button", name="Gerar fundo (~US$ 0,04)").click()
    expect(pagina.locator(".credito")).to_contain_text("um estúdio com luz neon")

    fundo = tmp_path / "fundo.png"
    Image.new("RGB", (800, 450), (0, 90, 200)).save(fundo)
    pagina.get_by_role("button", name="Imagem", exact=True).click()
    pagina.set_input_files(".soltar-imagem input[type=file]", str(fundo))
    expect(pagina.locator(".soltar-imagem strong")).to_have_text("Arraste uma imagem aqui")
    expect(imagem_no_fundo).to_be_attached()

    pagina.get_by_role("button", name="Cor", exact=True).click()
    expect(imagem_no_fundo).not_to_be_attached()
    assert erros == [], erros


def test_montagem_com_personagem_e_narracao(navegador, endereco, tmp_path):
    """Um fundo sem pessoa, um personagem animado por cima e a narração à parte."""
    from tests.conftest import ler_info
    from tests.test_montagem import audio_wav, gif

    pagina = navegador.new_page(viewport={"width": 1366, "height": 900})
    pagina.add_init_script("localStorage.setItem('editor-tour-visto', '1')")
    erros: list[str] = []
    pagina.on("pageerror", lambda e: erros.append(str(e)))
    pagina.on("console", lambda m: m.type == "error" and erros.append(m.text))
    pagina.goto(endereco)

    pagina.get_by_role("button", name="Um fundo e, por cima").click()
    fundo = fazer_video(tmp_path / "tela.mp4", largura=320, altura=180, segundos=3.0,
                        com_audio=False)
    pagina.set_input_files('[data-envio="fundo"] input', str(fundo))
    expect(pagina.get_by_label("dados do fundo")).to_contain_text("320×180")
    pagina.get_by_role("button", name="Personagem animado").click()
    pagina.set_input_files('[data-envio="personagem"] input', str(gif(tmp_path / "b.gif", lado=80)))
    expect(pagina.get_by_label("dados do personagem")).to_contain_text("4 quadros")
    expect(pagina.locator(".tela-montada .por-cima")).to_be_attached()
    # De onde vem o áudio: com o personagem, só o fundo ou um áudio separado; e o fundo
    # deste teste é mudo, então a pílula dele fica desligada.
    audio_vem_de = pagina.get_by_role("group", name="de onde vem o áudio")
    expect(audio_vem_de.get_by_role("button")).to_have_count(2)
    expect(audio_vem_de.get_by_role("button", name="O vídeo de fundo")).to_be_disabled()
    expect(pagina.locator('[data-envio="audio"]')).to_have_count(0)
    audio_vem_de.get_by_role("button", name="Um áudio separado").click()
    pagina.set_input_files('[data-envio="audio"] input', str(audio_wav(tmp_path / "n.wav")))
    expect(pagina.get_by_label("dados do áudio separado")).to_contain_text("n.wav")
    # a montagem tem o "Mover o personagem" e o formato do quadro
    expect(pagina.locator("label.interruptor", has_text="Mover o personagem")).to_have_count(1)
    pagina.get_by_role("button", name="Em pé (9:16)").click()

    with pagina.expect_request(lambda r: r.url.split("?")[0].endswith("/api/tarefas")
                               and r.method == "POST") as pedido:
        pagina.get_by_role("button", name="Editar vídeo").click()
    montagem = pedido.value.post_data_json["montagem"]
    assert montagem["formato"] == "vertical" and montagem["fala"] == "audio"
    assert montagem["personagem_id"] and montagem["audio_id"] and "pessoa_id" not in montagem
    pagina.locator(".miniaturas img").first.wait_for(timeout=120_000)

    saida = tmp_path / "saida"
    editado = next(saida.glob("tela-editado.mp4"))
    assert (ler_info(editado)["largura"], ler_info(editado)["altura"]) == (180, 320)
    assert list(saida.glob("*-thumb-1280x720.png"))
    assert not erros, erros
