"""
A thumbnail com IA, sem rede: a API do Gemini é um transporte falso do httpx, que guarda
os pedidos e responde o que cada teste manda.
"""
from __future__ import annotations

import base64
import json
import os
import re
import stat

import httpx
import pytest

from editor import ia

NOMES = ["alerta", "celular", "dinheiro", "relogio"]
QUADROS = [(1.0, b"\xff\xd8quadro-um"), (5.5, b"\xff\xd8quadro-dois"),
           (9.0, b"\xff\xd8quadro-tres")]
CHAVE = "AIzaSyTESTE-chave-de-mentira-123456"


@pytest.fixture
def de_verdade(monkeypatch):
    """O código de verdade (sem a IA falsa), com uma chave de mentira."""
    monkeypatch.delenv(ia.VARIAVEL_FALSA, raising=False)
    monkeypatch.setenv(ia.VARIAVEL_DA_CHAVE, CHAVE)


def _variante(**muda) -> dict:
    v = {"ideia": "a ideia", "modelo": "classico", "chamada": "A gravidade explicada",
         "destaque": "gravidade", "numero": "", "selo": "", "icone": "nenhum",
         "cor": "amarelo", "fundo": "cor", "recorte": True, "quadro": 1,
         "rosto": [100, 300, 400, 600], "seta": False, "alvo": []}
    v.update(muda)
    return v


def _resposta(variantes: list[dict], fim: str = "STOP") -> httpx.Response:
    texto = json.dumps({"variantes": variantes}, ensure_ascii=False)
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": texto}]},
                                                     "finishReason": fim}]})


