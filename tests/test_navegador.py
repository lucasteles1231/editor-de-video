"""
A página num navegador de verdade (Playwright): o tour, uma edição inteira e a
thumbnail gerada no navegador — no Chromium (Chrome e Edge), no Firefox e no WebKit
(o motor do Safari, que o macOS abre por padrão).

Cada motor que não estiver instalado é pulado:
    uv run playwright install chromium firefox webkit
"""
from __future__ import annotations

import re
import threading
import time
from pathlib import Path

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


#: Anota cada recurso barrado pela CSP do editor (o Firefox nem sempre põe no console).
VIGIAR_A_CSP = ("window.__barrados = [];"
                "document.addEventListener('securitypolicyviolation',"
                " (e) => window.__barrados.push(e.violatedDirective + ' ' + e.blockedURI));")


def _barrados(pagina) -> list[str]:
    return pagina.evaluate("window.__barrados || []")


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
    pagina.add_init_script(VIGIAR_A_CSP)
    pagina.goto(endereco)

    # O tour abre sozinho na primeira visita: os dois jeitos de usar e um passo por área
    # (nove ao todo). Cada passo é esperado antes do clique seguinte: o balão anima entre
    # um e outro, e no CI (mais lento) o texto ainda dizia "6 de 7" logo depois do sexto
    # clique.
    progresso = pagina.locator(".driver-popover-progress-text")
    expect(progresso).to_have_text("1 de 9", timeout=10_000)
    expect(pagina.locator(".driver-popover-title")).to_have_text("Dois jeitos de usar")
    expect(pagina.locator(".driver-popover-description")).to_contain_text(
        "Notícia com cenas")
    for passo in range(2, 10):
        pagina.locator(".driver-popover-next-btn").click()
        expect(progresso).to_have_text(f"{passo} de 9")
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

    # O vídeo do teste é em pé: a thumbnail sai no formato de Shorts, TikTok e Reels.
    saida = tmp_path / "saida"
    pngs = list(saida.glob("*-thumb-1080x1920.png"))
    assert len(pngs) == 1 and list(saida.glob("*-editado.mp4"))
    with Image.open(pngs[0]) as im:
        assert im.size == (1080, 1920)
        # não é um retângulo vazio: tem o recorte, o contorno branco e a cor de destaque
        cores = im.convert("RGB").getcolors(1_000_000)
        assert len(cores) > 500
        assert any(r > 250 and g > 250 and b > 250 for _, (r, g, b) in cores)
    primeira = pngs[0].read_bytes()

    # Escolher outra ideia e baixar: sai a capa como está na tela, e a da pasta é trocada.
    ideias.nth(2).click()
    expect(ideias.nth(2)).to_have_attribute("aria-pressed", "true")
    with pagina.expect_download(timeout=60_000) as baixada:
        pagina.get_by_role("button", name=re.compile("^Baixar para Shorts, TikTok e Reels")).click()
    jpg = tmp_path / "baixada.jpg"
    baixada.value.save_as(jpg)
    with Image.open(jpg) as im:
        assert im.format == "JPEG" and im.size == (1080, 1920)
    assert jpg.stat().st_size <= 2 * 1024 * 1024
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
    # Em pé (o vídeo do teste), a pessoa fica no meio, embaixo da chamada.
    x0, y0 = caixa["x"] + caixa["width"] * 0.5, caixa["y"] + caixa["height"] * 0.75
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
    # De onde vem o áudio: com o personagem, o fundo, um áudio separado ou a "Minha voz";
    # e o fundo deste teste é mudo, então a pílula dele fica desligada.
    audio_vem_de = pagina.get_by_role("group", name="de onde vem o áudio")
    expect(audio_vem_de.get_by_role("button")).to_have_count(3)
    expect(audio_vem_de.get_by_role("button", name="O vídeo de fundo")).to_be_disabled()
    expect(pagina.locator('[data-envio="audio"]')).to_have_count(0)
    audio_vem_de.get_by_role("button", name="Áudio separado").click()
    pagina.set_input_files('[data-envio="audio"] input', str(audio_wav(tmp_path / "n.wav")))
    expect(pagina.get_by_label("os áudios separados")).to_contain_text("n.wav")
    # a montagem tem o "Mover o personagem"; o fundo é deitado, e o editor recomenda o
    # YouTube. Trocar para o TikTok põe o quadro em pé (o passo 4 acompanha).
    expect(pagina.locator("label.interruptor", has_text="Mover o personagem")).to_have_count(1)
    onde = pagina.get_by_role("group", name="onde você vai postar")
    expect(onde.locator('[aria-pressed="true"]')).to_have_text(re.compile("^YouTube recomendado"))
    onde.get_by_role("button", name=re.compile("^TikTok")).click()
    onde.get_by_role("button", name=re.compile("^YouTube( recomendado)?$")).click()
    em_pe = pagina.get_by_role("button", name="Em pé (9:16)")
    expect(em_pe).to_have_attribute("aria-pressed", "true")

    with pagina.expect_request(lambda r: r.url.split("?")[0].endswith("/api/tarefas")
                               and r.method == "POST") as pedido:
        pagina.get_by_role("button", name="Editar vídeo").click()
    montagem = pedido.value.post_data_json["montagem"]
    assert montagem["formato"] == "vertical" and montagem["fala"] == "audio"
    assert montagem["personagem_id"] and len(montagem["audio_ids"]) == 1
    assert "pessoa_id" not in montagem
    pagina.locator(".miniaturas img").first.wait_for(timeout=120_000)

    saida = tmp_path / "saida"
    editado = next(saida.glob("tela-editado.mp4"))
    assert (ler_info(editado)["largura"], ler_info(editado)["altura"]) == (180, 320)
    assert list(saida.glob("*-thumb-1080x1920.png"))
    assert not _barrados(pagina), _barrados(pagina)
    assert not erros, erros


