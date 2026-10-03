"""
A interface no navegador: um servidor local que serve a página e a API.

**Só no próprio computador, e só para quem abriu.** O servidor escuta em
``127.0.0.1`` e cada sessão tem um token aleatório, que vai na URL aberta no
navegador; toda chamada da API precisa dele (no cabeçalho ``X-Editor-Token`` ou, para
o player e as imagens, em ``?t=``). O ``Host`` e o ``Origin`` também são conferidos:
sem isso, qualquer site aberto no mesmo navegador poderia mandar o editor trabalhar.
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from importlib.resources import files
from pathlib import Path
from typing import Annotated

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image

from editor import __version__, icones, transcricao
from editor import saida as saida_mod
from editor import video as video_mod
from editor.opcoes import OpcoesDeEdicao
from editor.tarefas import Gerente, Ocupado, Tarefa

#: O YouTube recusa thumbnail maior que 2 MB.
JPG_MAXIMO = 2 * 1024 * 1024
#: Envios mais velhos que isto são apagados quando a interface abre.
GUARDAR_ENVIOS_S = 2 * 24 * 3600


def pasta_de_envios() -> Path:
    from platformdirs import user_cache_dir

    pasta = Path(user_cache_dir("editor-de-video", appauthor=False)) / "envios"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def pasta_de_saida_padrao() -> Path:
    from platformdirs import user_videos_dir

    return Path(user_videos_dir()) / "editor-de-video"


def _limpar_envios_antigos(pasta: Path) -> None:
    agora = time.time()
    for item in pasta.iterdir():
        try:
            if agora - item.stat().st_mtime > GUARDAR_ENVIOS_S:
                shutil.rmtree(item, ignore_errors=True)
        except OSError:
            continue


def _nome_seguro(nome: str) -> str:
    """O nome do arquivo sem caminho e sem caracteres que o Windows recusa."""
    base = Path(nome or "video.mp4").name
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", base).strip(" .")
    return base or "video.mp4"


def _livre(destino: Path) -> Path:
    """Um nome que ainda não existe: video-editado.mp4, video-editado-2.mp4..."""
    if not destino.exists():
        return destino
    for n in range(2, 1000):
        outro = destino.with_name(f"{destino.stem}-{n}{destino.suffix}")
        if not outro.exists():
            return outro
    return destino.with_name(f"{destino.stem}-{uuid.uuid4().hex[:6]}{destino.suffix}")


def nitidez(matriz: np.ndarray) -> float:
    """O quanto o quadro está nítido (variância do laplaciano), penalizando o escuro."""
    cinza = matriz.mean(axis=2)
    lap = (-4 * cinza[1:-1, 1:-1] + cinza[:-2, 1:-1] + cinza[2:, 1:-1]
           + cinza[1:-1, :-2] + cinza[1:-1, 2:])
    brilho = float(cinza.mean())
    return float(lap.var()) * (0.3 if brilho < 40 or brilho > 230 else 1.0)


def abrir_pasta(pasta: Path) -> None:
    """Abre a pasta no gerenciador de arquivos do sistema."""
    if sys.platform.startswith("win"):
        os.startfile(str(pasta))  # a forma do Windows de abrir uma pasta
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(pasta)])
    else:
        subprocess.Popen(["xdg-open", str(pasta)])


def criar_app(token: str, *, porta: int, pasta_saida: Path | None = None,
              estatico: Path | None = None) -> FastAPI:
    app = FastAPI(title="editor-de-video", version=__version__, docs_url=None, redoc_url=None)
    gerente = Gerente()
    envios = pasta_de_envios()
    _limpar_envios_antigos(envios)
    saida_base = pasta_saida or pasta_de_saida_padrao()
    videos: dict[str, dict] = {}
    hosts = {f"127.0.0.1:{porta}", f"localhost:{porta}"}
    origens = {f"http://{h}" for h in hosts}

    @app.middleware("http")
    async def guarda(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            if request.headers.get("host") not in hosts:
                return JSONResponse({"erro": "endereço não permitido"}, status_code=403)
            origem = request.headers.get("origin")
            if origem and origem not in origens:
                return JSONResponse({"erro": "origem não permitida"}, status_code=403)
            dado = request.headers.get("x-editor-token") or request.query_params.get("t")
            if not dado or not secrets.compare_digest(dado, token):
                return JSONResponse({"erro": "token ausente ou inválido"}, status_code=401)
        return await call_next(request)

    def _video(vid: str) -> dict:
        if vid not in videos:
            raise HTTPException(404, "vídeo não encontrado — envie de novo")
        return videos[vid]

    def _tarefa(tid: str) -> Tarefa:
        if tid not in gerente.tarefas:
            raise HTTPException(404, "edição não encontrada")
        return gerente.tarefas[tid]

    @app.get("/api/estado")
    def estado():
        return {
            "versao": __version__,
            "formatos": saida_mod.disponiveis(),
            "codecs": {c: v[2] for c, v in saida_mod.CODECS.items()},
            "resolucoes": list(saida_mod.RESOLUCOES), "fps": list(saida_mod.FPS),
            "qualidades": list(saida_mod.QUALIDADES),
            "modelos": [{"nome": m, "tamanho": t, "baixado": transcricao.modelo_baixado(m)}
                        for m, t in transcricao.MODELOS.items()],
            "padroes": {"edicao": OpcoesDeEdicao().para_dict(),
                        "saida": saida_mod.OpcoesDeSaida().para_dict()},
            "pasta_saida": str(saida_base), "ocupado": gerente.ocupado(),
            "gif_max_s": saida_mod.GIF_MAX_S,
        }

    @app.post("/api/videos")
    def enviar(arquivo: Annotated[UploadFile, File()]):
        vid = uuid.uuid4().hex[:12]
        pasta = envios / vid
        pasta.mkdir(parents=True)
        destino = pasta / _nome_seguro(arquivo.filename or "video.mp4")
        with destino.open("wb") as f:
            shutil.copyfileobj(arquivo.file, f, length=1024 * 1024)
        try:
            info = video_mod.sondar(destino)
        except Exception as erro:
            shutil.rmtree(pasta, ignore_errors=True)
            raise HTTPException(400, f"não consegui ler este vídeo: {erro}") from erro
        videos[vid] = {"caminho": destino, "info": info, "nome": destino.name}
        return {"id": vid, "nome": destino.name, "tamanho_bytes": destino.stat().st_size,
                "largura": info.largura, "altura": info.altura, "fps": float(info.fps),
                "duracao": round(info.duracao, 2), "vertical": info.vertical,
                "tem_audio": info.tem_audio}

    @app.get("/api/videos/{vid}/arquivo")
    def video_original(vid: str):
        return FileResponse(_video(vid)["caminho"])

    # O instante se chama "segundo", e não "t": o "t" da URL é o token da sessão
    # (o navegador busca a imagem sozinho, sem cabeçalho). Com os dois como "t", o
    # servidor lia o token no lugar do instante e devolvia 422.
    @app.get("/api/videos/{vid}/quadro")
    def quadro(vid: str, segundo: float = 0.0, largura: int = 1280):
        v = _video(vid)
        matriz = video_mod.quadro_em(v["caminho"], segundo, v["info"].rotacao)
        if matriz is None:
            raise HTTPException(404, "sem quadro nesse instante")
        img = Image.fromarray(matriz)
        if img.width > largura:
            img = img.resize((largura, round(img.height * largura / img.width)),
                             Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=90)
        return Response(buf.getvalue(), media_type="image/jpeg",
                        headers={"Cache-Control": "max-age=3600"})

    @app.get("/api/videos/{vid}/quadro-automatico")
    def quadro_automatico(vid: str):
        v = _video(vid)
        dur = v["info"].duracao
        candidatos = [dur * (0.1 + 0.8 * k / 11) for k in range(12)]
        melhor, nota = candidatos[0], -1.0
        for t in candidatos:
            m = video_mod.quadro_em(v["caminho"], t, v["info"].rotacao)
            if m is None:
                continue
            pequeno = np.asarray(Image.fromarray(m).resize((320, round(320 * m.shape[0]
                                                                        / m.shape[1]))))
            n = nitidez(pequeno.astype(np.float32))
            if n > nota:
                melhor, nota = t, n
        return {"t": round(melhor, 2)}

    @app.post("/api/tarefas")
    async def criar_tarefa(request: Request):
        dados = await request.json()
        v = _video(str(dados.get("video_id", "")))
        edicao = OpcoesDeEdicao.de_dict(dados.get("edicao") or {})
        saida = saida_mod.OpcoesDeSaida.de_dict(dados.get("saida") or {})
        erros = edicao.problemas() + saida.problemas()
        if erros:
            raise HTTPException(422, "; ".join(erros))
        previa = dados.get("previa_s")
        saida_base.mkdir(parents=True, exist_ok=True)
        destino = _livre(saida_base / f"{Path(v['nome']).stem}-editado.{saida.formato}")
        try:
            t = gerente.iniciar(Tarefa(v["caminho"], destino, edicao, saida,
                                       float(previa) if previa else None))
        except Ocupado as erro:
            raise HTTPException(409, "já há uma edição rodando") from erro
        return t.para_dict()

    @app.get("/api/tarefas/{tid}")
    def ver_tarefa(tid: str):
        return _tarefa(tid).para_dict()

    @app.get("/api/tarefas/{tid}/eventos")
    async def eventos(tid: str):
        t = _tarefa(tid)

        async def fluxo():
            visto = -1
            while True:
                if t.versao != visto:
                    visto = t.versao
                    yield f"data: {json.dumps(t.para_dict(), ensure_ascii=False)}\n\n"
                if t.estado != "rodando":
                    return
                await asyncio.sleep(0.4)

        return StreamingResponse(fluxo(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})

    @app.post("/api/tarefas/{tid}/cancelar")
    def cancelar(tid: str):
        _tarefa(tid).cancelar.set()
        return {"ok": True}

    def _arquivo(t: Tarefa, tipo: str) -> Path:
        if t.estado != "pronto" or not t.resultado:
            raise HTTPException(409, "a edição ainda não terminou")
        if tipo == "video":
            return Path(t.resultado["video"])
        if tipo == "plano":
            return Path(t.resultado["plano"])
        for caminho in t.resultado.get("legendas", []) + t.resultado.get("thumbnails", []):
            if Path(caminho).name == tipo or Path(caminho).suffix == f".{tipo}":
                return Path(caminho)
        raise HTTPException(404, "arquivo não encontrado")

    @app.get("/api/tarefas/{tid}/arquivo/{tipo}")
    def baixar(tid: str, tipo: str, inline: int = 0):
        caminho = _arquivo(_tarefa(tid), tipo)
        if not caminho.is_file():
            raise HTTPException(404, "o arquivo não está mais lá")
        if inline:
            return FileResponse(caminho)
        return FileResponse(caminho, filename=caminho.name)

    @app.post("/api/tarefas/{tid}/thumbnail")
    def salvar_thumbnail(tid: str, imagem: Annotated[UploadFile, File()],
                         nome: Annotated[str, Form()]):
        t = _tarefa(tid)
        if t.estado != "pronto" or not t.resultado:
            raise HTTPException(409, "a edição ainda não terminou")
        if not re.fullmatch(r"[0-9]{2,4}x[0-9]{2,4}", nome):
            raise HTTPException(422, "nome da thumbnail inválido")
        img = Image.open(imagem.file).convert("RGB")
        base = Path(t.resultado["video"])
        png = base.with_name(f"{base.stem}-thumb-{nome}.png")
        img.save(png, "PNG", optimize=True)
        jpg = png.with_suffix(".jpg")
        for qualidade in (92, 85, 78, 70, 60):
            img.save(jpg, "JPEG", quality=qualidade, optimize=True)
            if jpg.stat().st_size <= JPG_MAXIMO:
                break
        t.resultado.setdefault("thumbnails", [])
        for c in (str(png), str(jpg)):
            if c not in t.resultado["thumbnails"]:
                t.resultado["thumbnails"].append(c)
        return {"png": png.name, "jpg": jpg.name, "jpg_bytes": jpg.stat().st_size}

    @app.post("/api/abrir-pasta")
    def abrir_a_pasta():
        saida_base.mkdir(parents=True, exist_ok=True)
        abrir_pasta(saida_base)
        return {"ok": True}

    @app.get("/api/icones")
    def lista_de_icones():
        return {nome: icones.caminhos(nome) for nome in icones.nomes()}

    @app.get("/fontes/DejaVuSans-Bold.ttf")
    def fonte():
        dados = (files("editor") / "recursos" / "DejaVuSans-Bold.ttf").read_bytes()
        return Response(dados, media_type="font/ttf",
                        headers={"Cache-Control": "max-age=86400"})

    pasta_estatica = estatico or Path(str(files("editor") / "interface" / "estatico"))
    if (pasta_estatica / "index.html").is_file():
        app.mount("/", StaticFiles(directory=pasta_estatica, html=True), name="pagina")
    else:
        @app.get("/")
        def sem_pagina():
            return Response("A página não foi montada (rode npm run build em web/).",
                            media_type="text/plain; charset=utf-8")

    app.state.gerente = gerente
    app.state.videos = videos
    return app


def abrir(*, porta: int = 0, navegador: bool = True) -> int:
    """Sobe a interface e abre o navegador nela. Fica rodando até Ctrl+C."""
    import uvicorn

    soquete = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    soquete.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        soquete.bind(("127.0.0.1", porta))
    except OSError:
        print(f"a porta {porta} está ocupada — rode sem --porta para usar uma livre")
        return 2
    porta = soquete.getsockname()[1]
    token = secrets.token_urlsafe(24)
    app = criar_app(token, porta=porta)
    url = f"http://127.0.0.1:{porta}/?t={token}"
    servidor = uvicorn.Server(uvicorn.Config(app, log_level="warning"))

    def quando_subir() -> None:
        while not servidor.started:
            time.sleep(0.05)
        print(f"\n  editor-de-video {__version__} aberto em:\n  {url}\n\n"
              "  (Ctrl+C para fechar)\n", flush=True)
        if navegador:
            webbrowser.open(url)

    threading.Thread(target=quando_subir, daemon=True).start()
    with contextlib.suppress(KeyboardInterrupt):
        servidor.run(sockets=[soquete])
    return 0


__all__ = ["abrir", "abrir_pasta", "criar_app", "nitidez"]
