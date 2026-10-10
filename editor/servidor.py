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
import hashlib
import io
import json
import logging
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
import wave
import webbrowser
from importlib.resources import files
from pathlib import Path
from typing import Annotated

import numpy as np
from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image

from editor import (
    __version__,
    catalogo,
    cenas,
    ia,
    icones,
    imagens,
    montagem,
    motor_de_voz,
    pexels,
    presets,
    recorte,
    sons,
    transcricao,
    voz_clonada,
)
from editor import saida as saida_mod
from editor import video as video_mod
from editor.opcoes import OpcoesDeEdicao
from editor.tarefas import Gerente, Ocupado, Tarefa

logger = logging.getLogger(__name__)

#: O YouTube recusa thumbnail maior que 2 MB.
JPG_MAXIMO = 2 * 1024 * 1024
#: As fontes que a página pode pedir (a da legenda e a da chamada da thumbnail).
FONTES = ("DejaVuSans-Bold.ttf", "Anton-Regular.ttf")
#: Quantos recortes ficam guardados: cada um é um quadro inteiro mais o alfa.
RECORTES_GUARDADOS = 6
#: As mãos que apontam (Fluent UI Emoji, MIT): só estes arquivos são servidos.
MAOS = tuple(sorted(f"mao-{estilo}-{tom}.{'png' if estilo == '3d' else 'svg'}"
                    for estilo in ("3d", "vetor")
                    for tom in ("default", "light", "medium-light", "medium", "medium-dark",
                                "dark")))
#: A matriz da biblioteca de cenas (o cenas.json do chat tinha 80 KB) e as partes do
#: áudio separado.
MATRIZ_MAXIMA = 2 * 1024 * 1024
PARTES_MAXIMAS = 30
#: Envios mais velhos que isto são apagados quando a interface abre.
GUARDAR_ENVIOS_S = 2 * 24 * 3600
#: Os cabeçalhos de toda resposta. A página não tem script na linha e não carrega nada de
#: fora: tudo vem do próprio editor (as fotos do Pexels passam por ele). Os estilos na
#: linha são os do React (``style={...}``); ``blob:`` e ``data:`` são a thumbnail desenhada
#: no navegador e os áudios gravados. Ninguém põe a página dentro de outra (``frame-
#: ancestors``), e o endereço, com o token, nunca vai no ``Referer``.
POLITICA = "; ".join([
    "default-src 'self'", "script-src 'self'", "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:", "media-src 'self' data: blob:", "font-src 'self' data:",
    "connect-src 'self' data: blob:", "worker-src 'self' blob:", "object-src 'none'",
    "base-uri 'none'", "form-action 'none'", "frame-ancestors 'none'",
])
CABECALHOS = {"Content-Security-Policy": POLITICA, "Referrer-Policy": "no-referrer",
              "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
              "Cross-Origin-Opener-Policy": "same-origin"}


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