def test_biblioteca_de_cenas(navegador, endereco, tmp_path):
    """A pasta de cenas com a matriz dentro, nada por cima, a narração em dois arquivos e
    o preset "Notícia com cenas": o pedido leva a biblioteca e os áudios em ordem, e o
    resultado diz quem escreveu o roteiro (a IA falsa, nos testes)."""
    import json

    from tests.test_montagem import audio_wav

    pagina = navegador.new_page(viewport={"width": 1366, "height": 900})
    pagina.add_init_script("localStorage.setItem('editor-tour-visto', '1')")
    erros: list[str] = []
    pagina.on("pageerror", lambda e: erros.append(str(e)))
    pagina.on("console", lambda m: m.type == "error" and erros.append(m.text))
    pagina.add_init_script(VIGIAR_A_CSP)
    pagina.goto(endereco)

    pasta = tmp_path / "cenas"
    (pasta / "clipes").mkdir(parents=True)
    for k, nome in enumerate(["t1-001", "t1-002", "t1-003", "t1-004"]):
        fazer_video(pasta / "clipes" / f"{nome}.mp4", largura=320, altura=180,
                    segundos=1.0 + k * 0.2, com_audio=False)
    matriz = [{"id": "t1-001", "arquivo": "cenas/clipes/t1-001.mp4", "descricao": "explosão",
               "energia": "alta"},
              {"id": "t1-002", "arquivo": "t1-002.mp4", "descricao": "praia"},
              {"id": "t1-003", "arquivo": "t1-003.mp4", "descricao": "boate",
               "monetizacao": "evitar"},
              {"id": "t1-004", "arquivo": "t1-004.mp4", "descricao": "cidade"}]
    (pasta / "cenas.json").write_text(json.dumps(matriz), encoding="utf-8")

    pagina.get_by_role("button", name="Um fundo e, por cima").click()
    pagina.get_by_role("button", name="Biblioteca de cenas").click()
    pagina.set_input_files('[data-envio="cenas"] input', str(pasta))
    ficha = pagina.get_by_label("dados da biblioteca de cenas")
    expect(ficha).to_contain_text("3 cenas", timeout=30_000)
    expect(ficha).to_contain_text("1 marcada “evitar” (fica de fora)")
    pagina.get_by_role("button", name="Nada", exact=True).click()
    # Sem som nos clipes, a fala vem dos áudios (ou da "Minha voz"): dois, que tocam na
    # ordem do nome.
    audio_vem_de = pagina.get_by_role("group", name="de onde vem o áudio")
    expect(audio_vem_de.get_by_role("button")).to_have_count(2)
    pagina.set_input_files('[data-envio="audio"] input',
                           [str(audio_wav(tmp_path / "parte 2.wav")),
                            str(audio_wav(tmp_path / "parte 1.wav"))])
    expect(pagina.get_by_label("os áudios separados")).to_contain_text("1. parte 1.wav")
    expect(pagina.get_by_label("os áudios separados")).to_contain_text("2. parte 2.wav")

    pagina.get_by_role("button", name=re.compile("^Notícia com cenas")).click()
    expect(pagina.locator("label.interruptor", has_text="Janela e câmera")
           .locator("input")).to_be_checked()
    expect(pagina.get_by_role("group", name="Voz").get_by_role("button", name="Estúdio")
           ).to_have_attribute("aria-pressed", "true")
    expect(pagina.get_by_role("group", name="Estilo").get_by_role("button", name="Destaques")
           ).to_have_attribute("aria-pressed", "true")
    expect(pagina.get_by_placeholder("cocaína, sexo, decapitação")).to_have_value(
        re.compile("^cocaína, sexo"))
    # leve, para o teste não demorar (a biblioteca não limita a resolução)
    pagina.get_by_role("button", name="Em pé (9:16)").click()
    resolucao = pagina.locator("label.campo", has_text="Resolução").locator("select")
    expect(resolucao.locator('option[value="2160p"]')).to_be_enabled()
    resolucao.select_option("480p")

    with pagina.expect_request(lambda r: r.url.split("?")[0].endswith("/api/tarefas")
                               and r.method == "POST") as pedido:
        pagina.get_by_role("button", name="Editar vídeo").click()
    dados = pedido.value.post_data_json
    montagem = dados["montagem"]
    assert montagem["biblioteca_id"] and "fundo_id" not in montagem
    assert len(montagem["audio_ids"]) == 2 and montagem["fala"] == "audio"
    assert "pessoa_id" not in montagem and "personagem_id" not in montagem
    assert dados["edicao"]["estilo_da_legenda"] == "destaques"
    expect(pagina.locator(".painel .roteiro")).to_contain_text("Roteiro da IA de teste",
                                                               timeout=180_000)
    assert list((tmp_path / "saida").glob("cenas-editado.mp4"))
    assert not _barrados(pagina), _barrados(pagina)
    assert not erros, erros


