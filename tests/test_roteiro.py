"""
O roteiro: as cenas de cada bloco, os cartões e os destaques da legenda, escritos pelo
Gemini (um transporte falso do httpx, que responde o que cada teste manda) e
conferidos pelo editor; sem o Gemini, pelas palavras.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from editor import ia, roteiro
from editor.cenas import Biblioteca, Cena
from editor.transcricao import Palavra

CHAVE = "AIzaSyTESTE-chave-de-mentira-123456"
NOMES = ["alerta", "camera", "certo", "dinheiro", "errado"]

FALA = ("A Rockstar não vai pegar leve no jogo. Uma página foi apagada e os fãs printaram "
        "tudo. Você vai poder carregar cocaína no inventário. Na Europa a nota é 18 e nos "
        "Estados Unidos é 17. E aí, tá certa ou passou do ponto? Deixe sua opinião e me "
        "segue pra mais.")


def _palavras(texto: str = FALA, passo: float = 0.4) -> list[Palavra]:
    return [Palavra(w, round(i * passo, 3), round(i * passo + 0.3, 3))
            for i, w in enumerate(texto.split())]


PALAVRAS = _palavras()
DURACAO = PALAVRAS[-1].fim + 0.5


def _indice(palavra: str, depois: int = 0) -> int:
    return next(i for i, w in enumerate(PALAVRAS)
                if i >= depois and w.texto.strip(".,?").lower() == palavra.lower())


BIBLIOTECA = Biblioteca([Cena(f"c{k}", Path(f"c{k}.mp4"), f"cena {k}", duracao=2.0,
                              energia="alta" if k == 3 else "")
                         for k in range(12)]
                        + [Cena("cuidado1", Path("x1.mp4"), "boate", monetizacao="cuidado",
                                duracao=2.0),
                           Cena("cuidado2", Path("x2.mp4"), "boate", monetizacao="cuidado",
                                duracao=2.0),
                           Cena("cuidado3", Path("x3.mp4"), "boate", monetizacao="cuidado",
                                duracao=2.0)])


@pytest.fixture
def de_verdade(monkeypatch):
    """O código de verdade (sem a IA falsa), com uma chave de mentira."""
    monkeypatch.delenv(ia.VARIAVEL_FALSA, raising=False)
    monkeypatch.setenv(ia.VARIAVEL_DA_CHAVE, CHAVE)


def _resposta(dados: dict) -> httpx.Response:
    texto = json.dumps(dados, ensure_ascii=False)
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": texto}]},
                                                     "finishReason": "STOP"}]})


class _Gemini:
    """Responde em ordem o que estiver na fila e guarda cada pedido."""

    def __init__(self, *respostas: httpx.Response):
        self.fila = list(respostas)
        self.pedidos: list[dict] = []

    def __call__(self, pedido: httpx.Request) -> httpx.Response:
        self.pedidos.append(json.loads(pedido.content))
        return self.fila.pop(0)

    def texto(self, k: int) -> str:
        return " ".join(p["text"] for c in self.pedidos[k]["contents"] for p in c["parts"]
                        if "text" in p)

    @property
    def transporte(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


def _escrever(gemini: _Gemini | None = None, **extra) -> roteiro.Roteiro:
    opcoes = {"biblioteca": BIBLIOTECA, "cartoes": True, "idioma": "pt",
              "nomes_de_icones": NOMES, "proibidas": ["cocaína"]}
    opcoes.update(extra)
    return roteiro.escrever(PALAVRAS, DURACAO,
                            transporte=gemini.transporte if gemini else None, **opcoes)


def _cenas_boas(blocos) -> list[dict]:
    return [{"bloco": k, "cenas": [f"c{k}"]} for k in range(len(blocos))]


def _cartoes_bons() -> list[dict]:
    return [
        {"modelo": "selo", "palavra": 0, "texto": "Sem censura", "icone": "alerta",
         "cor": "rosa"},
        {"modelo": "carimbo", "palavra": _indice("página"), "rotulo": "404",
         "texto": "APAGADA", "forte": _indice("apagada")},
        {"modelo": "lista", "palavra": _indice("carregar"), "texto": "",
         "itens": [{"texto": "cocaína no inventário", "palavra": _indice("carregar"),
                    "icone": "dinheiro"}, {"texto": "a qualquer hora",
                                           "palavra": _indice("cocaína")}]},
        {"modelo": "quadro", "palavra": _indice("europa"), "texto": "Classificação",
         "itens": [{"texto": "Europa", "valor": "18", "palavra": _indice("europa")},
                   {"texto": "EUA", "valor": "17", "palavra": _indice("estados")}]},
        {"modelo": "enquete", "palavra": _indice("certa"), "texto": "Passou do ponto?",
         "forte": _indice("deixe"),
         "itens": [{"texto": "Tá certa", "palavra": _indice("certa")},
                   {"texto": "Passou", "palavra": _indice("passou")}]},
    ]


class TestComOGemini:
    def test_cenas_e_cartoes_que_passam(self, de_verdade):
        blocos = roteiro.cenas_mod.blocos_da_fala(PALAVRAS, DURACAO)
        gemini = _Gemini(_resposta({"cenas": _cenas_boas(blocos), "cartoes": _cartoes_bons()}))
        r = _escrever(gemini)
        assert r.por == "gemini" and r.pedidos == 1 and r.aviso == ""
        assert r.escolhas == [[f"c{k}"] for k in range(len(blocos))]
        assert [c.modelo for c in r.cartoes] == ["selo", "carimbo", "lista", "quadro",
                                                 "enquete"]
        selo, carimbo, lista = r.cartoes[:3]
        # o texto vai em maiúsculas, e a palavra proibida sai censurada
        assert selo.texto == "SEM CENSURA" and selo.forte == selo.inicio == 0.0
        assert lista.itens[0].texto == "COCA**NA NO INVENTÁRIO"
        # entra 100 ms antes da palavra, e cada um vai até o seguinte
        assert carimbo.inicio == pytest.approx(PALAVRAS[_indice("página")].inicio - 0.1)
        assert selo.fim == carimbo.inicio
        assert carimbo.forte == pytest.approx(PALAVRAS[_indice("apagada")].inicio - 0.1)
        # o pedido leva a fala numerada, os blocos e o catálogo, sem os ids num enum
        texto = gemini.texto(0)
        assert "[0] A [1] Rockstar" in texto and "c11 | cena 11" in texto
        esquema = gemini.pedidos[0]["generationConfig"]["responseJsonSchema"]
        cenas = esquema["properties"]["cenas"]["items"]["properties"]["cenas"]["items"]
        assert "enum" not in cenas

    def test_o_que_veio_errado_volta_para_conserto_uma_vez(self, de_verdade):
        blocos = roteiro.cenas_mod.blocos_da_fala(PALAVRAS, DURACAO)
        ruins = _cenas_boas(blocos)
        ruins[1]["cenas"] = ["nao-existe"]
        ruins[2]["cenas"] = ["c0"]                                   # repetida
        cartoes_ruins = [{"modelo": "lista", "palavra": 3, "itens": [
            {"texto": "um", "palavra": 5}]}]                         # um item só
        gemini = _Gemini(_resposta({"cenas": ruins, "cartoes": cartoes_ruins}),
                         _resposta({"cenas": _cenas_boas(blocos), "cartoes": _cartoes_bons()}))
        r = _escrever(gemini)
        assert r.pedidos == 2
        conserto = gemini.texto(1)
        assert "'nao-existe' não está na lista" in conserto
        assert "a cena c0 já foi usada" in conserto
        assert "pede de 2 a 4 itens, vieram 1" in conserto
        assert r.escolhas == [[f"c{k}"] for k in range(len(blocos))]
        assert len(r.cartoes) == 5

    def test_o_conserto_nao_repete_cena(self, de_verdade):
        blocos = roteiro.cenas_mod.blocos_da_fala(PALAVRAS, DURACAO)
        primeira = _cenas_boas(blocos)
        primeira[0]["cenas"] = ["inexistente"]                       # o bloco 0 fica vazio
        segunda = [{"bloco": 0, "cenas": ["c1"]}]                    # c1 já está no bloco 1
        gemini = _Gemini(_resposta({"cenas": primeira, "cartoes": []}),
                         _resposta({"cenas": segunda, "cartoes": []}))
        r = _escrever(gemini)
        todas = [i for e in r.escolhas for i in e]
        assert len(todas) == len(set(todas))
        assert all(r.escolhas)

    def test_cuidado_no_maximo_duas(self, de_verdade):
        blocos = roteiro.cenas_mod.blocos_da_fala(PALAVRAS, DURACAO)
        cenas_ = _cenas_boas(blocos)
        cenas_[0]["cenas"] = ["cuidado1", "cuidado2", "cuidado3"]
        gemini = _Gemini(_resposta({"cenas": cenas_, "cartoes": []}),
                         _resposta({"cenas": cenas_, "cartoes": []}))
        r = _escrever(gemini)
        assert r.escolhas[0] == ["cuidado1", "cuidado2"]

    def test_cartao_que_entra_antes_do_anterior_terminar_sai(self, de_verdade):
        cartoes = _cartoes_bons()[:3]
        # a lista entra antes do carimbo cair: o carimbo fica, a lista sai
        cartoes[2]["palavra"] = _indice("foi")
        cartoes[2]["itens"] = [{"texto": "um", "palavra": _indice("foi")},
                               {"texto": "dois", "palavra": _indice("apagada")}]
        gemini = _Gemini(_resposta({"cenas": [], "cartoes": cartoes}),
                         _resposta({"cenas": [], "cartoes": cartoes}))
        r = _escrever(gemini, biblioteca=None)
        assert [c.modelo for c in r.cartoes] == ["selo", "carimbo"]
        assert "entra antes de o carimbo" in gemini.texto(1)

    def test_os_destaques_da_legenda(self, de_verdade):
        destaques = [{"de": 1, "ate": 1, "estilo": "ciano"},
                     {"de": 2, "ate": 5, "estilo": "pilula"},
                     {"de": 4, "ate": 6, "estilo": "rosa"},           # sobrepõe: sai
                     {"de": 7, "ate": 8, "estilo": "pilula"},         # perto demais: vira rosa
                     {"de": 20, "ate": 27, "estilo": "rosa"},         # 8 palavras: sai
                     {"de": 30, "ate": 999, "estilo": "rosa"}]        # fora da fala: sai
        gemini = _Gemini(_resposta({"cartoes": [], "destaques": destaques}))
        r = _escrever(gemini, biblioteca=None, cartoes=False, destaques=True)
        assert r.destaques == [(1, 1, "ciano"), (2, 5, "pilula"), (7, 8, "rosa")]
        assert "OS DESTAQUES DA LEGENDA" in gemini.texto(0)
        assert r.para_json()["destaques"] == [[1, 1, "ciano"], [2, 5, "pilula"],
                                              [7, 8, "rosa"]]

    def test_sem_destaques_do_gemini_ficam_os_das_palavras(self, de_verdade):
        gemini = _Gemini(_resposta({"cartoes": [], "destaques": []}))
        r = _escrever(gemini, biblioteca=None, cartoes=False, destaques=True)
        assert (1, 1, "ciano") in r.destaques                    # "Rockstar"

    def test_quantos_cartoes_pela_duracao(self):
        assert roteiro.quantos_cartoes(46.0) == (6, 9)
        assert roteiro.quantos_cartoes(3.0) == (1, 1)
        assert roteiro.quantos_cartoes(180.0) == (22, 36)


class TestSemOGemini:
    def test_sem_chave_as_cenas_vem_das_palavras(self, monkeypatch):
        monkeypatch.delenv(ia.VARIAVEL_FALSA, raising=False)
        r = _escrever()
        assert r.por == "palavras" and r.cartoes == []
        assert "sem a chave do Gemini" in r.aviso
        assert all(r.escolhas) and len(r.escolhas) == len(r.blocos)

    def test_gemini_fora_do_ar(self, de_verdade, monkeypatch):
        monkeypatch.setattr(ia, "ESPERA_S", 0)
        gemini = _Gemini(*[httpx.Response(503, json={"error": {"message": "fora"}})] * 20)
        r = _escrever(gemini, destaques=True)
        assert r.por == "palavras" and "o Gemini não respondeu" in r.aviso
        assert r.destaques                                          # os das palavras

    def test_a_ia_falsa(self):
        r = _escrever(destaques=True)
        assert r.por == "falsa"
        assert {c.modelo for c in r.cartoes} >= {"selo", "lista", "carimbo"}
        assert (2, 3, "pilula") in r.destaques

    def test_nada_pedido_nada_feito(self, de_verdade):
        r = _escrever(_Gemini(), biblioteca=None, cartoes=False)
        assert r.por == "" and r.pedidos == 0
