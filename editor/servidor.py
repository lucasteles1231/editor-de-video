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
    ia,
    icones,
    imagens,
    montagem,
    pexels,
    presets,
    recorte,
    sons,
    transcricao,
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
    recortes: dict[tuple[str, float], tuple[np.ndarray, recorte.Recorte]] = {}
    trava_dos_recortes = threading.Lock()
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

    def _personagem(pid: str) -> dict:
        if pid not in personagens:
            raise HTTPException(404, "personagem não encontrado — envie de novo")
        return personagens[pid]

    def _audio(aid: str) -> dict:
        if aid not in audios:
            raise HTTPException(404, "áudio não encontrado — envie de novo")
        return audios[aid]

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
        fundo = _video(str(pedido.get("fundo_id", "")))
        pessoa = personagem = audio = None
        if pedido.get("pessoa_id"):
            pessoa = _video(str(pedido["pessoa_id"]))
        if pedido.get("personagem_id"):
            personagem = _personagem(str(pedido["personagem_id"]))
        if pedido.get("audio_id"):
            audio = _audio(str(pedido["audio_id"]))
        recorte_ = str(pedido.get("recorte") or "modnet")
        if pessoa is not None and recorte_ == "transparente" and not pessoa.get("tem_alfa"):
            raise HTTPException(422, "Este vídeo da pessoa não tem transparência: escolha "
                                     "recortar com o MODNet.")
        m = montagem.Montagem(
            fundo["caminho"], pessoa=pessoa["caminho"] if pessoa else None,
            personagem=personagem["caminho"] if personagem else None,
            audio=audio["caminho"] if audio else None, recorte=recorte_,
            formato=str(pedido.get("formato") or "fundo"),
            tirar_fundo_do_personagem=bool(pedido.get("tirar_fundo_do_personagem", True)),
            fala=str(pedido["fala"]) if pedido.get("fala") else None)
        erros = m.problemas()
        if erros:
            raise HTTPException(422, "; ".join(erros))
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

    # ── as ideias do Gemini ───────────────────────────────────────────────

    @app.post("/api/tarefas/{tid}/thumbs-ia")
    def thumbs_ia(tid: str, dados: Annotated[dict | None, Body()] = None):
        t = _tarefa(tid)
        if t.estado != "pronto" or not t.resultado:
            raise HTTPException(409, "a edição ainda não terminou")
        evitar = [str(c)[:60] for c in (dados or {}).get("evitar", [])][:12]
        m = t.montagem
        origens = None
        if m is None:
            info = video_mod.sondar(t.video)
            quadros = quadros_candidatos(t.video, info)
            duracao, vertical = info.duracao, info.vertical
        else:
            # Na montagem, os quadros vêm das duas camadas: 4 da pessoa e 4 do fundo (com
            # o personagem, que não está em vídeo nenhum, os 8 são do fundo).
            info_do_fundo = video_mod.sondar(m.fundo)
            da_pessoa = []
            if m.pessoa is not None:
                da_pessoa = quadros_candidatos(m.pessoa, video_mod.sondar(m.pessoa), n=4,
                                               alfa=m.recorte == "transparente")
            do_fundo = quadros_candidatos(m.fundo, info_do_fundo,
                                          n=ia.QUADROS - len(da_pessoa))
            quadros = da_pessoa + do_fundo
            origens = ["pessoa"] * len(da_pessoa) + ["fundo"] * len(do_fundo)
            duracao = float(t.resultado.get("duracao_original") or info_do_fundo.duracao)
            vertical = int(t.resultado.get("altura", 0)) > int(t.resultado.get("largura", 0))
        try:
            return ia.sugerir(fala_do_plano(Path(t.resultado["plano"])), quadros,
                              idioma=t.edicao.idioma, duracao=duracao,
                              vertical=vertical, nomes_de_icones=icones.nomes(),
                              evitar=evitar, origens=origens)
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