def test_minha_voz(navegador, endereco, tmp_path):
    """A "Minha voz" do começo ao fim, com um arquivo no lugar do microfone: o nome, a
    leitura enviada e conferida, a voz salva, o roteiro narrado (pelo motor falso) e o
    pedido de edição com a narração como áudio separado."""
    from tests.test_voz_clonada import _leitura

    pagina = navegador.new_page(viewport={"width": 1366, "height": 900})
    pagina.add_init_script("localStorage.setItem('editor-tour-visto', '1')")
    erros: list[str] = []
    pagina.on("pageerror", lambda e: erros.append(str(e)))
    pagina.on("console", lambda m: m.type == "error" and erros.append(m.text))
    pagina.add_init_script(VIGIAR_A_CSP)
    pagina.goto(endereco)

    pagina.get_by_role("button", name="Um fundo e, por cima").click()
    fundo = fazer_video(tmp_path / "tela.mp4", largura=320, altura=180, segundos=2.0,
                        com_audio=False)
    pagina.set_input_files('[data-envio="fundo"] input', str(fundo))
    expect(pagina.get_by_label("dados do fundo")).to_contain_text("320×180")
    pagina.get_by_role("button", name="Nada", exact=True).click()
    pagina.get_by_role("group", name="de onde vem o áudio").get_by_role(
        "button", name="Minha voz (de um roteiro)").click()
    editar = pagina.get_by_role("button", name="Editar vídeo")
    expect(editar).to_be_disabled()                 # sem a narração, ainda não

    # sem nenhuma voz salva, a gravação abre direto
    gravar = pagina.get_by_label("gravar a sua voz")
    gravar.get_by_label("Seu nome (vai na autorização)").fill("Ana")
    gravar.get_by_role("button", name="Começar a leitura").click()
    expect(gravar.get_by_label("o parágrafo 1")).to_contain_text("Eu, Ana, autorizo")
    paragrafos = gravar.get_by_label("os parágrafos da leitura").get_by_role("button")
    total = paragrafos.count()
    assert total >= 8
    gravar.get_by_role("button", name="Enviar a gravação").click()
    expect(gravar.get_by_label("o texto inteiro")).to_contain_text("Que notícia incrível!")
    gravar.get_by_label("a gravação da leitura inteira").set_input_files(
        str(_leitura(tmp_path / "leitura.wav", total)))
    expect(gravar).to_contain_text(f"{total} de {total} parágrafos aprovados", timeout=30_000)
    expect(gravar.get_by_role("status")).to_contain_text("Parágrafo 1 aprovado")
    salvar = gravar.get_by_role("button", name="Salvar a minha voz")
    expect(salvar).to_be_enabled()
    salvar.click()

    voz = pagina.get_by_label("minha voz")
    expect(voz.get_by_role("group", name="as vozes salvas").get_by_role("button", name="Ana")
           ).to_have_attribute("aria-pressed", "true", timeout=15_000)
    voz.get_by_label("o roteiro a narrar").fill(
        "A Rockstar confirmou: o PEGI deu 18 anos.\n\nE aí, passou do ponto? Comenta aí.")
    voz.locator("summary", has_text="Pronúncia").click()
    voz.get_by_label("a lista de pronúncia").fill("PEGI = pégui")
    voz.get_by_role("button", name="Narrar o roteiro").click()
    expect(voz).to_contain_text("pronta para editar", timeout=30_000)
    expect(voz.locator("summary")).to_have_text("Pronúncia (1)")

    pagina.get_by_role("button", name="Em pé (9:16)").click()
    expect(editar).to_be_enabled()
    with pagina.expect_request(lambda r: r.url.split("?")[0].endswith("/api/tarefas")
                               and r.method == "POST") as pedido:
        editar.click()
    montagem = pedido.value.post_data_json["montagem"]
    assert montagem["fala"] == "audio" and len(montagem["audio_ids"]) == 1
    pagina.locator(".miniaturas img").first.wait_for(timeout=120_000)
    assert list((tmp_path / "saida").glob("tela-editado.mp4"))
    assert not _barrados(pagina), _barrados(pagina)
    assert not erros, erros


