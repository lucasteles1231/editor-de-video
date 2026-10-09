"""
A matriz gerada a partir dos clipes: a leitura (3 quadros e o movimento), a energia, o
pedido ao Gemini (um transporte falso do httpx), o que fica guardado, a cena recusada,
o rascunho sem chave e o terminal.
"""
from __future__ import annotations

import json
from pathlib import Path

import av
import httpx
import numpy as np
import pytest

from editor import catalogo, cenas, ia

CHAVE = "AIzaSyTESTE-chave-de-mentira-123456"


def _clipe(caminho: Path, *, mexe: bool, segundos: float = 1.0, cor=(200, 60, 40)) -> Path:
    """Um clipe de cor única (parado) ou com uma faixa que corre pela tela (mexe)."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with av.open(str(caminho), "w") as c:
        v = c.add_stream("libx264", rate=30, options={"crf": "20", "preset": "ultrafast"})
        v.width, v.height, v.pix_fmt = 160, 90, "yuv420p"
        for i in range(round(segundos * 30)):
            q = np.empty((90, 160, 3), np.uint8)
            q[...] = cor
            if mexe:
                x = (i * 9) % 160
                q[:, x:x + 30] = 255 - np.array(cor, np.uint8)
            f = av.VideoFrame.from_ndarray(q, format="rgb24")
            f.pts = i
            for p in v.encode(f):
                c.mux(p)
        for p in v.encode():
            c.mux(p)
    return caminho


@pytest.fixture
def pasta(tmp_path) -> Path:
    raiz = tmp_path / "cenas"
    _clipe(raiz / "clipes" / "t1-001-explosao-carro.mp4", mexe=True)
    _clipe(raiz / "clipes" / "t1-002-praia-calma.mp4", mexe=False, cor=(40, 140, 220))
    _clipe(raiz / "t1-003_cidade_noite.mp4", mexe=True, cor=(20, 20, 60))
    return raiz


@pytest.fixture
def de_verdade(monkeypatch):
    monkeypatch.delenv(ia.VARIAVEL_FALSA, raising=False)
    monkeypatch.setenv(ia.VARIAVEL_DA_CHAVE, CHAVE)


class _Gemini:
    """Responde cada pedido com o que a função manda e guarda os pedidos."""

    def __init__(self, responder):
        self.responder = responder
        self.pedidos: list[dict] = []

    def __call__(self, pedido: httpx.Request) -> httpx.Response:
        corpo = json.loads(pedido.content)
        self.pedidos.append(corpo)
        return self.responder(corpo)

    @property
    def transporte(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


def _texto(corpo: dict) -> str:
    return " ".join(p["text"] for c in corpo["contents"] for p in c["parts"] if "text" in p)


def _imagens(corpo: dict) -> int:
    return sum("inlineData" in p for c in corpo["contents"] for p in c["parts"])


def _resposta(cenas_: list[dict]) -> httpx.Response:
    texto = json.dumps({"cenas": cenas_}, ensure_ascii=False)
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": texto}]},
                                                     "finishReason": "STOP"}]})


def _descreve_todas(corpo: dict) -> httpx.Response:
    n = _imagens(corpo) // catalogo.QUADROS_POR_CLIPE
    return _resposta([{"k": k, "descricao": f"Cena {k} descrita", "categorias": ["Ação", "Carro"],
                       "personagens": ["Lucia"] if k == 0 else [], "periodo": "dia",
                       "energia": "alta", "monetizacao": "ok", "obs": ""} for k in range(n)])


class TestALeitura:
    def test_tres_quadros_e_o_movimento(self, pasta):
        parado = catalogo.ler_clipe(pasta / "clipes" / "t1-002-praia-calma.mp4", "a.mp4")
        mexendo = catalogo.ler_clipe(pasta / "clipes" / "t1-001-explosao-carro.mp4", "b.mp4")
        assert len(parado.quadros) == len(mexendo.quadros) == catalogo.QUADROS_POR_CLIPE
        assert all(q[:2] == b"\xff\xd8" for q in parado.quadros)          # JPEG
        assert parado.movimento < 1.0 < mexendo.movimento
        assert parado.duracao == pytest.approx(1.0, abs=0.05)

    @pytest.mark.parametrize(("movimentos", "esperado"), [
        ([1.0, 2.0], ["media", "media"]),
        ([5.0, 1.0, 3.0], ["alta", "baixa", "media"]),
        ([1, 2, 3, 4, 5, 6], ["baixa", "baixa", "media", "media", "alta", "alta"]),
    ])
    def test_a_energia_pela_posicao(self, movimentos, esperado):
        assert catalogo.energias(movimentos) == esperado

    def test_os_clipes_com_o_caminho_relativo(self, pasta):
        assert [a for _, a in catalogo.clipes_relativos(pasta)] == [
            "clipes/t1-001-explosao-carro.mp4", "clipes/t1-002-praia-calma.mp4",
            "t1-003_cidade_noite.mp4"]


class TestComOGemini:
    def test_descreve_e_a_matriz_vale(self, pasta, de_verdade):
        gemini = _Gemini(_descreve_todas)
        g = catalogo.gerar(catalogo.clipes_relativos(pasta), assunto="trailers do GTA 6",
                           transporte=gemini.transporte)
        assert g.por == "gemini" and g.aviso == "" and g.pedidos == 1
        assert _imagens(gemini.pedidos[0]) == 3 * catalogo.QUADROS_POR_CLIPE
        texto = _texto(gemini.pedidos[0])
        assert "trailers do GTA 6" in texto and "clipes/t1-002-praia-calma.mp4" in texto
        primeira = g.cenas[0]
        assert primeira["arquivo"] == "clipes/t1-001-explosao-carro.mp4"
        assert primeira["id"] == "t1-001-explosao-carro"
        assert primeira["categorias"] == ["acao", "carro"]             # sem acento, minúsculas
        assert primeira["personagens"] == ["Lucia"] and primeira["energia"] == "alta"
        # o editor lê o que ele mesmo escreveu
        b = cenas.ler_matriz(json.dumps(g.cenas), cenas.clipes_da_pasta(pasta))
        assert len(b.cenas) == 3

    def test_o_que_ja_foi_descrito_nao_pede_de_novo(self, pasta, de_verdade):
        gemini = _Gemini(_descreve_todas)
        catalogo.gerar(catalogo.clipes_relativos(pasta), transporte=gemini.transporte)
        segunda = catalogo.gerar(catalogo.clipes_relativos(pasta), transporte=gemini.transporte)
        assert len(gemini.pedidos) == 1 and segunda.pedidos == 0
        assert segunda.cenas[1]["descricao"] == "Cena 1 descrita"
        # outro assunto é outra descrição
        catalogo.gerar(catalogo.clipes_relativos(pasta), assunto="outra coisa",
                       transporte=gemini.transporte)
        assert len(gemini.pedidos) == 2

    def test_a_cena_que_faltou_volta_uma_vez(self, pasta, de_verdade):
        vezes = []

        def so_a_primeira(corpo):
            vezes.append(1)
            if len(vezes) == 1:                         # o primeiro pedido: só a cena 0
                return _resposta([{"k": 0, "descricao": "A primeira", "categorias": [],
                                   "periodo": "dia", "energia": "baixa", "monetizacao": "ok"}])
            return _descreve_todas(corpo)
        gemini = _Gemini(so_a_primeira)
        g = catalogo.gerar(catalogo.clipes_relativos(pasta), transporte=gemini.transporte)
        assert len(gemini.pedidos) == 2
        assert [c["descricao"] for c in g.cenas] == ["A primeira", "Cena 0 descrita",
                                                     "Cena 1 descrita"]

    def test_a_cena_recusada_fica_evitar(self, pasta, de_verdade):
        def recusa_a_praia(corpo):
            if "praia-calma" in _texto(corpo):          # o arquivo, e não o exemplo
                return httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}})
            return _descreve_todas(corpo)
        gemini = _Gemini(recusa_a_praia)
        g = catalogo.gerar(catalogo.clipes_relativos(pasta), transporte=gemini.transporte)
        praia = g.cenas[1]
        assert praia["monetizacao"] == "evitar" and "não quis descrever" in praia["obs"]
        assert praia["descricao"] == "Praia calma"                     # o nome do arquivo
        assert g.cenas[0]["descricao"].startswith("Cena") and g.cenas[2]["descricao"]
        # o lote de 3 foi dividido até isolar a praia
        assert len(gemini.pedidos) >= 3

    def test_a_cota_acaba_e_fica_o_rascunho(self, pasta, de_verdade):
        corpo_429 = {"error": {"code": 429, "details": [
            {"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}}
        gemini = _Gemini(lambda corpo: httpx.Response(429, json=corpo_429))
        g = catalogo.gerar(catalogo.clipes_relativos(pasta), transporte=gemini.transporte)
        assert "cota" in g.aviso and "gere de novo" in g.aviso
        assert [c["descricao"] for c in g.cenas] == ["Explosao carro", "Praia calma",
                                                     "Cidade noite"]


class TestSemOGemini:
    def test_sem_chave_sai_o_rascunho(self, pasta, monkeypatch):
        monkeypatch.delenv(ia.VARIAVEL_FALSA, raising=False)
        g = catalogo.gerar(catalogo.clipes_relativos(pasta))
        assert g.por == "rascunho" and "sem a chave" in g.aviso
        assert g.cenas[0]["descricao"] == "Explosao carro"
        assert {c["energia"] for c in g.cenas} <= set(cenas.ENERGIAS)
        # a que mexe é mais forte que a parada
        energia = {c["arquivo"]: c["energia"] for c in g.cenas}
        assert energia["clipes/t1-002-praia-calma.mp4"] == "baixa"

    def test_a_ia_falsa(self, pasta):
        g = catalogo.gerar(catalogo.clipes_relativos(pasta))
        assert g.por == "falsa" and len(g.cenas) == 3

    def test_o_progresso(self, pasta):
        visto: list[tuple[int, int, int]] = []
        catalogo.gerar(catalogo.clipes_relativos(pasta),
                       progresso=lambda *a: visto.append(a))
        assert visto[-1][:2] == (3, 3)


class TestOTerminal:
    def test_gera_o_cenas_json_ao_lado_dos_clipes(self, pasta, capsys):
        from editor import cli

        assert cli.main(["--gerar-matriz", str(pasta), "--assunto", "um jogo"]) == 0
        gerada = json.loads((pasta / "cenas.json").read_text(encoding="utf-8"))
        assert len(gerada) == 3 and "3 cenas descritas" in capsys.readouterr().out
        # com um cenas.json que já existe, o novo vai para outro nome
        assert cli.main(["--gerar-matriz", str(pasta)]) == 0
        assert (pasta / "cenas-gerada.json").is_file()

    def test_pasta_sem_clipes(self, tmp_path, capsys):
        from editor import cli

        assert cli.main(["--gerar-matriz", str(tmp_path)]) == 2
        assert "não tem clipes" in capsys.readouterr().err