class _Gemini:
    """Responde em ordem o que estiver na fila e guarda cada pedido."""

    def __init__(self, *respostas: httpx.Response):
        self.fila = list(respostas)
        self.pedidos: list[httpx.Request] = []

    def __call__(self, pedido: httpx.Request) -> httpx.Response:
        self.pedidos.append(pedido)
        return self.fila.pop(0)

    @property
    def transporte(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


def _sugerir(gemini: _Gemini, **extra):
    return ia.sugerir("Hoje eu explico a gravidade.", QUADROS, idioma="pt", duracao=12.0,
                      vertical=True, nomes_de_icones=NOMES, transporte=gemini.transporte,
                      **extra)


class TestAConferencia:
    def _conferir(self, v):
        return ia.conferir(v, quadros=8, nomes_de_icones=set(NOMES))

    def test_ideia_boa(self):
        pronta, problemas = self._conferir(_variante())
        assert problemas == []
        assert pronta["destaque"] == 1 and pronta["icone"] == ""
        # a caixa do Gemini é [ymin, xmin, ymax, xmax] de 0 a 1000
        assert pronta["rosto"] == {"x0": 0.3, "y0": 0.1, "x1": 0.6, "y1": 0.4}

    @pytest.mark.parametrize("chamada", ["Gravidade", "Por que as coisas caem no chão hoje",
                                         "Aerodinamicamente incompreensível"])
    def test_chamada_fora_da_medida(self, chamada):
        pronta, problemas = self._conferir(_variante(chamada=chamada, destaque=""))
        assert pronta is None and problemas

    def test_formula_gasta(self):
        _, problemas = self._conferir(_variante(chamada="Você não vai acreditar",
                                                destaque="acreditar"))
        assert any("gasta" in p for p in problemas)

    def test_destaque_com_pontuacao_e_acento(self):
        pronta, _ = self._conferir(_variante(chamada="Você erra isso?", destaque="ISSO"))
        assert pronta["destaque"] == 2

    def test_destaque_que_nao_esta_na_chamada(self):
        _, problemas = self._conferir(_variante(destaque="maçã"))
        assert any("destaque" in p for p in problemas)

    def test_modelo_numero_precisa_de_numero(self):
        _, problemas = self._conferir(_variante(modelo="numero", numero="muitos"))
        assert any("número" in p for p in problemas)
        pronta, _ = self._conferir(_variante(modelo="numero", numero="R$10"))
        assert pronta["numero"] == "R$10"

    def test_catalogos_fechados(self):
        for campo, valor in (("cor", "bege"), ("modelo", "meme"), ("fundo", "video"),
                             ("quadro", 8)):
            pronta, problemas = self._conferir(_variante(**{campo: valor}))
            assert pronta is None and problemas, campo

    def test_icone_que_nao_existe_sai_sem_icone(self):
        """O ícone não vai mais como enum no esquema; um nome inventado não pode custar
        um pedido de conserto, então a ideia sai sem ícone."""
        pronta, problemas = self._conferir(_variante(icone="foguete-lunar"))
        assert pronta["icone"] == "" and not problemas
        pronta, _ = self._conferir(_variante(icone=" Dinheiro "))
        assert pronta["icone"] == "dinheiro"

    def test_caixa_invertida_ou_minuscula(self):
        _, problemas = self._conferir(_variante(rosto=[400, 600, 100, 300]))
        assert any("rosto" in p for p in problemas)

    def test_rosto_do_tamanho_da_pessoa_sai(self):
        """Visto num teste real: a caixa do "rosto" veio com a pessoa inteira dentro."""
        pronta, problemas = self._conferir(_variante(rosto=[80, 300, 950, 700]))
        assert pronta["rosto"] is None and not problemas
        pronta, _ = self._conferir(_variante(rosto=[100, 400, 350, 600]))
        assert pronta["rosto"] == {"x0": 0.4, "y0": 0.1, "x1": 0.6, "y1": 0.35}

    def test_seta_sem_alvo_vira_sem_seta(self):
        pronta, _ = self._conferir(_variante(seta=True, alvo=[]))
        assert pronta["seta"] is False and pronta["alvo"] is None
        pronta, _ = self._conferir(_variante(seta=True, alvo=[500, 500, 800, 900]))
        assert pronta["seta"] is True and pronta["alvo"]["x1"] == 0.9


class TestOPedido:
    def test_formato(self, de_verdade):
        gemini = _Gemini(_resposta([_variante(), _variante(chamada="Gravidade sem mistério",
                                                           destaque="Gravidade"),
                                    _variante(chamada="Por que tudo cai", destaque="cai")]))
        r = _sugerir(gemini)
        assert len(r["variantes"]) == 3 and r["modelo"] == ia.MODELOS[0]
        assert r["variantes"][0]["t"] == 5.5                     # o quadro 1
        pedido = gemini.pedidos[0]
        # a chave vai no cabeçalho, nunca na URL
        assert pedido.headers["x-goog-api-key"] == CHAVE and CHAVE not in str(pedido.url)
        corpo = json.loads(pedido.content)
        config = corpo["generationConfig"]
        assert config["thinkingConfig"] == {"thinkingBudget": 0}
        assert config["responseMimeType"] == "application/json"
        assert "propertyOrdering" not in json.dumps(config)
        # nenhum enum grande no esquema: os 3.x recusavam o de 123 ícones com um 400
        enums = re.findall(r'"enum": \[([^\]]*)\]', json.dumps(config["responseJsonSchema"]))
        assert enums and max(e.count(",") + 1 for e in enums) <= 10
        partes = corpo["contents"][0]["parts"]
        # as imagens primeiro, a pergunta por último
        assert [list(p) for p in partes] == [["inlineData"]] * 3 + [["text"]]
        assert base64.b64decode(partes[0]["inlineData"]["data"]) == QUADROS[0][1]
        assert "Hoje eu explico a gravidade" in partes[-1]["text"]
        assert "dinheiro" in partes[-1]["text"]                  # o catálogo vai no pedido

    def test_so_vai_o_texto_e_os_quadros(self, de_verdade):
        """O que sai do computador: a fala e os quadros pequenos, e mais nada."""
        gemini = _Gemini(_resposta([_variante()] * 3))
        _sugerir(gemini)
        corpo = json.loads(gemini.pedidos[0].content)
        assert set(corpo) == {"systemInstruction", "contents", "generationConfig"}
        assert len(gemini.pedidos[0].content) < 20_000

    def test_escada_de_modelos(self, de_verdade):
        gemini = _Gemini(httpx.Response(429, json={"error": {"message": "quota"}}),
                         httpx.Response(404, json={"error": {"message": "no model"}}),
                         _resposta([_variante()] * 3))
        r = _sugerir(gemini)
        assert r["modelo"] == ia.MODELOS[2]
        assert [p.url.path.rsplit("/", 1)[-1] for p in gemini.pedidos] == [
            f"{m}:generateContent" for m in ia.MODELOS]

    def test_sem_cota_em_todos(self, de_verdade):
        gemini = _Gemini(*[httpx.Response(429, json={"error": {"message": "quota"}})] * 3)
        with pytest.raises(ia.ErroDaIA, match="cota grátis"):
            _sugerir(gemini)

    def test_sobrecarga_tenta_o_mesmo_de_novo(self, de_verdade, monkeypatch):
        monkeypatch.setattr(ia, "ESPERA_S", 0)
        gemini = _Gemini(httpx.Response(503, json={"error": {"message": "high demand"}}),
                         _resposta([_variante()] * 3))
        r = _sugerir(gemini)
        assert r["modelo"] == ia.MODELOS[0]
        assert len(gemini.pedidos) == 2 and r["pedidos"] == 2     # a conta dos pedidos

    def test_400_generico_tenta_pensando(self, de_verdade):
        """Visto na primeira chamada de verdade: o modelo 3.x recusava com um 400
        genérico ("invalid argument"), sem dizer que era o raciocínio desligado."""
        gemini = _Gemini(httpx.Response(400, json={"error": {"message": "invalid argument"}}),
                         _resposta([_variante()] * 3))
        assert _sugerir(gemini)["modelo"] == ia.MODELOS[0]
        segundo = json.loads(gemini.pedidos[1].content)["generationConfig"]
        assert "thinkingConfig" not in segundo

    def test_depois_da_recusa_o_modelo_ja_vai_pensando(self, de_verdade):
        """O pedido seguinte da sessão (o conserto do roteiro, as ideias) não gasta de novo
        a tentativa que o modelo sempre recusa."""
        gemini = _Gemini(httpx.Response(400, json={"error": {"message": "invalid argument"}}),
                         _resposta([_variante()] * 3), _resposta([_variante()] * 3))
        assert _sugerir(gemini)["pedidos"] == 2
        assert _sugerir(gemini)["pedidos"] == 1
        terceiro = json.loads(gemini.pedidos[2].content)["generationConfig"]
        assert "thinkingConfig" not in terceiro

    def test_um_400_que_continua_nao_marca_o_modelo(self, de_verdade):
        # recusado com e sem raciocínio (um esquema ruim, por exemplo): não é o raciocínio
        ruim = httpx.Response(400, json={"error": {"message": "invalid argument"}})
        gemini = _Gemini(*[ruim] * 2 * len(ia.MODELOS))
        with pytest.raises(ia.ErroDaIA):
            _sugerir(gemini)
        assert set() == ia._PENSA_SEMPRE

    def test_cota_do_dia_diz_quando_volta(self, de_verdade):
        """O formato real, copiado de um 429 do gemini-3.8-flash em 03/10/2026."""
        corpo = {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "details": [
            {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [
                {"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
                 "quotaValue": "20"}]},
            {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "1801s"}]}}
        gemini = _Gemini(*[httpx.Response(429, json=corpo)] * 3)
        with pytest.raises(ia.ErroDaIA, match="volta em cerca de 30 min"):
            _sugerir(gemini)

    def test_cota_do_minuto(self, de_verdade):
        corpo = {"error": {"message": "quota", "details": [
            {"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}]}}
        gemini = _Gemini(*[httpx.Response(429, json=corpo)] * 3)
        with pytest.raises(ia.ErroDaIA, match="Espere um minuto"):
            _sugerir(gemini)

    def test_resposta_cortada_tenta_o_proximo(self, de_verdade):
        gemini = _Gemini(_resposta([_variante()], fim="MAX_TOKENS"),
                         _resposta([_variante()] * 3))
        assert _sugerir(gemini)["modelo"] == ia.MODELOS[1]

    def test_modelo_que_nao_desliga_o_raciocinio(self, de_verdade):
        gemini = _Gemini(httpx.Response(400, json={"error": {
                             "message": "thinking budget is not supported"}}),
                         _resposta([_variante()] * 3))
        r = _sugerir(gemini)
        assert r["modelo"] == ia.MODELOS[0]
        segundo = json.loads(gemini.pedidos[1].content)["generationConfig"]
        assert "thinkingConfig" not in segundo

    def test_chave_recusada_para_na_hora(self, de_verdade):
        gemini = _Gemini(httpx.Response(403, json={"error": {"message": "denied"}}))
        with pytest.raises(ia.ErroDaIA, match="recusou a chave"):
            _sugerir(gemini)
        assert len(gemini.pedidos) == 1

    def test_conserto_das_ideias_ruins(self, de_verdade):
        ruim = _variante(chamada="Você não vai acreditar nisso", destaque="isso")
        gemini = _Gemini(_resposta([_variante(), ruim, _variante(chamada="Tudo cai",
                                                                 destaque="cai")]),
                         _resposta([_variante(chamada="Gravidade de verdade",
                                              destaque="Gravidade")]))
        r = _sugerir(gemini)
        assert len(r["variantes"]) == 3
        conserto = json.loads(gemini.pedidos[1].content)["contents"][0]["parts"][-1]["text"]
        assert "VIERAM COM PROBLEMAS" in conserto and "gasta" in conserto
        assert "sem falar da correção" in conserto

    def test_evitar_as_chamadas_anteriores(self, de_verdade):
        gemini = _Gemini(_resposta([_variante()] * 3))
        _sugerir(gemini, evitar=["A gravidade explicada"])
        texto = json.loads(gemini.pedidos[0].content)["contents"][0]["parts"][-1]["text"]
        assert "ideias diferentes delas" in texto and "A gravidade explicada" in texto

    def test_sem_chave(self, monkeypatch):
        monkeypatch.delenv(ia.VARIAVEL_FALSA, raising=False)
        with pytest.raises(ia.ErroDaIA, match="Falta a chave"):
            _sugerir(_Gemini())

    def test_falsa_nao_chama_ninguem(self):
        gemini = _Gemini()
        r = _sugerir(gemini)
        assert len(r["variantes"]) == 3 and gemini.pedidos == []
        assert {v["t"] for v in r["variantes"]} <= {t for t, _ in QUADROS}


class TestAChave:
    def test_variavel_ganha_do_arquivo(self, monkeypatch):
        ia.salvar_chave("chave-do-arquivo-12345678901234")
        assert ia.chave() == ("chave-do-arquivo-12345678901234", "arquivo")
        monkeypatch.setenv(ia.VARIAVEL_DA_CHAVE, "chave-da-variavel-123456789012")
        assert ia.chave() == ("chave-da-variavel-123456789012", "variavel")

    @pytest.mark.skipif(os.name != "posix", reason="permissão de arquivo é coisa de POSIX")
    def test_arquivo_so_do_usuario(self):
        ia.salvar_chave("chave-do-arquivo-12345678901234")
        modo = stat.S_IMODE(os.stat(ia.pasta_de_config() / "config.json").st_mode)
        assert modo == 0o600

    def test_estado_nunca_mostra_a_chave(self, monkeypatch):
        monkeypatch.delenv(ia.VARIAVEL_FALSA, raising=False)
        ia.salvar_chave(CHAVE)
        e = ia.estado()
        assert e["configurada"] and CHAVE not in json.dumps(e) and e["final"] == "…3456"
        ia.apagar_chave()
        assert ia.estado()["configurada"] is False

    def test_validar_chave(self):
        ok = httpx.MockTransport(lambda r: httpx.Response(200, json={"models": []}))
        ia.validar_chave(CHAVE, transporte=ok)
        recusa = httpx.MockTransport(lambda r: httpx.Response(400, json={"error": {}}))
        with pytest.raises(ia.ErroDaIA, match="recusou esta chave"):
            ia.validar_chave(CHAVE, transporte=recusa)
        with pytest.raises(ia.ErroDaIA, match="não parece uma chave"):
            ia.validar_chave("minha chave")

    @pytest.mark.parametrize("colada", [
        "AQ.Ab8RN6Kq-exemplo_de.chave-nova-com-ponto",          # o formato novo, com ponto
        '"AIzaSyTESTE-chave-de-mentira-123456"',                # com aspas
        "GEMINI_API_KEY=AIzaSyTESTE-chave-de-mentira-123456",  # copiada de um .env
        "  AIzaSyTESTE-chave-de-mentira-123456\n",
    ])
    def test_chave_colada_de_varios_jeitos(self, colada):
        """Visto na primeira chave de verdade: o formato rígido (letras, números, "_" e
        "-") recusou uma chave válida antes de perguntar ao Google."""
        vistos = []

        def google(pedido):
            vistos.append(pedido.headers["x-goog-api-key"])
            return httpx.Response(200, json={"models": []})

        limpa = ia.validar_chave(colada, transporte=httpx.MockTransport(google))
        assert limpa == vistos[0] and limpa == limpa.strip().strip('"')
        assert "=" not in limpa and " " not in limpa


class TestOsCamposDoFundo:
    def _conferir(self, **muda):
        return ia.conferir(_variante(**muda), quadros=8, nomes_de_icones=set(NOMES))

    def test_video_precisa_do_quadro_do_fundo(self):
        pronta, problemas = self._conferir(fundo="video")
        assert pronta is None and any("quadro_fundo" in p for p in problemas)
        pronta, _ = self._conferir(fundo="video", quadro_fundo=5, foco=[200, 100, 700, 900])
        assert pronta["quadro_fundo"] == 5 and pronta["foco"]["x1"] == 0.9

    def test_banco_precisa_da_busca_e_gerado_da_cena(self):
        assert self._conferir(fundo="banco")[0] is None
        assert self._conferir(fundo="banco", busca="praia deserta")[0]["busca"] == "praia deserta"
        assert self._conferir(fundo="gerado")[0] is None
        assert self._conferir(fundo="gerado", cena="um estúdio")[0]["cena"] == "um estúdio"

    def test_campos_de_outro_fundo_vao_vazios(self):
        pronta, _ = self._conferir(fundo="cor", busca="praia", cena="mar", quadro_fundo=3)
        assert (pronta["busca"], pronta["cena"], pronta["quadro_fundo"]) == ("", "", -1)

    def test_luz_e_mao(self):
        assert self._conferir(luz="raios", mao="titulo")[0]["luz"] == "raios"
        assert self._conferir(luz="neon")[0] is None
        # a mão que apontaria para um alvo que não existe aponta para o título
        assert self._conferir(mao="alvo", alvo=[])[0]["mao"] == "titulo"


class TestOFundoGerado:
    def _imagem(self) -> httpx.Response:
        dados = base64.b64encode(b"\x89PNG-de-mentira").decode()
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [
            {"inlineData": {"mimeType": "image/png", "data": dados}}]}}]})

    def test_formato_do_pedido(self, de_verdade):
        gemini = _Gemini(self._imagem())
        dados = ia.gerar_fundo("um estúdio colorido", "9:16", transporte=gemini.transporte)
        assert dados == b"\x89PNG-de-mentira"
        pedido = gemini.pedidos[0]
        assert pedido.url.path.endswith(f"/models/{ia.MODELO_DE_IMAGEM}:generateContent")
        assert pedido.headers["x-goog-api-key"] == CHAVE and CHAVE not in str(pedido.url)
        corpo = json.loads(pedido.content)
        assert corpo["generationConfig"] == {"responseModalities": ["IMAGE"],
                                             "imageConfig": {"aspectRatio": "9:16"}}
        texto = corpo["contents"][0]["parts"][0]["text"]
        assert "um estúdio colorido" in texto and "no text" in texto and "no people" in texto
        # o gasto fica anotado
        gastos = (ia.pasta_de_dados() / "gastos.jsonl").read_text(encoding="utf-8")
        assert '"proporcao": "9:16"' in gastos

    @pytest.mark.parametrize("mensagem", ["Quota exceeded ... limit: 0, model: gemini",
                                          "This feature requires billing to be enabled"])
    def test_sem_faturamento(self, de_verdade, mensagem):
        gemini = _Gemini(httpx.Response(429, json={"error": {"message": mensagem}}))
        with pytest.raises(ia.ErroDaIA, match="faturamento"):
            ia.gerar_fundo("um estúdio", transporte=gemini.transporte)

    def test_teto_da_sessao(self, de_verdade, monkeypatch):
        monkeypatch.setattr(ia, "_geradas", ia.TETO_DE_IMAGENS)
        gemini = _Gemini()
        with pytest.raises(ia.ErroDaIA, match="teto"):
            ia.gerar_fundo("um estúdio", transporte=gemini.transporte)
        assert gemini.pedidos == []

    def test_conta_tambem_a_tentativa_recusada(self, de_verdade):
        gemini = _Gemini(httpx.Response(500, json={"error": {"message": "falhou"}}))
        with pytest.raises(ia.ErroDaIA):
            ia.gerar_fundo("um estúdio", transporte=gemini.transporte)
        assert ia.geracoes_restantes() == ia.TETO_DE_IMAGENS - 1

    def test_falsa_nao_gasta(self):
        dados = ia.gerar_fundo("qualquer", "1:1")
        assert dados[:4] == b"\x89PNG" and ia.geracoes_restantes() == ia.TETO_DE_IMAGENS