def test_minha_voz_pelo_microfone(navegador, endereco):
    """O teleprompter grava pelo microfone de verdade da página (o MediaRecorder): no
    Chromium, um microfone falso que toca bipes. A gravação chega ao servidor, é lida
    pelo PyAV (WebM com Opus) e recebe a nota."""
    if navegador.browser_type.name != "chromium":
        pytest.skip("só o Chromium tem o microfone falso")
    nav = navegador.browser_type.launch(args=["--use-fake-ui-for-media-stream",
                                              "--use-fake-device-for-media-stream"])
    try:
        pagina = nav.new_page()
        pagina.add_init_script("localStorage.setItem('editor-tour-visto', '1')")
        pagina.goto(endereco)
        pagina.get_by_role("button", name="Um fundo e, por cima").click()
        pagina.get_by_role("group", name="de onde vem o áudio").get_by_role(
            "button", name="Minha voz (de um roteiro)").click()
        gravar = pagina.get_by_label("gravar a sua voz")
        gravar.get_by_label("Seu nome (vai na autorização)").fill("Ana")
        gravar.get_by_role("button", name="Começar a leitura").click()
        gravar.get_by_role("button", name="Gravar o parágrafo 1").click()
        parar = gravar.get_by_role("button", name="Parar")
        expect(parar).to_be_visible()
        pagina.wait_for_timeout(3500)
        parar.click()
        # o bipe do microfone falso vem no volume máximo: a nota é "estourou", e as
        # medidas mostram que a gravação foi lida inteira
        resultado = gravar.get_by_role("status")
        expect(resultado).to_contain_text("Regrave o parágrafo 1", timeout=30_000)
        expect(resultado).to_contain_text("O som estourou")
        expect(resultado).to_contain_text("100% das palavras")
        expect(gravar.get_by_role("button", name="Regravar o parágrafo 1")).to_be_visible()
        expect(gravar.get_by_label("parágrafo 1: regravar")).to_be_visible()
    finally:
        nav.close()


