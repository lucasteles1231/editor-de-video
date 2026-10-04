"""
Fotos do Pexels para o fundo da thumbnail — opcional, com a chave grátis de quem usa.

**Só a busca sai do computador.** O servidor faz a busca, baixa a foto escolhida e a
serve para a página, que continua falando só com o próprio editor.

As fotos do Pexels são de uso livre, sem crédito obrigatório. As regras da API pedem um
link para o Pexels e o nome do fotógrafo junto das fotos, e a página mostra os dois.

Para testes há um Pexels falso, ligado por ``EDITOR_PEXELS=falso``: fotos de gradiente
desenhadas aqui mesmo, sem rede.
"""
from __future__ import annotations

import hashlib
import io
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

API = "https://api.pexels.com/v1"
ONDE_PEGAR_A_CHAVE = "https://www.pexels.com/api/"
NOME_DA_CHAVE = "pexels_api_key"
VARIAVEL_DA_CHAVE = "PEXELS_API_KEY"
VARIAVEL_FALSA = "EDITOR_PEXELS"
POR_PAGINA = 12
ORIENTACOES = {"paisagem": "landscape", "retrato": "portrait", "quadrado": "square"}


class ErroDoPexels(RuntimeError):
    """Um problema que a página mostra como está — a mensagem já é para quem usa."""


@dataclass
class Foto:
    id: int
    largura: int
    altura: int
    autor: str
    autor_url: str
    pagina: str
    alt: str
    #: As URLs no Pexels: a pequena (para a grade) e a grande (para a thumbnail).
    previa: str
    grande: str

    def para_dict(self) -> dict:
        return asdict(self)


#: As fotos das últimas buscas, para baixar pelo id sem buscar de novo.
_vistas: dict[int, Foto] = {}


def _falso() -> bool:
    return os.environ.get(VARIAVEL_FALSA, "").strip().lower() == "falso"


def estado() -> dict:
    if _falso():
        return {"configurada": True, "origem": "falsa", "final": "…test"}
    from editor import chaves

    return chaves.estado(NOME_DA_CHAVE, VARIAVEL_DA_CHAVE)


def chave() -> str:
    from editor import chaves

    return chaves.ler(NOME_DA_CHAVE, VARIAVEL_DA_CHAVE)[0]


def salvar_chave(valor: str) -> None:
    from editor import chaves

    chaves.salvar(NOME_DA_CHAVE, valor)


def apagar_chave() -> None:
    from editor import chaves

    chaves.apagar(NOME_DA_CHAVE)


def _cliente(transporte=None, timeout: float = 30.0):
    import httpx

    return httpx.Client(transport=transporte, timeout=timeout, follow_redirects=True)


def _pedir(caminho: str, params: dict, chave_: str, transporte=None) -> dict:
    import httpx

    try:
        with _cliente(transporte) as cliente:
            r = cliente.get(f"{API}{caminho}", params=params,
                            headers={"Authorization": chave_})
    except httpx.HTTPError as erro:
        raise ErroDoPexels("Não consegui falar com o Pexels. Confira a internet e tente "
                           "de novo.") from erro
    if r.status_code in (401, 403):
        raise ErroDoPexels("O Pexels recusou a chave. Confira se copiou inteira, ou pegue "
                           f"a sua em {ONDE_PEGAR_A_CHAVE}")
    if r.status_code == 429:
        raise ErroDoPexels("O Pexels limita as buscas por hora (200 na chave grátis). "
                           "Espere um pouco e tente de novo.")
    if r.status_code >= 400:
        raise ErroDoPexels(f"O Pexels respondeu {r.status_code}. Tente de novo.")
    return r.json()


def validar_chave(valor: str, *, transporte=None) -> str:
    """Confere a chave com uma busca de uma foto e devolve ela limpa."""
    from editor import chaves

    valor = chaves.limpar(valor)
    if not chaves.parece_chave(valor):
        raise ErroDoPexels("Isso não parece uma chave do Pexels: ela é uma sequência longa, "
                           f"sem espaços. Pegue a sua em {ONDE_PEGAR_A_CHAVE}")
    _pedir("/search", {"query": "nature", "per_page": 1}, valor, transporte)
    return valor