class TestAMontagemEmCamadas:
    """Na montagem, os quadros vêm de duas camadas: a pessoa e o fundo."""

    ORIGENS = ["pessoa"] * 4 + ["fundo"] * 4

    def test_o_pedido_diz_de_onde_vem_cada_quadro(self):
        pedido = ia.montar_pedido("fala", [1.0 * i for i in range(8)], idioma="pt",
                                  duracao=20.0, vertical=True, nomes_de_icones=NOMES,
                                  origens=self.ORIGENS)
        assert "quadro 0: a 1ª imagem, em 0.0 s (da pessoa)" in pedido
        assert "quadro 7: a 8ª imagem, em 7.0 s (do fundo)" in pedido
        assert "MONTADO EM CAMADAS" in pedido and "0, 1, 2, 3" in pedido
        so_fundo = ia.montar_pedido("fala", [1.0] * 8, idioma="pt", duracao=20.0,
                                    vertical=True, nomes_de_icones=NOMES,
                                    origens=["fundo"] * 8)
        assert "personagem animado" in so_fundo

    def test_o_pedido_diz_onde_vai_ser_postado(self):
        pedido = ia.montar_pedido("fala", [1.0] * 8, idioma="pt", duracao=20.0, vertical=True,
                                  nomes_de_icones=NOMES, plataformas=["tiktok", "reels", "x"])
        assert "ONDE VAI SER POSTADO: TikTok" in pedido and "Instagram Reels" in pedido
        assert "cortada em cima e embaixo" in pedido
        so_youtube = ia.montar_pedido("fala", [1.0] * 8, idioma="pt", duracao=20.0,
                                      vertical=False, nomes_de_icones=NOMES,
                                      plataformas=["youtube"])
        assert "YouTube (vídeo deitado" in so_youtube and "cortada em cima" not in so_youtube
        assert "ONDE VAI SER POSTADO" not in ia.montar_pedido(
            "fala", [1.0] * 8, idioma="pt", duracao=20.0, vertical=False,
            nomes_de_icones=NOMES)

    def test_quadro_da_pessoa_e_fundo_do_fundo(self):
        def conferir(**muda):
            return ia.conferir(_variante(**muda), quadros=8, nomes_de_icones=set(NOMES),
                               origens=self.ORIGENS)

        assert conferir(quadro=2)[0] is not None
        assert conferir(quadro=5)[0] is None                     # 5 é do fundo
        assert conferir(fundo="video", quadro_fundo=6, foco=[])[0] is not None
        _, problemas = conferir(fundo="video", quadro_fundo=1, foco=[])
        assert any("4, 5, 6, 7" in p for p in problemas)          # 1 é da pessoa

    def test_com_personagem_nao_ha_rosto_e_sempre_recorta(self):
        boas, _ = ia._separar({"variantes": [_variante(quadro=3, recorte=False,
                                                       rosto=[100, 400, 300, 600])]},
                              8, set(NOMES), ["fundo"] * 8)
        assert boas[0]["recorte"] is True and boas[0]["rosto"] is None
