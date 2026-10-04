"""O Pexels, sem rede: a API é um transporte falso do httpx."""
from __future__ import annotations

import httpx
import pytest

from editor import pexels

CHAVE = "chave-do-pexels-de-mentira-1234567890"


@pytest.fixture
def de_verdade(monkeypatch):
    monkeypatch.delenv(pexels.VARIAVEL_FALSA, raising=False)
    monkeypatch.setenv(pexels.VARIAVEL_DA_CHAVE, CHAVE)


def _foto(i: int) -> dict:
    return {"id": i, "width": 4000, "height": 2250, "url": f"https://www.pexels.com/photo/{i}/",
            "photographer": f"Fotógrafa {i}", "photographer_url": "https://www.pexels.com/@f",
            "alt": "um estúdio", "src": {
                "medium": f"https://images.pexels.com/photos/{i}/m.jpeg",
                "large2x": f"https://images.pexels.com/photos/{i}/g.jpeg"}}


class _Pexels:
    def __init__(self, *respostas: httpx.Response):
        self.fila = list(respostas)
        self.pedidos: list[httpx.Request] = []

    def __call__(self, pedido: httpx.Request) -> httpx.Response:
        self.pedidos.append(pedido)
        return self.fila.pop(0)

    @property
    def transporte(self):
        return httpx.MockTransport(self)


def test_busca(de_verdade):
    api = _Pexels(httpx.Response(200, json={"photos": [_foto(1), _foto(2)]}))
    fotos = pexels.buscar("estúdio de vídeo", "retrato", transporte=api.transporte)
    assert [f.id for f in fotos] == [1, 2] and fotos[0].autor == "Fotógrafa 1"
    pedido = api.pedidos[0]
    # a chave vai no cabeçalho, nunca na URL
    assert pedido.headers["Authorization"] == CHAVE and CHAVE not in str(pedido.url)
    params = dict(pedido.url.params)
    assert params["query"] == "estúdio de vídeo" and params["orientation"] == "portrait"
    assert params["locale"] == "pt-BR" and params["per_page"] == str(pexels.POR_PAGINA)


@pytest.mark.parametrize(("status", "trecho"), [(401, "recusou a chave"), (429, "por hora")])
def test_erros(de_verdade, status, trecho):
    api = _Pexels(httpx.Response(status, json={}))
    with pytest.raises(pexels.ErroDoPexels, match=trecho):
        pexels.buscar("praia", transporte=api.transporte)


def test_baixa_uma_vez_so(de_verdade):
    api = _Pexels(httpx.Response(200, json={"photos": [_foto(7)]}),
                  httpx.Response(200, content=b"\xff\xd8jpeg"))
    pexels.buscar("praia", transporte=api.transporte)
    assert pexels.baixar(7, "grande", transporte=api.transporte) == b"\xff\xd8jpeg"
    assert str(api.pedidos[1].url).endswith("/g.jpeg")
    # a segunda vez vem do disco: a fila está vazia e nada é pedido
    assert pexels.baixar(7, "grande", transporte=api.transporte) == b"\xff\xd8jpeg"
    assert len(api.pedidos) == 2


def test_so_baixa_do_pexels(de_verdade):
    """O endereço vem da resposta da API, mas o servidor só baixa do CDN do Pexels."""
    falsa = _foto(9)
    falsa["src"]["large2x"] = "http://127.0.0.1:22/segredo"
    api = _Pexels(httpx.Response(200, json={"photos": [falsa]}))
    pexels.buscar("praia", transporte=api.transporte)
    with pytest.raises(pexels.ErroDoPexels, match="sem endereço do Pexels"):
        pexels.baixar(9, "grande", transporte=api.transporte)


def test_validar_chave():
    ok = httpx.MockTransport(lambda r: httpx.Response(200, json={"photos": []}))
    assert pexels.validar_chave(f'PEXELS_API_KEY="{CHAVE}"', transporte=ok) == CHAVE
    with pytest.raises(pexels.ErroDoPexels, match="não parece"):
        pexels.validar_chave("curta")


def test_falso_nao_chama_ninguem():
    fotos = pexels.buscar("qualquer coisa")
    assert fotos and pexels.baixar(fotos[0].id, "previa")[:2] == b"\xff\xd8"