def _foto(dados: dict) -> Foto:
    src = dados.get("src") or {}
    return Foto(id=int(dados["id"]), largura=int(dados.get("width") or 0),
                altura=int(dados.get("height") or 0),
                autor=str(dados.get("photographer") or ""),
                autor_url=str(dados.get("photographer_url") or ""),
                pagina=str(dados.get("url") or ""), alt=str(dados.get("alt") or "")[:160],
                previa=str(src.get("medium") or ""), grande=str(src.get("large2x") or ""))


def _falsas(consulta: str) -> list[Foto]:
    base = int(hashlib.sha1(consulta.encode()).hexdigest()[:6], 16)
    return [Foto(id=base + i, largura=1600, altura=900, autor=f"Fotógrafo {i + 1}",
                 autor_url="", pagina="", alt=f"{consulta} {i + 1}", previa="falso://",
                 grande="falso://") for i in range(6)]


def buscar(consulta: str, orientacao: str = "paisagem", *, transporte=None) -> list[Foto]:
    """As fotos para uma busca (no idioma da fala; o Pexels entende português)."""
    consulta = " ".join((consulta or "").split())[:80]
    if not consulta:
        raise ErroDoPexels("Escreva o que buscar.")
    if _falso():
        fotos = _falsas(consulta)
    else:
        valor = chave()
        if not valor:
            raise ErroDoPexels(f"Falta a chave do Pexels: pegue a sua em {ONDE_PEGAR_A_CHAVE}")
        dados = _pedir("/search", {"query": consulta, "per_page": POR_PAGINA,
                                   "orientation": ORIENTACOES.get(orientacao, "landscape"),
                                   "locale": "pt-BR"}, valor, transporte)
        fotos = [_foto(f) for f in dados.get("photos", []) if f.get("id")]
    for f in fotos:
        _vistas[f.id] = f
    return fotos


def foto(foto_id: int) -> Foto | None:
    return _vistas.get(foto_id)


def _gradiente(semente: int, largura: int, altura: int) -> bytes:
    from PIL import Image

    cor = ((semente * 73) % 200 + 30, (semente * 151) % 200 + 30, (semente * 37) % 200 + 30)
    img = Image.linear_gradient("L").resize((largura, altura)).convert("RGB")
    img = Image.blend(img, Image.new("RGB", (largura, altura), cor), 0.6)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def _pasta_do_cache() -> Path:
    from platformdirs import user_cache_dir

    destino = Path(user_cache_dir("editor-de-video", appauthor=False)) / "pexels"
    destino.mkdir(parents=True, exist_ok=True)
    return destino


def baixar(foto_id: int, tamanho: str = "previa", *, transporte=None) -> bytes:
    """Os bytes da foto (``previa`` ou ``grande``), guardados para não baixar duas vezes."""
    import httpx

    f = foto(foto_id)
    if f is None:
        raise ErroDoPexels("Essa foto não está mais na lista; busque de novo.")
    if _falso():
        return _gradiente(foto_id, 320 if tamanho == "previa" else 1600,
                          180 if tamanho == "previa" else 900)
    arquivo = _pasta_do_cache() / f"{foto_id}-{tamanho}.jpg"
    if arquivo.is_file():
        return arquivo.read_bytes()
    url = f.previa if tamanho == "previa" else f.grande
    if not url.startswith("https://images.pexels.com/"):
        raise ErroDoPexels("Essa foto veio sem endereço do Pexels.")
    try:
        with _cliente(transporte, timeout=60) as cliente:
            r = cliente.get(url)
    except httpx.HTTPError as erro:
        raise ErroDoPexels("Não consegui baixar a foto do Pexels.") from erro
    if r.status_code >= 400:
        raise ErroDoPexels(f"O Pexels respondeu {r.status_code} ao baixar a foto.")
    arquivo.write_bytes(r.content)
    return r.content


__all__ = ["ErroDoPexels", "Foto", "apagar_chave", "baixar", "buscar", "chave", "estado",
           "foto", "salvar_chave", "validar_chave"]