def _wav(amostras: np.ndarray, taxa: int) -> bytes:
    """Um WAV mono de 16 bits."""
    pcm = (np.clip(amostras, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    corpo = io.BytesIO()
    with wave.open(corpo, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taxa)
        w.writeframes(pcm)
    return corpo.getvalue()


def nitidez(matriz: np.ndarray) -> float:
    """O quanto o quadro está nítido (variância do laplaciano), penalizando o escuro."""
    cinza = matriz.mean(axis=2)
    lap = (-4 * cinza[1:-1, 1:-1] + cinza[:-2, 1:-1] + cinza[2:, 1:-1]
           + cinza[1:-1, :-2] + cinza[1:-1, 2:])
    brilho = float(cinza.mean())
    return float(lap.var()) * (0.3 if brilho < 40 or brilho > 230 else 1.0)


def quadros_candidatos(caminho: Path, info: video_mod.Info, n: int = ia.QUADROS,
                       lado: int = ia.LADO_DO_QUADRO, *, alfa: bool = False
                       ) -> list[tuple[float, bytes]]:
    """Os ``n`` quadros para o Gemini olhar: os mais nítidos entre 24 amostras, espalhados
    pelo vídeo, em JPEG pequeno. Em ordem de tempo. Com ``alfa`` (a pessoa já sem fundo),
    ela vai sobre um cinza: atrás dela, o arquivo pode ter qualquer coisa."""
    dur = max(0.1, info.duracao)
    amostras = []
    for k in range(24):
        t = dur * (0.05 + 0.9 * k / 23)
        m = video_mod.quadro_em(caminho, t, info.rotacao, alfa=alfa)
        if m is None:
            continue
        if m.shape[2] == 4:
            cinza = Image.new("RGBA", (m.shape[1], m.shape[0]), (128, 128, 128, 255))
            img = Image.alpha_composite(cinza, Image.fromarray(m, "RGBA")).convert("RGB")
        else:
            img = Image.fromarray(m)
        pequeno = np.asarray(img.resize((320, max(1, round(320 * img.height / img.width)))))
        amostras.append((nitidez(pequeno.astype(np.float32)), t, img))
    escolhidos: list[tuple[float, Image.Image]] = []
    espaco = dur / 12
    for _nota, t, img in sorted(amostras, key=lambda a: -a[0]):
        if all(abs(t - u) >= espaco for u, _ in escolhidos):
            escolhidos.append((t, img))
        if len(escolhidos) == n:
            break
    saida = []
    for t, img in sorted(escolhidos, key=lambda e: e[0]):
        img = img.copy()
        img.thumbnail((lado, lado), Image.LANCZOS)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=82)
        saida.append((round(t, 2), buf.getvalue()))
    return saida


def fala_do_plano(caminho: Path) -> str:
    """O texto dito, na ordem, a partir do ``.plano.json`` da edição."""
    try:
        plano = json.loads(Path(caminho).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return " ".join(str(b.get("texto", "")) for b in plano.get("blocos", [])).strip()


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
    imagens.limpar_antigas()
    saida_base = pasta_saida or pasta_de_saida_padrao()
    videos: dict[str, dict] = {}
    personagens: dict[str, dict] = {}
    audios: dict[str, dict] = {}
    bibliotecas: dict[str, dict] = {}
    gravacoes: dict[str, voz_clonada.Gravacao] = {}
    narracoes: dict[str, dict] = {}
    recortes: dict[tuple[str, float], tuple[np.ndarray, recorte.Recorte]] = {}
    trava_dos_recortes = threading.Lock()
    hosts = {f"127.0.0.1:{porta}", f"localhost:{porta}"}
    origens = {f"http://{h}" for h in hosts}

    @app.middleware("http")
    async def guarda(request: Request, call_next):
        resposta = None
        if request.url.path.startswith("/api/"):
            dado = request.headers.get("x-editor-token") or request.query_params.get("t")
            origem = request.headers.get("origin")
            if request.headers.get("host") not in hosts:
                resposta = JSONResponse({"erro": "endereço não permitido"}, status_code=403)
            elif origem and origem not in origens:
                resposta = JSONResponse({"erro": "origem não permitida"}, status_code=403)
            elif not dado or not secrets.compare_digest(dado, token):
                resposta = JSONResponse({"erro": "token ausente ou inválido"}, status_code=401)
        if resposta is None:
            resposta = await call_next(request)
        for nome, valor in CABECALHOS.items():
            resposta.headers.setdefault(nome, valor)
        return resposta

    def _video(vid: str) -> dict:
        if vid not in videos:
            raise HTTPException(404, "vídeo não encontrado — envie de novo")
        return videos[vid]

    def _personagem(pid: str) -> dict:
        if pid not in personagens:
            raise HTTPException(404, "personagem não encontrado — envie de novo")
        return personagens[pid]

    def _audio(aid: str) -> dict:
        if aid not in audios:
            raise HTTPException(404, "áudio não encontrado — envie de novo")
        return audios[aid]

    def _fundo_da_montagem(m: montagem.Montagem) -> Path:
        """O vídeo de fundo, ou, na biblioteca de cenas, a capa dela (a mesma que a
        thumbnail usa como "Vídeo")."""
        if m.fundo is not None:
            return Path(m.fundo)
        for b in bibliotecas.values():
            if b["pasta"] == Path(m.cenas) and b["capa"]:
                return videos[b["capa"]["id"]]["caminho"]
        return cenas.clipes_da_pasta(Path(m.cenas))[0]

    def _biblioteca(bid: str) -> dict:
        if bid not in bibliotecas:
            raise HTTPException(404, "biblioteca não encontrada — envie a pasta de novo")
        return bibliotecas[bid]

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
            "ia": ia.estado(),
            "recorte": {"baixado": recorte.modelo_baixado(), "tamanho": recorte.TAMANHO},
            "pexels": pexels.estado(),
            "geracao": {"restantes": ia.geracoes_restantes(), "teto": ia.TETO_DE_IMAGENS},
            "presets": presets.para_json(),
            "temas_dos_sons": sons.temas(),
        }

    @app.get("/api/sons/{tema}.wav")
    def ouvir_tema(tema: str, volume: float = 1.0):
        """Os sons de um tema em fila, para ouvir antes de editar."""
        if tema not in sons.temas():
            raise HTTPException(404, "tema de sons desconhecido")
        amostras = sons.demonstracao(tema, video_mod.TAXA, min(1.5, max(0.3, volume)))
        return Response(_wav(amostras, video_mod.TAXA), media_type="audio/wav")

    # ── a chave do Gemini ─────────────────────────────────────────────────
    # A chave entra pela página e nunca volta para ela: o estado só diz o fim dela.

    @app.get("/api/ia")
    def estado_da_ia():
        return ia.estado()

    @app.put("/api/ia/chave")
    def salvar_a_chave(dados: Annotated[dict, Body()]):
        try:
            valor = ia.validar_chave(str(dados.get("chave", "")))
        except ia.ErroDaIA as erro:
            raise HTTPException(422, str(erro)) from erro
        ia.salvar_chave(valor)
        return ia.estado()

    @app.delete("/api/ia/chave")
    def apagar_a_chave():
        ia.apagar_chave()
        return ia.estado()

    # ── as imagens de fundo ───────────────────────────────────────────────

    def _imagem(info: imagens.Imagem) -> dict:
        return {**info.para_dict(), "url": f"/api/imagens/{info.id}"}

    @app.post("/api/imagens")
    def enviar_imagem(arquivo: Annotated[UploadFile, File()]):
        dados = arquivo.file.read(imagens.TETO_BYTES + 1)
        try:
            return _imagem(imagens.guardar(dados, origem="envio"))
        except imagens.ImagemRecusada as erro:
            raise HTTPException(400, f"Não deu para usar essa imagem: {erro}.") from erro

    @app.get("/api/imagens/{iid}")
    def ver_imagem(iid: str):
        caminho = imagens.caminho(iid)
        if caminho is None:
            raise HTTPException(404, "imagem não encontrada")
        return FileResponse(caminho, media_type="image/jpeg",
                            headers={"Cache-Control": "max-age=86400"})

    # ── o Pexels ──────────────────────────────────────────────────────────

    @app.get("/api/pexels")
    def estado_do_pexels():
        return pexels.estado()

    @app.put("/api/pexels/chave")
    def salvar_chave_do_pexels(dados: Annotated[dict, Body()]):
        try:
            valor = pexels.validar_chave(str(dados.get("chave", "")))
        except pexels.ErroDoPexels as erro:
            raise HTTPException(422, str(erro)) from erro
        pexels.salvar_chave(valor)
        return pexels.estado()

    @app.delete("/api/pexels/chave")
    def apagar_chave_do_pexels():
        pexels.apagar_chave()
        return pexels.estado()

    @app.post("/api/pexels/buscar")
    def buscar_no_pexels(dados: Annotated[dict, Body()]):
        try:
            fotos = pexels.buscar(str(dados.get("consulta", "")),
                                  str(dados.get("orientacao", "paisagem")))
        except pexels.ErroDoPexels as erro:
            raise HTTPException(502, str(erro)) from erro
        # Sem os endereços do Pexels: a página pede a prévia ao editor, que baixa.
        return {"fotos": [{k: v for k, v in f.para_dict().items()
                           if k not in ("previa", "grande")} for f in fotos]}

    @app.get("/api/pexels/foto/{fid}")
    def previa_do_pexels(fid: int):
        try:
            dados = pexels.baixar(fid, "previa")
        except pexels.ErroDoPexels as erro:
            raise HTTPException(404, str(erro)) from erro
        return Response(dados, media_type="image/jpeg",
                        headers={"Cache-Control": "max-age=86400"})

    @app.post("/api/pexels/usar")
    def usar_foto_do_pexels(dados: Annotated[dict, Body()]):
        fid = int(dados.get("id", 0) or 0)
        foto = pexels.foto(fid)
        try:
            bruto = pexels.baixar(fid, "grande")
            info = imagens.guardar(bruto, origem="pexels",
                                   credito=f"{foto.autor} / Pexels" if foto else "Pexels")
        except (pexels.ErroDoPexels, imagens.ImagemRecusada) as erro:
            raise HTTPException(502, str(erro)) from erro
        return _imagem(info)

    # ── o fundo gerado (custa dinheiro: só a pedido, com teto) ─────────────

    @app.post("/api/fundo-gerado")
    def gerar_um_fundo(dados: Annotated[dict, Body()]):
        cena = " ".join(str(dados.get("cena", "")).split())
        proporcao = str(dados.get("proporcao", "16:9"))
        lado = str(dados.get("lado", "esquerda"))
        chave_ = hashlib.sha1(f"{cena}|{proporcao}|{lado}".encode()).hexdigest()
        ja_feita = imagens.achar(chave_)
        if ja_feita:
            return {**_imagem(ja_feita), "restantes": ia.geracoes_restantes(), "nova": False}
        try:
            bruto = ia.gerar_fundo(cena, proporcao, lado_do_texto=lado)
            info = imagens.guardar(bruto, origem="gerada", credito=cena, chave=chave_)
        except ia.ErroDaIA as erro:
            raise HTTPException(502, str(erro)) from erro
        except imagens.ImagemRecusada as erro:
            raise HTTPException(502, f"A imagem gerada veio com problema: {erro}") from erro
        return {**_imagem(info), "restantes": ia.geracoes_restantes(), "nova": True}

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
        alfa = video_mod.tem_alfa(destino)
        videos[vid] = {"caminho": destino, "info": info, "nome": destino.name, "tem_alfa": alfa}
        return {"id": vid, "nome": destino.name, "tamanho_bytes": destino.stat().st_size,
                "largura": info.largura, "altura": info.altura, "fps": float(info.fps),
                "duracao": round(info.duracao, 2), "vertical": info.vertical,
                "tem_audio": info.tem_audio, "tem_alfa": alfa}

    # ── a montagem em camadas: o personagem e a narração à parte ──────────

    def _guardar(arquivo: UploadFile, padrao: str) -> tuple[str, Path]:
        uid = uuid.uuid4().hex[:12]
        pasta = envios / uid
        pasta.mkdir(parents=True)
        destino = pasta / _nome_seguro(arquivo.filename or padrao)
        with destino.open("wb") as f:
            shutil.copyfileobj(arquivo.file, f, length=1024 * 1024)
        return uid, destino

    def _carregar_personagem(pid: str, tirar_fundo: bool) -> montagem.Personagem:
        """O personagem lido (guardado em memória: ler um GIF grande leva um tempo)."""
        p = _personagem(pid)
        chave_ = "lido" if tirar_fundo else "lido_com_fundo"
        if chave_ not in p:
            p[chave_] = montagem.ler_personagem(p["caminho"], tirar_fundo=tirar_fundo,
                                                lado_maximo=720)
        return p[chave_]

    @app.post("/api/personagens")
    def enviar_personagem(arquivo: Annotated[UploadFile, File()]):
        pid, destino = _guardar(arquivo, "personagem.gif")
        try:
            lido = montagem.ler_personagem(destino, tirar_fundo=False, lado_maximo=720)
        except montagem.PersonagemInvalido as erro:
            shutil.rmtree(destino.parent, ignore_errors=True)
            raise HTTPException(400, str(erro)) from erro
        personagens[pid] = {"caminho": destino, "nome": destino.name,
                            "tem_alfa": lido.tem_alfa, "lido_com_fundo": lido}
        with Image.open(destino) as im:
            largura, altura = im.size
        return {"id": pid, "nome": destino.name, "tamanho_bytes": destino.stat().st_size,
                "largura": largura, "altura": altura, "quadros": len(lido.quadros),
                "duracao": round(lido.duracao, 2), "tem_alfa": lido.tem_alfa,
                "fundo_de_cor": montagem.cor_do_fundo(lido.quadros[0]) is not None}

    @app.get("/api/personagens/{pid}/quadro.png")
    def quadro_do_personagem(pid: str, tirar_fundo: int = 1, quadro: int = 0):
        lido = _carregar_personagem(pid, bool(tirar_fundo))
        q = lido.quadros[min(max(quadro, 0), len(lido.quadros) - 1)]
        buf = io.BytesIO()
        Image.fromarray(q, "RGBA").save(buf, "PNG")
        return Response(buf.getvalue(), media_type="image/png",
                        headers={"Cache-Control": "max-age=3600"})

    @app.get("/api/personagens/{pid}/arquivo")
    def arquivo_do_personagem(pid: str):
        return FileResponse(_personagem(pid)["caminho"])

    @app.get("/api/personagens/{pid}/recorte")
    def recorte_do_personagem(pid: str, tirar_fundo: int = 1):
        camada = montagem.CamadaDePersonagem(_carregar_personagem(pid, bool(tirar_fundo)))
        return {"ok": True, "pessoa": camada.pessoa.para_dict(), "rosto": camada.rosto.para_dict(),
                "largura": camada.largura, "altura": camada.altura}

    @app.post("/api/audios")
    def enviar_audio(arquivo: Annotated[UploadFile, File()]):
        aid, destino = _guardar(arquivo, "narracao.m4a")
        try:
            duracao = video_mod.duracao_do_audio(destino)
        except Exception as erro:
            shutil.rmtree(destino.parent, ignore_errors=True)
            raise HTTPException(400, "Não achei áudio neste arquivo. Use MP3, WAV ou M4A."
                                ) from erro
        audios[aid] = {"caminho": destino, "nome": destino.name, "duracao": duracao}
        return {"id": aid, "nome": destino.name, "tamanho_bytes": destino.stat().st_size,
                "duracao": round(duracao, 2)}

    # ── "Minha voz": o motor, a leitura gravada, as vozes salvas e a narração ──
    # A gravação e a voz ficam no computador; a narração vira um áudio separado como
    # outro qualquer (com o roteiro ao lado, para a legenda sair com a grafia dele).

    def _voz(erro: voz_clonada.VozInvalida) -> HTTPException:
        return HTTPException(422, str(erro))

    def _gravacao(gid: str) -> voz_clonada.Gravacao:
        if gid not in gravacoes:
            raise HTTPException(404, "Gravação não encontrada: comece a leitura de novo.")
        return gravacoes[gid]

    @app.get("/api/vozes")
    def estado_das_vozes():
        return {"motor": motor_de_voz.estado(), "vozes": voz_clonada.vozes()}

    @app.post("/api/vozes/motor")
    def instalar_o_motor():
        try:
            return motor_de_voz.instalar_em_segundo_plano()
        except motor_de_voz.ErroDoMotor as erro:
            raise HTTPException(409, str(erro)) from erro

    @app.get("/api/vozes/motor")
    def andamento_do_motor():
        return motor_de_voz.estado()

    @app.post("/api/vozes/motor/cancelar")
    def cancelar_o_motor():
        motor_de_voz.cancelar_instalacao()
        return motor_de_voz.estado()

    @app.delete("/api/vozes/motor")
    def desinstalar_o_motor():
        try:
            motor_de_voz.desinstalar()
        except motor_de_voz.ErroDoMotor as erro:
            raise HTTPException(409, str(erro)) from erro
        return motor_de_voz.estado()

    @app.post("/api/vozes/gravacoes")
    def nova_gravacao(dados: Annotated[dict, Body()]):
        gid = uuid.uuid4().hex[:12]
        try:
            g = voz_clonada.Gravacao(str(dados.get("nome", "")), envios / f"voz-{gid}")
        except voz_clonada.VozInvalida as erro:
            raise _voz(erro) from erro
        gravacoes[gid] = g
        return {"id": gid, **g.para_dict()}

    @app.get("/api/vozes/gravacoes/{gid}")
    def ver_gravacao(gid: str):
        return {"id": gid, **_gravacao(gid).para_dict()}

    @app.put("/api/vozes/gravacoes/{gid}/paragrafos/{indice}")
    def gravar_paragrafo(gid: str, indice: int, arquivo: Annotated[UploadFile, File()]):
        """Um parágrafo gravado pelo microfone da página (ou regravado)."""
        g = _gravacao(gid)
        sufixo = Path(_nome_seguro(arquivo.filename or "")).suffix or ".webm"
        destino = g.pasta / f"enviado-{indice + 1:02d}{sufixo}"
        with destino.open("wb") as f:
            shutil.copyfileobj(arquivo.file, f, length=1024 * 1024)
        try:
            g.receber_paragrafo(indice, destino)
        except voz_clonada.VozInvalida as erro:
            raise _voz(erro) from erro
        finally:
            destino.unlink(missing_ok=True)
        return {"id": gid, **g.para_dict()}

    @app.post("/api/vozes/gravacoes/{gid}/leitura")
    def enviar_leitura(gid: str, arquivo: Annotated[UploadFile, File()]):
        """A leitura inteira, gravada fora da página, num arquivo só."""
        g = _gravacao(gid)
        destino = g.pasta / f"enviado{Path(_nome_seguro(arquivo.filename or '')).suffix or '.m4a'}"
        with destino.open("wb") as f:
            shutil.copyfileobj(arquivo.file, f, length=1024 * 1024)
        try:
            g.receber_leitura(destino)
        except voz_clonada.VozInvalida as erro:
            raise _voz(erro) from erro
        finally:
            destino.unlink(missing_ok=True)
        return {"id": gid, **g.para_dict()}

    @app.get("/api/vozes/gravacoes/{gid}/paragrafos/{indice}.wav")
    def ouvir_paragrafo(gid: str, indice: int):
        caminho = _gravacao(gid).wav(indice)
        if not caminho.is_file():
            raise HTTPException(404, "Este parágrafo ainda não foi gravado.")
        return FileResponse(caminho, media_type="audio/wav", headers={"Cache-Control": "no-store"})

    @app.post("/api/vozes/gravacoes/{gid}/salvar")
    def salvar_voz(gid: str):
        try:
            v = voz_clonada.salvar(_gravacao(gid))
        except voz_clonada.VozInvalida as erro:
            raise _voz(erro) from erro
        shutil.rmtree(gravacoes.pop(gid).pasta, ignore_errors=True)
        return v

    @app.delete("/api/vozes/{slug}")
    def apagar_voz(slug: str):
        try:
            voz_clonada.apagar(slug)
        except voz_clonada.VozInvalida as erro:
            raise HTTPException(404, str(erro)) from erro
        return {"vozes": voz_clonada.vozes()}

    @app.get("/api/vozes/{slug}/referencia.wav")
    def ouvir_referencia(slug: str):
        try:
            return FileResponse(voz_clonada.referencia(slug), media_type="audio/wav")
        except voz_clonada.VozInvalida as erro:
            raise HTTPException(404, str(erro)) from erro

    @app.put("/api/vozes/{slug}/pronuncia")
    def salvar_pronuncia(slug: str, dados: Annotated[dict, Body()]):
        try:
            return voz_clonada.salvar_pronuncia(
                slug, voz_clonada.ler_pronuncia(str(dados.get("texto", ""))))
        except voz_clonada.VozInvalida as erro:
            raise HTTPException(404, str(erro)) from erro

    @app.post("/api/vozes/{slug}/narrar")
    def narrar(slug: str, dados: Annotated[dict, Body()]):
        """Narra o roteiro em segundo plano; quando termina, o WAV vira um áudio separado."""
        if any(n["rodando"] for n in narracoes.values()):
            raise HTTPException(409, "Já há uma narração rodando.")
        roteiro = str(dados.get("roteiro") or "")
        try:
            voz_clonada.ler_voz(slug)
            if not roteiro.strip():
                raise voz_clonada.VozInvalida("O roteiro está vazio.")
        except voz_clonada.VozInvalida as erro:
            raise _voz(erro) from erro
        if not motor_de_voz.instalado():
            raise HTTPException(409, "Instale a voz sintetizada primeiro.")
        pronuncia = (voz_clonada.ler_pronuncia(str(dados["pronuncia"]))
                     if dados.get("pronuncia") is not None else None)
        nid = uuid.uuid4().hex[:12]
        estado = {"id": nid, "rodando": True, "feitas": 0, "total": 0, "erro": "",
                  "audio": None, "cancelar": threading.Event()}
        narracoes[nid] = estado

        def andou(feitas: int, total: int) -> None:
            estado.update(feitas=feitas, total=total)

        def rodar() -> None:
            try:
                aid = uuid.uuid4().hex[:12]
                destino = envios / aid / f"narracao-{slug}.wav"
                destino.parent.mkdir(parents=True)
                n = voz_clonada.narrar(slug, roteiro, destino, pronuncia=pronuncia,
                                       progresso=andou, parar=estado["cancelar"].is_set)
                audios[aid] = {"caminho": destino, "nome": destino.name, "duracao": n.segundos}
                estado["audio"] = {"id": aid, "nome": destino.name, "duracao": n.segundos,
                                   "tamanho_bytes": destino.stat().st_size,
                                   "reaproveitados": n.reaproveitados, "aparelho": n.aparelho}
            except (voz_clonada.VozInvalida, motor_de_voz.ErroDoMotor) as erro:
                estado["erro"] = str(erro)
            except Exception as erro:
                logger.exception("a narração não saiu")
                estado["erro"] = f"A narração não saiu: {type(erro).__name__}: {erro}"
            finally:
                estado["rodando"] = False

        threading.Thread(target=rodar, daemon=True, name=f"narrar-{nid}").start()
        return {k: v for k, v in estado.items() if k != "cancelar"}

    @app.get("/api/vozes/narracoes/{nid}")
    def andamento_da_narracao(nid: str):
        if nid not in narracoes:
            raise HTTPException(404, "Narração não encontrada.")
        return {k: v for k, v in narracoes[nid].items() if k != "cancelar"}

    @app.post("/api/vozes/narracoes/{nid}/cancelar")
    def cancelar_narracao(nid: str):
        if nid in narracoes:
            narracoes[nid]["cancelar"].set()
        return {"ok": True}

    @app.get("/api/audios/{aid}/arquivo")
    def ouvir_audio(aid: str):
        return FileResponse(_audio(aid)["caminho"])

    # ── a biblioteca de cenas: a pasta dos clipes e a matriz ──────────────

    def _registrar_video(caminho: Path) -> dict:
        """Um arquivo que já está no computador vira um "vídeo" da página (a capa da
        biblioteca, de onde a thumbnail tira os quadros)."""
        vid = uuid.uuid4().hex[:12]
        info = video_mod.sondar(caminho)
        videos[vid] = {"caminho": caminho, "info": info, "nome": caminho.name, "tem_alfa": False}
        return {"id": vid, "nome": caminho.name, "tamanho_bytes": caminho.stat().st_size,
                "largura": info.largura, "altura": info.altura, "fps": float(info.fps),
                "duracao": round(info.duracao, 2), "vertical": info.vertical,
                "tem_audio": info.tem_audio, "tem_alfa": False}

    @app.post("/api/bibliotecas")
    def nova_biblioteca(dados: Annotated[dict | None, Body()] = None):
        bid = uuid.uuid4().hex[:12]
        pasta = envios / bid / "clipes"
        pasta.mkdir(parents=True)
        nome = Path(_nome_seguro(str((dados or {}).get("nome") or "cenas"))).stem or "cenas"
        bibliotecas[bid] = {"pasta": pasta, "nome": nome, "matriz": None, "capa": None}
        return {"id": bid, "nome": nome}

    @app.post("/api/bibliotecas/{bid}/clipes")
    def enviar_clipe(bid: str, arquivo: Annotated[UploadFile, File()]):
        b = _biblioteca(bid)
        nome = _nome_seguro(arquivo.filename or "")
        if Path(nome).suffix.lower() not in cenas.EXTENSOES:
            raise HTTPException(400, "Na biblioteca entram só vídeos (MP4, MOV, WebM, MKV).")
        with (b["pasta"] / nome).open("wb") as f:
            shutil.copyfileobj(arquivo.file, f, length=1024 * 1024)
        return {"clipes": len(cenas.clipes_da_pasta(b["pasta"]))}

    @app.post("/api/bibliotecas/{bid}/matriz")
    def enviar_matriz(bid: str, arquivo: Annotated[UploadFile, File()]):
        b = _biblioteca(bid)
        dados = arquivo.file.read(MATRIZ_MAXIMA + 1)
        if len(dados) > MATRIZ_MAXIMA:
            raise HTTPException(400, "A matriz passa de 2 MB.")
        try:
            lida = cenas.ler_matriz(dados.decode("utf-8-sig"), cenas.clipes_da_pasta(b["pasta"]))
        except UnicodeDecodeError as erro:
            raise HTTPException(422, "A matriz precisa ser um texto em UTF-8 (o cenas.json)."
                                ) from erro
        except cenas.MatrizInvalida as erro:
            raise HTTPException(422, str(erro)) from erro
        destino = b["pasta"].parent / "matriz.json"
        destino.write_bytes(dados)
        b["matriz"] = destino
        # A capa: uma cena forte, registrada como vídeo, para a thumbnail e as ideias.
        capa = next((c for c in lida.cenas if c.energia == "alta"), lida.cenas[0])
        b["capa"] = _registrar_video(capa.arquivo)
        return {"id": bid, "nome": b["nome"], **lida.ficha(), "capa": b["capa"]}

    # A matriz gerada pelo editor: o Gemini descreve os clipes (em segundo plano, com o
    # andamento), e a página mostra numa tabela para revisar antes de valer.

    @app.post("/api/bibliotecas/{bid}/gerar-matriz")
    def gerar_matriz(bid: str, dados: Annotated[dict | None, Body()] = None):
        b = _biblioteca(bid)
        if (b.get("geracao") or {}).get("rodando"):
            raise HTTPException(409, "A matriz já está sendo gerada.")
        clipes = [(c, c.name) for c in cenas.clipes_da_pasta(b["pasta"])]
        if not clipes:
            raise HTTPException(422, "A pasta não tem clipes para descrever.")
        assunto = re.sub(r"\s+", " ", str((dados or {}).get("assunto") or "")).strip()[:200]
        estado = {"rodando": True, "prontas": 0, "total": len(clipes), "pedidos": 0,
                  "por": "", "aviso": "", "erro": "", "cenas": None}
        b["geracao"] = estado

        def andou(prontas: int, total: int, pedidos: int) -> None:
            estado.update(prontas=prontas, total=total, pedidos=pedidos)

        def rodar() -> None:
            try:
                g = catalogo.gerar(clipes, assunto=assunto, progresso=andou)
                estado.update(cenas=g.cenas, por=g.por, aviso=g.aviso, pedidos=g.pedidos)
            except Exception as erro:
                logger.exception("a matriz não saiu")
                estado["erro"] = f"A matriz não saiu: {erro}"
            finally:
                estado["rodando"] = False

        threading.Thread(target=rodar, daemon=True).start()
        return {k: v for k, v in estado.items() if k != "cenas"}

    @app.get("/api/bibliotecas/{bid}/gerar-matriz")
    def andamento_da_matriz(bid: str):
        estado = _biblioteca(bid).get("geracao")
        if estado is None:
            raise HTTPException(404, "Nenhuma matriz foi pedida para esta biblioteca.")
        return dict(estado)

    @app.get("/api/bibliotecas/{bid}/matriz")
    def matriz_atual(bid: str):
        """A matriz em uso, para a tabela de revisão."""
        b = _biblioteca(bid)
        if b["matriz"] is None:
            raise HTTPException(404, "Esta biblioteca ainda não tem matriz.")
        dados = json.loads(Path(b["matriz"]).read_text(encoding="utf-8-sig"))
        return {"cenas": dados.get("cenas") if isinstance(dados, dict) else dados}

    @app.get("/api/bibliotecas/{bid}/quadro")
    def quadro_da_cena(bid: str, arquivo: str, segundo: float | None = None,
                       largura: int = 240):
        """Um quadro de uma cena da biblioteca (o do meio, se o instante não vier)."""
        b = _biblioteca(bid)
        caminho = b["pasta"] / Path(arquivo.replace("\\", "/")).name
        if not caminho.is_file():
            raise HTTPException(404, "Esta cena não está na pasta enviada.")
        info = video_mod.sondar(caminho)
        t = info.duracao / 2 if segundo is None else min(max(0.0, segundo), info.duracao)
        matriz = video_mod.quadro_em(caminho, t, info.rotacao)
        if matriz is None:
            raise HTTPException(404, "Não deu para ler um quadro desta cena.")
        img = Image.fromarray(matriz)
        largura = max(80, min(640, largura))
        img.thumbnail((largura, largura), Image.LANCZOS)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=80)
        return Response(buf.getvalue(), media_type="image/jpeg",
                        headers={"Cache-Control": "max-age=3600"})

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

    # ── o recorte da pessoa ───────────────────────────────────────────────

    def _recorte(vid: str, segundo: float) -> tuple[np.ndarray, recorte.Recorte]:
        v = _video(vid)
        chave_ = (vid, round(segundo, 2))
        with trava_dos_recortes:
            if chave_ in recortes:
                recortes[chave_] = recortes.pop(chave_)          # o mais recente no fim
                return recortes[chave_]
        matriz = video_mod.quadro_em(v["caminho"], segundo, v["info"].rotacao,
                                     alfa=v.get("tem_alfa", False))
        if matriz is None:
            raise HTTPException(404, "sem quadro nesse instante")
        if matriz.shape[2] == 4:
            # O vídeo já vem sem fundo: o alfa do próprio arquivo, sem modelo nenhum.
            alfa = matriz[..., 3].astype(np.float32) / 255.0
            matriz = np.ascontiguousarray(matriz[..., :3])
            r = recorte.Recorte((np.clip(alfa, 0, 1) * 255).astype(np.uint8),
                                *recorte.caixas(alfa))
            with trava_dos_recortes:
                recortes[chave_] = (matriz, r)
                while len(recortes) > RECORTES_GUARDADOS:
                    recortes.pop(next(iter(recortes)))
            return matriz, r
        try:
            r = recorte.recortar(matriz)
        except Exception as erro:
            logger.warning("o recorte falhou: %s", erro)
            raise HTTPException(503, "Não consegui recortar a pessoa. Na primeira vez o "
                                f"editor baixa o modelo de recorte ({recorte.TAMANHO}): "
                                "confira a internet.") from erro
        r.alfa = (np.clip(r.alfa, 0, 1) * 255).astype(np.uint8)    # guardado em 1 byte
        with trava_dos_recortes:
            recortes[chave_] = (matriz, r)
            while len(recortes) > RECORTES_GUARDADOS:
                recortes.pop(next(iter(recortes)))
        return matriz, r

    @app.get("/api/videos/{vid}/recorte")
    def recorte_info(vid: str, segundo: float = 0.0):
        _matriz, r = _recorte(vid, segundo)
        return {"ok": r.ok, "pessoa": r.pessoa.para_dict() if r.pessoa else None,
                "rosto": r.rosto.para_dict() if r.rosto else None}

    @app.get("/api/videos/{vid}/recorte.png")
    def recorte_png(vid: str, segundo: float = 0.0, largura: int = 1280):
        matriz, r = _recorte(vid, segundo)
        dados = recorte.png(matriz, r.alfa.astype(np.float32) / 255.0, largura)
        return Response(dados, media_type="image/png",
                        headers={"Cache-Control": "max-age=3600"})

    def _montagem(pedido: dict) -> tuple[montagem.Montagem, Path, str]:
        """A montagem pedida pela página, o vídeo da thumbnail e o nome da saída."""
        fundo = biblioteca = None
        if pedido.get("biblioteca_id"):
            biblioteca = _biblioteca(str(pedido["biblioteca_id"]))
            if biblioteca["matriz"] is None:
                raise HTTPException(422, "Envie a matriz da biblioteca (o cenas.json).")
        else:
            fundo = _video(str(pedido.get("fundo_id", "")))
        pessoa = personagem = None
        if pedido.get("pessoa_id"):
            pessoa = _video(str(pedido["pessoa_id"]))
        if pedido.get("personagem_id"):
            personagem = _personagem(str(pedido["personagem_id"]))
        ids_de_audio = pedido.get("audio_ids") or (
            [pedido["audio_id"]] if pedido.get("audio_id") else [])
        partes = [_audio(str(a))["caminho"] for a in list(ids_de_audio)[:PARTES_MAXIMAS]]
        recorte_ = str(pedido.get("recorte") or "modnet")
        if pessoa is not None and recorte_ == "transparente" and not pessoa.get("tem_alfa"):
            raise HTTPException(422, "Este vídeo da pessoa não tem transparência: escolha "
                                     "recortar com o MODNet.")
        m = montagem.Montagem(
            fundo["caminho"] if fundo else None, pessoa=pessoa["caminho"] if pessoa else None,
            personagem=personagem["caminho"] if personagem else None,
            audios=tuple(partes), recorte=recorte_,
            cenas=biblioteca["pasta"] if biblioteca else None,
            matriz=biblioteca["matriz"] if biblioteca else None,
            formato=str(pedido.get("formato") or "fundo"),
            tirar_fundo_do_personagem=bool(pedido.get("tirar_fundo_do_personagem", True)),
            fala=str(pedido["fala"]) if pedido.get("fala") else None)
        erros = m.problemas()
        if erros:
            raise HTTPException(422, "; ".join(erros))
        if biblioteca is not None:
            capa = videos[biblioteca["capa"]["id"]]
            return m, (pessoa or capa)["caminho"], f"{biblioteca['nome']}.mp4"
        return m, (pessoa or fundo)["caminho"], fundo["nome"]

    @app.post("/api/tarefas")
    async def criar_tarefa(request: Request):
        dados = await request.json()
        m = None
        if dados.get("montagem"):
            m, video_da_thumb, nome = _montagem(dados["montagem"])
        else:
            v = _video(str(dados.get("video_id", "")))
            video_da_thumb, nome = v["caminho"], v["nome"]
        edicao = OpcoesDeEdicao.de_dict(dados.get("edicao") or {})
        saida = saida_mod.OpcoesDeSaida.de_dict(dados.get("saida") or {})
        erros = edicao.problemas() + saida.problemas()
        if erros:
            raise HTTPException(422, "; ".join(erros))
        previa = dados.get("previa_s")
        saida_base.mkdir(parents=True, exist_ok=True)
        destino = _livre(saida_base / f"{Path(nome).stem}-editado.{saida.formato}")
        try:
            t = gerente.iniciar(Tarefa(video_da_thumb, destino, edicao, saida,
                                       float(previa) if previa else None, montagem=m))
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

    # ── as thumbnails ─────────────────────────────────────────────────────
    # Salvas na pasta de saída, em PNG e em JPG de até 2 MB. Só as salvas nesta sessão
    # podem ser baixadas pela página.
    thumbnails: dict[str, Path] = {}

    def _gravar_thumbnail(imagem: UploadFile, base: Path, tamanho: str) -> dict:
        """``<base>-thumb-<tamanho>.png`` e ``.jpg``, ao lado de ``base``."""
        if not re.fullmatch(r"[0-9]{2,4}x[0-9]{2,4}", tamanho):
            raise HTTPException(422, "nome da thumbnail inválido")
        try:
            img = Image.open(imagem.file).convert("RGB")
        except (OSError, ValueError) as erro:
            raise HTTPException(422, "a thumbnail não é uma imagem") from erro
        png = base.with_name(f"{base.stem}-thumb-{tamanho}.png")
        png.parent.mkdir(parents=True, exist_ok=True)
        img.save(png, "PNG", optimize=True)
        jpg = png.with_suffix(".jpg")
        for qualidade in (92, 85, 78, 70, 60):
            img.save(jpg, "JPEG", quality=qualidade, optimize=True)
            if jpg.stat().st_size <= JPG_MAXIMO:
                break
        for c in (png, jpg):
            thumbnails[c.name] = c
        return {"png": png.name, "jpg": jpg.name, "jpg_bytes": jpg.stat().st_size}

    def _no_resultado(t: Tarefa, gravada: dict) -> None:
        lista = t.resultado.setdefault("thumbnails", [])
        for nome in (gravada["png"], gravada["jpg"]):
            caminho = str(thumbnails[nome])
            if caminho not in lista:
                lista.append(caminho)

    @app.post("/api/tarefas/{tid}/thumbnail")
    def salvar_thumbnail(tid: str, imagem: Annotated[UploadFile, File()],
                         nome: Annotated[str, Form()]):
        t = _tarefa(tid)
        if t.estado != "pronto" or not t.resultado:
            raise HTTPException(409, "a edição ainda não terminou")
        gravada = _gravar_thumbnail(imagem, Path(t.resultado["video"]), nome)
        _no_resultado(t, gravada)
        return gravada

    @app.post("/api/thumbnails")
    def salvar_thumbnail_do_passo(imagem: Annotated[UploadFile, File()],
                                  tamanho: Annotated[str, Form()],
                                  video_id: Annotated[str, Form()],
                                  tarefa_id: Annotated[str, Form()] = ""):
        """O botão "Baixar" do passo 5. Depois da edição, a thumbnail leva o nome do vídeo
        editado e entra no resultado; antes, leva o nome do vídeo enviado."""
        t = gerente.tarefas.get(tarefa_id) if tarefa_id else None
        if t is not None and t.estado == "pronto" and t.resultado:
            gravada = _gravar_thumbnail(imagem, Path(t.resultado["video"]), tamanho)
            _no_resultado(t, gravada)
            return gravada
        v = _video(video_id)
        return _gravar_thumbnail(imagem, saida_base / Path(v["nome"]).name, tamanho)

    @app.get("/api/thumbnails/{nome}")
    def baixar_thumbnail(nome: str, inline: int = 0):
        caminho = thumbnails.get(nome)
        if caminho is None or not caminho.is_file():
            raise HTTPException(404, "thumbnail não encontrada")
        return FileResponse(caminho) if inline else FileResponse(caminho, filename=caminho.name)

    # ── as ideias do Gemini ───────────────────────────────────────────────

    @app.post("/api/tarefas/{tid}/thumbs-ia")
    def thumbs_ia(tid: str, dados: Annotated[dict | None, Body()] = None):
        t = _tarefa(tid)
        if t.estado != "pronto" or not t.resultado:
            raise HTTPException(409, "a edição ainda não terminou")
        evitar = [str(c)[:60] for c in (dados or {}).get("evitar", [])][:12]
        plataformas = [str(x) for x in (dados or {}).get("plataformas", [])
                       if str(x) in ia.PLATAFORMAS]
        m = t.montagem
        origens = None
        if m is None:
            info = video_mod.sondar(t.video)
            quadros = quadros_candidatos(t.video, info)
            duracao, vertical = info.duracao, info.vertical
        else:
            # Na montagem, os quadros vêm das duas camadas: 4 da pessoa e 4 do fundo (com
            # o personagem, que não está em vídeo nenhum, os 8 são do fundo).
            fundo_ = _fundo_da_montagem(m)
            info_do_fundo = video_mod.sondar(fundo_)
            da_pessoa = []
            if m.pessoa is not None:
                da_pessoa = quadros_candidatos(m.pessoa, video_mod.sondar(m.pessoa), n=4,
                                               alfa=m.recorte == "transparente")
            do_fundo = quadros_candidatos(fundo_, info_do_fundo,
                                          n=ia.QUADROS - len(da_pessoa))
            quadros = da_pessoa + do_fundo
            origens = ["pessoa"] * len(da_pessoa) + ["fundo"] * len(do_fundo)
            duracao = float(t.resultado.get("duracao_original") or info_do_fundo.duracao)
            vertical = int(t.resultado.get("altura", 0)) > int(t.resultado.get("largura", 0))
        try:
            return ia.sugerir(fala_do_plano(Path(t.resultado["plano"])), quadros,
                              idioma=t.edicao.idioma, duracao=duracao,
                              vertical=vertical, nomes_de_icones=icones.nomes(),
                              evitar=evitar, origens=origens, plataformas=plataformas)
        except ia.ErroDaIA as erro:
            raise HTTPException(502, str(erro)) from erro

    @app.post("/api/abrir-pasta")
    def abrir_a_pasta():
        saida_base.mkdir(parents=True, exist_ok=True)
        abrir_pasta(saida_base)
        return {"ok": True}

    @app.get("/api/icones")
    def lista_de_icones():
        return {nome: icones.caminhos(nome) for nome in icones.nomes()}

    @app.get("/maos/{nome}")
    def mao(nome: str):
        if nome not in MAOS:
            raise HTTPException(404, "mão não encontrada")
        dados = (files("editor") / "recursos" / "maos" / nome).read_bytes()
        tipo = "image/png" if nome.endswith(".png") else "image/svg+xml"
        return Response(dados, media_type=tipo, headers={"Cache-Control": "max-age=86400"})

    @app.get("/fontes/{nome}")
    def fonte(nome: str):
        if nome not in FONTES:
            raise HTTPException(404, "fonte não encontrada")
        dados = (files("editor") / "recursos" / nome).read_bytes()
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


__all__ = ["abrir", "abrir_pasta", "criar_app", "fala_do_plano", "nitidez",
           "quadros_candidatos"]