def test_gerar_e_revisar_a_matriz(navegador, endereco, tmp_path):
    """Uma pasta sem matriz: o Gemini (aqui, a IA de teste) descreve as cenas, a tabela
    mostra cada uma com a miniatura, a pessoa corrige uma descrição e usa a matriz."""
    pagina = navegador.new_page(viewport={"width": 1366, "height": 1100})
    pagina.add_init_script("localStorage.setItem('editor-tour-visto', '1')")
    erros: list[str] = []
    pagina.on("pageerror", lambda e: erros.append(str(e)))
    pagina.on("console", lambda m: m.type == "error" and erros.append(m.text))
    pagina.goto(endereco)

    pasta = tmp_path / "minhas cenas"
    pasta.mkdir()
    for nome in ("c01-praia.mp4", "c02-carro.mp4", "c03-festa.mp4"):
        fazer_video(pasta / nome, largura=320, altura=180, segundos=1.0, com_audio=False)
    pagina.get_by_role("button", name="Um fundo e, por cima").click()
    pagina.get_by_role("button", name="Biblioteca de cenas").click()
    pagina.set_input_files('[data-envio="cenas"] input', str(pasta))
    gerar = pagina.get_by_role("button", name="Gerar a matriz")
    expect(gerar).to_be_visible(timeout=30_000)
    pagina.get_by_placeholder("do que são as cenas").fill("um jogo de corrida")
    gerar.click()
    revisao = pagina.get_by_role("region", name="revisão da matriz")
    expect(revisao).to_contain_text("3 cenas", timeout=30_000)
    expect(revisao).to_contain_text("IA de teste")
    expect(revisao.locator("img")).to_have_count(3)
    descricao = revisao.get_by_label("descrição de c02-carro.mp4")
    descricao.fill("Carro vermelho correndo na pista")
    revisao.get_by_label("monetização de c03-festa.mp4").select_option("evitar")
    with pagina.expect_download() as baixado:
        revisao.get_by_role("button", name="Baixar o cenas.json").click()
    import json as _json
    salvo = _json.loads(Path(baixado.value.path()).read_text(encoding="utf-8"))
    assert salvo[1]["descricao"] == "Carro vermelho correndo na pista"
    revisao.get_by_role("button", name="Usar esta matriz").click()
    ficha = pagina.get_by_label("dados da biblioteca de cenas")
    expect(ficha).to_contain_text("2 cenas", timeout=30_000)           # a festa ficou de fora
    expect(ficha).to_contain_text("1 marcada “evitar”")
    expect(revisao).to_have_count(0)
    # e dá para voltar à tabela com a matriz em uso
    pagina.get_by_role("button", name="Revisar a matriz").click()
    expect(pagina.get_by_label("descrição de c02-carro.mp4")).to_have_value(
        "Carro vermelho correndo na pista")
    assert not erros, erros


def test_presets_e_sons(navegador, endereco, tmp_path):
    """Escolher um preset muda os controles e o pedido; mexer num controle marca
    "Personalizado"; o "Ouvir" toca os sons do tema."""
    pagina = navegador.new_page(viewport={"width": 1366, "height": 900})
    pagina.add_init_script("localStorage.setItem('editor-tour-visto', '1')")
    erros: list[str] = []
    pagina.on("pageerror", lambda e: erros.append(str(e)))
    pagina.on("console", lambda m: m.type == "error" and erros.append(m.text))
    pagina.goto(endereco)

    presets = pagina.get_by_role("group", name="presets de edição")
    marcado = presets.locator('[aria-pressed="true"]')
    expect(marcado).to_have_text(re.compile("^Padrão"))
    presets.get_by_role("button", name=re.compile("^Short de gameplay")).click()
    expect(marcado).to_have_text(re.compile("^Short de gameplay"))
    tema = pagina.get_by_label("Tema dos sons")
    expect(tema).to_have_value("gameplay")
    expect(pagina.get_by_label("Letras por linha")).to_have_value("14")
    expect(pagina.get_by_label("Quadros por segundo")).to_have_value("60")
    expect(pagina.locator("label.interruptor", has_text="Som em cada corte")
           .locator("input")).to_be_checked()

    # mexer num controle: vira "Personalizado"; escolher de novo volta a marca
    pagina.get_by_label("Letras por linha").select_option("16")
    expect(marcado).to_have_count(0)
    expect(pagina.locator(".preset.personalizado")).to_have_attribute("aria-current", "true")
    presets.get_by_role("button", name=re.compile("^Short de gameplay")).click()
    expect(marcado).to_have_text(re.compile("^Short de gameplay"))

    with pagina.expect_request(lambda r: "/api/sons/gameplay.wav" in r.url) as pedido:
        pagina.get_by_role("button", name="Ouvir").click()
    assert "volume=1.20" in pedido.value.url                 # o volume do preset vai junto
    # O WebKit do Linux entrega o som ao GStreamer, e o Playwright não vê a resposta
    # (status 0): o arquivo é conferido à parte.
    resposta = pagina.request.get(pedido.value.url)
    assert resposta.status == 200 and resposta.headers["content-type"] == "audio/wav"

    video = fazer_video(tmp_path / "jogo.mp4", segundos=3.0)
    pagina.set_input_files("#passo-envio input[type=file]", str(video))
    pagina.locator(".ficha").wait_for(timeout=20_000)
    with pagina.expect_request(lambda r: r.url.split("?")[0].endswith("/api/tarefas")
                               and r.method == "POST") as pedido:
        pagina.get_by_role("button", name="Editar vídeo").click()
    corpo = pedido.value.post_data_json
    assert corpo["edicao"]["tema_dos_sons"] == "gameplay" and corpo["edicao"]["ritmo"] == 1.5
    assert corpo["edicao"]["som_nos_cortes"] is True and corpo["saida"]["fps"] == "60"
    pagina.locator(".miniaturas img").first.wait_for(timeout=120_000)
    # o preset de gameplay faz a thumbnail em pé
    assert list((tmp_path / "saida").glob("*-thumb-1080x1920.png"))
    assert not erros, erros


