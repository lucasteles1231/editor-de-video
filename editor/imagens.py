"""
As imagens de fundo da thumbnail: as que a pessoa envia, as do Pexels e as geradas.

Todas passam pelo Pillow antes de ficar: ele confere que é imagem de verdade e a imagem é
gravada de novo, o que tira os metadados (a foto de celular traz o lugar em que foi tirada).
Ficam na pasta de cache do editor, com o mesmo arquivo para o mesmo conteúdo.
"""
from __future__ import annotations

import hashlib
import io
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image, ImageOps

#: O maior arquivo aceito, e o maior lado guardado (uma thumbnail tem no máximo 1920).
TETO_BYTES = 20 * 1024 * 1024
LADO_MAXIMO = 3840
FORMATOS = {"JPEG", "PNG", "WEBP", "GIF", "BMP"}
#: Imagens mais velhas que isto são apagadas quando a interface abre.
GUARDAR_S = 14 * 24 * 3600


class ImagemRecusada(ValueError):
    """O arquivo não serve como fundo; a mensagem é para quem enviou."""


@dataclass
class Imagem:
    id: str
    largura: int
    altura: int
    #: "envio", "pexels" ou "gerada".
    origem: str
    #: O crédito a mostrar (a foto do Pexels tem fotógrafo; a gerada, a descrição).
    credito: str = ""
    #: Para não gerar (e pagar) duas vezes a mesma imagem.
    chave: str = ""

    def para_dict(self) -> dict:
        return asdict(self)


def pasta() -> Path:
    from platformdirs import user_cache_dir

    destino = Path(user_cache_dir("editor-de-video", appauthor=False)) / "imagens"
    destino.mkdir(parents=True, exist_ok=True)
    return destino


def _abrir(dados: bytes) -> Image.Image:
    if len(dados) > TETO_BYTES:
        raise ImagemRecusada(f"a imagem tem {len(dados) / 1e6:.0f} MB; o teto é "
                             f"{TETO_BYTES // (1024 * 1024)} MB")
    try:
        img = Image.open(io.BytesIO(dados))
        img.load()
    except Exception as erro:
        raise ImagemRecusada("isso não é uma imagem que eu consiga abrir (use JPG, PNG "
                             "ou WebP)") from erro
    if img.format not in FORMATOS:
        raise ImagemRecusada(f"o formato {img.format} não é aceito (use JPG, PNG ou WebP)")
    return img


def guardar(dados: bytes, *, origem: str, credito: str = "", chave: str = "") -> Imagem:
    """Confere, limpa e guarda a imagem. Levanta :class:`ImagemRecusada`."""
    img = _abrir(dados)
    img = ImageOps.exif_transpose(img)          # a foto de celular deitada, de pé
    if img.mode in ("RGBA", "LA", "P"):
        fundo = Image.new("RGB", img.size, (26, 26, 26))
        img = img.convert("RGBA")
        fundo.paste(img, mask=img.getchannel("A"))
        img = fundo
    else:
        img = img.convert("RGB")
    if max(img.size) > LADO_MAXIMO:
        img.thumbnail((LADO_MAXIMO, LADO_MAXIMO), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92, optimize=True)
    limpo = buf.getvalue()
    iid = hashlib.sha1(limpo).hexdigest()[:16]
    destino = pasta()
    (destino / f"{iid}.jpg").write_bytes(limpo)
    info = Imagem(iid, img.width, img.height, origem, credito[:200], chave)
    (destino / f"{iid}.json").write_text(json.dumps(info.para_dict(), ensure_ascii=False),
                                         encoding="utf-8")
    return info


def caminho(iid: str) -> Path | None:
    if not iid.isalnum() or len(iid) != 16:
        return None
    arquivo = pasta() / f"{iid}.jpg"
    return arquivo if arquivo.is_file() else None


def abrir(iid: str) -> Imagem | None:
    if caminho(iid) is None:
        return None
    try:
        return Imagem(**json.loads((pasta() / f"{iid}.json").read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return None


def achar(chave: str) -> Imagem | None:
    """Uma imagem já guardada com esta chave (uma geração que já foi paga)."""
    if not chave:
        return None
    for meta in pasta().glob("*.json"):
        try:
            dados = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if dados.get("chave") == chave and caminho(dados.get("id", "")):
            return Imagem(**dados)
    return None


def limpar_antigas() -> None:
    """Apaga as imagens velhas — menos as geradas, que foram pagas: apagar uma seria
    pagar de novo pelo mesmo pedido."""
    agora = time.time()
    for meta in pasta().glob("*.json"):
        try:
            if agora - meta.stat().st_mtime <= GUARDAR_S:
                continue
            if json.loads(meta.read_text(encoding="utf-8")).get("origem") == "gerada":
                continue
        except (OSError, ValueError):
            continue
        meta.with_suffix(".jpg").unlink(missing_ok=True)
        meta.unlink(missing_ok=True)


__all__ = ["TETO_BYTES", "Imagem", "ImagemRecusada", "abrir", "achar", "caminho", "guardar",
           "limpar_antigas", "pasta"]