def test_plataformas_e_baixar(navegador, endereco, tmp_path):
    """A plataforma vem recomendada pelo formato do vídeo, decide o formato da thumbnail e
    mostra onde a capa é cortada; o "Baixar" entrega a capa antes mesmo de editar."""
    pagina = navegador.new_page(viewport={"width": 1366, "height": 900})
    pagina.add_init_script("localStorage.setItem('editor-tour-visto', '1')")
    erros: list[str] = []
    pagina.on("pageerror", lambda e: erros.append(str(e)))
    pagina.on("console", lambda m: m.type == "error" and erros.append(m.text))
    pagina.goto(endereco)

    pagina.set_input_files("#passo-envio input[type=file]", str(fazer_video(tmp_path / "jogo.mp4")))
    pagina.locator(".ficha").wait_for(timeout=20_000)
    onde = pagina.get_by_role("group", name="onde você vai postar")
    marcadas = onde.locator('[aria-pressed="true"]')
    expect(marcadas).to_have_count(3)
    for nome in ("YouTube Shorts", "TikTok", "Instagram Reels"):
        botao = onde.get_by_role("button", name=re.compile(f"^{nome}"))
        expect(botao).to_contain_text("recomendado")
    # a prévia é em pé e mostra os recortes: a busca do YouTube, o perfil e o feed
    expect(pagina.locator(".recorte")).to_have_count(3)
    expect(pagina.locator(".recortes")).to_contain_text(
        "o perfil do TikTok e o perfil do Instagram (3:4)")

    # Marcar o YouTube num vídeo em pé: um aviso, e um segundo formato para baixar.
    onde.get_by_role("button", name=re.compile("^YouTube recomendado|^YouTube$")).click()
    expect(pagina.locator(".plataformas .aviso")).to_contain_text("publica este vídeo como Short")
    expect(pagina.get_by_role("button", name=re.compile("^Baixar para"))).to_have_count(2)

    pagina.get_by_label("Chamada").fill("Teste das plataformas")
    with pagina.expect_download(timeout=60_000) as baixada:
        pagina.get_by_role("button", name="Baixar para Shorts, TikTok e Reels (1080×1920)").click()
    jpg = tmp_path / "capa.jpg"
    baixada.value.save_as(jpg)
    with Image.open(jpg) as im:
        assert im.format == "JPEG" and im.size == (1080, 1920)
    # antes de editar, leva o nome do vídeo enviado
    assert (tmp_path / "saida" / "jogo-thumb-1080x1920.png").is_file()
    expect(pagina.locator(".baixar-um small")).to_contain_text("jogo-thumb-1080x1920.jpg")

    # A última plataforma marcada não desmarca.
    for nome in ("YouTube", "YouTube Shorts", "TikTok", "Instagram Reels"):
        onde.get_by_role("button", name=re.compile(f"^{nome}( recomendado)?$")).click()
    expect(marcadas).to_have_count(1)
    expect(marcadas).to_have_text(re.compile("^Instagram Reels"))
    assert not erros, erros
