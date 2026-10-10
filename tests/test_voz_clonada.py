"""
"Minha voz": o texto de leitura, a conferência de cada parágrafo (a leitura, o volume, o
som estourado e o ruído), a leitura inteira dividida em parágrafos, a escolha da
referência, as vozes salvas, a narração (com o motor falso) e a legenda com a grafia do
roteiro. A transcrição é a falsa do conftest, que "ouve" a leitura perfeita; os testes
de leitura errada trocam o que foi ouvido.
"""
from __future__ import annotations

import json
import wave
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest

from editor import render, transcricao, voz_clonada
from editor.opcoes import OpcoesDeEdicao
from editor.transcricao import Palavra
from editor.voz_clonada import Medidas, Paragrafo

TAXA = voz_clonada.TAXA


def _fala(segundos: float, *, volume: float = 0.3, ruido: float = 0.0, semente: int = 0
          ) -> np.ndarray:
    """Uma "fala": rajadas de tom (0,4 s) com pausas curtas (0,15 s) entre elas."""
    t = np.arange(round(segundos * TAXA)) / TAXA
    x = volume * np.sin(2 * np.pi * 180 * t) * ((t % 0.55) < 0.4)
    if ruido:
        x = x + ruido * np.random.default_rng(semente).standard_normal(len(t))
    return x.astype(np.float32)


def _wav(caminho: Path, x: np.ndarray) -> Path:
    with wave.open(str(caminho), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TAXA)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return caminho


def _leitura(caminho: Path, paragrafos: int, segundos: float = 6.0) -> Path:
    """A leitura inteira: um bloco de fala por parágrafo, com 1 s de pausa entre eles."""
    pausa = np.zeros(TAXA, np.float32)
    partes = []
    for k in range(paragrafos):
        partes += [pausa, _fala(segundos, semente=k)]
    return _wav(caminho, np.concatenate([*partes, pausa]))


class TestOTexto:
    def test_a_autorizacao_com_o_nome_vem_primeiro(self):
        p = voz_clonada.texto_de_leitura("Ana Lúcia")
        assert p[0].startswith("Eu, Ana Lúcia, autorizo")
        assert len(p) >= 8 and all("{nome}" not in x for x in p)
        assert any("?" in x for x in p[1:]) and any("!" in x for x in p[1:])
        palavras = sum(len(x.split()) for x in p)
        assert 220 <= palavras <= 340                   # ~2 minutos lidos com calma

    @pytest.mark.parametrize("nome", ["", "   ", "Ana2", "a" * 41, "Ana; DROP", "{nome}"])
    def test_nomes_recusados(self, nome):
        with pytest.raises(voz_clonada.VozInvalida):
            voz_clonada.nome_valido(nome)

    def test_nomes_aceitos(self):
        assert voz_clonada.nome_valido("  João  da   Silva ") == "João da Silva"
        assert voz_clonada.nome_valido("D'Ávila-Souza") == "D'Ávila-Souza"
        assert voz_clonada.apelido("João da Silva") == "joao-da-silva"


class TestACobertura:
    def test_numeros_por_extenso_dos_dois_lados(self):
        esperado = "Ontem custava três mil e quinhentos reais, e hoje 15% menos."
        ouvido = "Ontem custava 3.500 reais, e hoje quinze por cento menos."
        assert voz_clonada.cobertura(esperado, ouvido)[0] == 1.0

    def test_o_que_faltou(self):
        fracao, faltaram = voz_clonada.cobertura("o milho, a farinha e o queijo",
                                                 "o milho e o queijo")
        assert fracao == pytest.approx(5 / 7) and faltaram == ["a", "farinha"]

    @pytest.mark.parametrize(("n", "texto"), [
        (0, "zero"), (16, "dezesseis"), (21, "vinte e um"), (100, "cem"), (101, "cento e um"),
        (1000, "mil"), (1500, "mil e quinhentos"), (2023, "dois mil e vinte e três"),
        (1230, "mil duzentos e trinta"), (3500, "três mil e quinhentos"),
        (203_000_000, "duzentos e três milhões"), (1_000_000, "um milhão"),
    ])
    def test_por_extenso(self, n, texto):
        assert transcricao.por_extenso(n) == texto


class TestAConferencia:
    TEXTO = "Você já reparou como as coisas mudam rápido? Vale a pena?"

    def test_a_leitura_boa_passa(self):
        p = voz_clonada.conferir_paragrafo(2, self.TEXTO, _fala(4), self.TEXTO)
        assert p.estado == "ok" and p.motivos == [] and p.cobertura == 1.0
        assert p.medidas.lufs > -30 and 40 < p.medidas.snr_db <= 90

    def test_a_leitura_pela_metade(self):
        p = voz_clonada.conferir_paragrafo(2, self.TEXTO, _fala(4), "Você já reparou como")
        assert p.estado == "refazer" and "Não ouvi o texto inteiro" in p.motivos[0]
        assert "rapido" in p.faltaram

    @pytest.mark.parametrize(("x", "trecho"), [
        (_fala(4, volume=0.002), "baixo demais"),
        (_fala(4, volume=1.5), "estourou"),
        (_fala(4, ruido=0.05), "ruído de fundo"),
        (_fala(0.8), "curta demais"),
    ])
    def test_o_som(self, x, trecho):
        p = voz_clonada.conferir_paragrafo(2, self.TEXTO, x, self.TEXTO)
        assert p.estado == "refazer" and any(trecho in m for m in p.motivos), p.motivos

    def test_a_autorizacao_precisa_ser_lida(self):
        texto = voz_clonada.texto_de_leitura("Ana")[0]
        sem = voz_clonada.conferir_paragrafo(0, texto, _fala(5), texto.replace("autorizo", "acho"))
        assert any("autorização" in m for m in sem.motivos)
        com = voz_clonada.conferir_paragrafo(0, texto, _fala(5), texto)
        assert com.estado == "ok"

    def test_os_limites_vieram_das_gravacoes_reais(self):
        # as do dono, a −31 a −36 LUFS e 26 a 30 dB acima do ruído, deram um clone bom
        real = Medidas(9.4, -35.9, 26.2, 0.0)
        assert real.problemas() == []


class TestAGravacao:
    def test_paragrafo_a_paragrafo(self, tmp_path):
        g = voz_clonada.Gravacao("Ana", tmp_path / "g")
        n = len(g.textos)
        for i in range(n):
            # com 0,5 s de silêncio nas pontas, que saem
            x = np.concatenate([np.zeros(TAXA // 2), _fala(4, semente=i), np.zeros(TAXA // 2)])
            p = g.receber_paragrafo(i, _wav(tmp_path / f"{i}.wav", x))
            assert p.estado == "ok", p.motivos
            assert p.medidas.segundos == pytest.approx(4.2, abs=0.1)
        assert g.pronta() and g.para_dict()["pronta"]

    def test_regravar_so_um(self, tmp_path, monkeypatch):
        g = voz_clonada.Gravacao("Ana", tmp_path / "g")
        real = voz_clonada.ouvir
        monkeypatch.setattr(voz_clonada, "ouvir", lambda c, e: real(c, e)[:3])
        assert g.receber_paragrafo(3, _wav(tmp_path / "a.wav", _fala(5))).estado == "refazer"
        monkeypatch.setattr(voz_clonada, "ouvir", real)
        assert g.receber_paragrafo(3, _wav(tmp_path / "b.wav", _fala(5))).estado == "ok"
        assert not g.pronta()                            # os outros ainda faltam

    def test_a_leitura_inteira_num_arquivo(self, tmp_path):
        g = voz_clonada.Gravacao("Ana", tmp_path / "g")
        g.receber_leitura(_leitura(tmp_path / "leitura.wav", len(g.textos)))
        assert all(p.estado == "ok" for p in g.paragrafos), [p.motivos for p in g.paragrafos]
        assert all(g.wav(i).is_file() for i in range(len(g.textos)))

    def test_arquivo_sem_audio(self, tmp_path):
        g = voz_clonada.Gravacao("Ana", tmp_path / "g")
        ruim = tmp_path / "nada.wav"
        ruim.write_bytes(b"isto nao e audio")
        with pytest.raises(voz_clonada.VozInvalida):
            g.receber_leitura(ruim)


class TestADivisao:
    def test_o_corte_cai_no_meio_da_pausa(self):
        x = np.zeros(8 * TAXA, np.float32)
        x[: 2 * TAXA] = _fala(2)
        x[4 * TAXA: 6 * TAXA] = _fala(2)
        palavras = [Palavra("Custava", 0.1, 0.6), Palavra("3.500", 0.7, 1.9),
                    Palavra("Que", 4.0, 4.4), Palavra("notícia!", 4.5, 5.9),
                    Palavra("hã", 6.5, 6.7)]          # o "hã" do fim fica com o último
        trechos = voz_clonada.dividir(x, palavras, ["Custava três mil e quinhentos.",
                                                    "Que notícia!", "Vale a pena?"])
        (a, ouvido_a), (b, ouvido_b), (c, ouvido_c) = trechos
        assert ouvido_a == "Custava 3.500" and ouvido_b == "Que notícia! hã"
        assert len(c) == 0 and ouvido_c == ""            # o terceiro não foi lido
        # o corte entre os dois foi em ~2,95 s: o primeiro trecho tem a fala dele inteira
        assert 1.9 < len(a) / TAXA < 2.4 and 1.9 < len(b) / TAXA < 2.4


def _paragrafo(i: int, texto: str, segundos: float, cobertura: float = 1.0, snr: float = 30.0,
               estado: str = "ok") -> Paragrafo:
    return Paragrafo(i, texto, estado, [], cobertura, texto, [], Medidas(segundos, -20, snr, 0))


class TestAReferencia:
    def test_uns_25_segundos_com_uma_pergunta(self):
        ps = [_paragrafo(0, "Eu autorizo.", 8),
              _paragrafo(1, "Uma história.", 12, snr=35),
              _paragrafo(2, "Mudam rápido? Vale a pena?", 12, snr=20),
              _paragrafo(3, "A receita.", 12, snr=34),
              _paragrafo(4, "Que notícia!", 12, snr=33)]
        escolhidos = voz_clonada.escolher_referencia(ps)
        # os dois melhores seriam 1 e 3; a pergunta entra no lugar do segundo
        assert escolhidos == [1, 2]

    def test_sem_passar_do_teto(self):
        ps = [_paragrafo(i, f"Frase {i}?", 15) for i in range(1, 6)]
        escolhidos = voz_clonada.escolher_referencia(ps)
        assert len(escolhidos) == 2                       # 30 s; um terceiro passaria de 35

    def test_os_reprovados_e_a_autorizacao_ficam_de_fora(self):
        ps = [_paragrafo(0, "Eu autorizo?", 30), _paragrafo(1, "Uma?", 10, estado="refazer"),
              _paragrafo(2, "Duas.", 10)]
        assert voz_clonada.escolher_referencia(ps) == [2]


@pytest.fixture
def voz_salva(tmp_path) -> dict:
    g = voz_clonada.Gravacao("Ana Lúcia", tmp_path / "g")
    g.receber_leitura(_leitura(tmp_path / "leitura.wav", len(g.textos)))
    return voz_clonada.salvar(g)


class TestAsVozesSalvas:
    def test_salvar_e_listar(self, voz_salva):
        assert voz_salva["apelido"] == "ana-lucia" and voz_salva["nome"] == "Ana Lúcia"
        assert [v["apelido"] for v in voz_clonada.vozes()] == ["ana-lucia"]
        dados = voz_clonada.ler_voz("ana-lucia")
        assert "?" in dados["referencia"]["texto"]
        assert 18 <= dados["referencia"]["segundos"] <= voz_clonada.REFERENCIA_TETO_S
        assert dados["autorizacao"]["texto"].startswith("Eu, Ana Lúcia, autorizo")
        ref = voz_clonada.referencia("ana-lucia")
        x = render.video_mod.ler_audio_mono(ref, TAXA)
        assert voz_clonada.voz.lufs(x) == pytest.approx(voz_clonada.REFERENCIA_LUFS, abs=1.5)

    def test_sem_a_leitura_aprovada_nao_salva(self, tmp_path):
        g = voz_clonada.Gravacao("Ana", tmp_path / "g")
        with pytest.raises(voz_clonada.VozInvalida, match="regravar"):
            voz_clonada.salvar(g)

    def test_a_pronuncia_fica_na_voz(self, voz_salva):
        lista = voz_clonada.ler_pronuncia("PEGI = pégui\nGTA → gê tê á\nlixo\n: nada")
        assert lista == {"PEGI": "pégui", "GTA": "gê tê á"}
        assert voz_clonada.salvar_pronuncia("ana-lucia", lista)["pronuncia"] == lista
        assert voz_clonada.vozes()[0]["pronuncia"] == lista

    def test_apagar(self, voz_salva):
        voz_clonada.apagar("ana-lucia")
        assert voz_clonada.vozes() == []
        with pytest.raises(voz_clonada.VozInvalida):
            voz_clonada.ler_voz("ana-lucia")

    @pytest.mark.parametrize("slug", ["../fora", "a/b", "", "ANA"])
    def test_nome_de_pasta_estranho(self, slug):
        with pytest.raises(voz_clonada.VozInvalida):
            voz_clonada.ler_voz(slug)


class TestANarracao:
    ROTEIRO = ("A Rockstar confirmou: o PEGI deu 18 anos. Ninguém esperava!\n\n"
               "E aí, tá certa ou passou do ponto? Comenta aí.")

    def test_os_pedacos(self):
        assert voz_clonada.pedacos(self.ROTEIRO) == [
            ["A Rockstar confirmou: o PEGI deu 18 anos. Ninguém esperava!"],
            ["E aí, tá certa ou passou do ponto? Comenta aí."]]
        longa = "palavra, " * 60 + "fim."
        partes = voz_clonada.pedacos(longa)[0]
        assert len(partes) > 1 and all(len(p) <= voz_clonada.PEDACO_MAXIMO for p in partes)
        assert " ".join(partes).split() == longa.split()

    def test_a_pronuncia_troca_a_palavra_inteira(self):
        lista = {"PEGI": "pégui", "GTA": "gê tê á"}
        assert voz_clonada.aplicar_pronuncia("o pegi do GTA, não do GTAX", lista) == \
            "o pégui do gê tê á, não do GTAX"

    def test_narra_e_guarda(self, voz_salva, tmp_path):
        visto = []
        n = voz_clonada.narrar("ana-lucia", self.ROTEIRO, tmp_path / "n.wav",
                               progresso=lambda f, t: visto.append((f, t)))
        assert n.pedacos == 2 and n.reaproveitados == 0 and visto[-1] == (2, 2)
        x = render.video_mod.ler_audio_mono(n.caminho, TAXA)
        assert voz_clonada.voz.lufs(x) == pytest.approx(voz_clonada.voz.FINAL_LUFS, abs=1.0)
        # o roteiro ao lado, sem a troca da pronúncia
        assert transcricao.texto_ao_lado(n.caminho) == self.ROTEIRO
        # de novo: tudo do cache; outra pronúncia muda só o pedaço que tem a palavra
        assert voz_clonada.narrar("ana-lucia", self.ROTEIRO, tmp_path / "m.wav"
                                  ).reaproveitados == 2
        assert voz_clonada.narrar("ana-lucia", self.ROTEIRO, tmp_path / "o.wav",
                                  pronuncia={"PEGI": "pégui"}).reaproveitados == 1

    def test_roteiro_vazio_ou_voz_que_nao_existe(self, voz_salva, tmp_path):
        with pytest.raises(voz_clonada.VozInvalida, match="vazio"):
            voz_clonada.narrar("ana-lucia", "  \n ", tmp_path / "n.wav")
        with pytest.raises(voz_clonada.VozInvalida):
            voz_clonada.narrar("outra", "Oi.", tmp_path / "n.wav")


class TestALegendaComOTexto:
    def test_a_grafia_do_texto_nos_tempos_ouvidos(self):
        ouvidas = [Palavra("o", 0.0, 0.1), Palavra("Peggy", 0.2, 0.6), Palavra("deu", 0.7, 0.9),
                   Palavra("18", 1.0, 1.3), Palavra("anos.", 1.4, 1.8)]
        ajustadas = transcricao.ajustar_ao_texto(ouvidas, "O PEGI deu dezoito anos!")
        assert [p.texto for p in ajustadas] == ["O", "PEGI", "deu", "dezoito", "anos!"]
        assert (ajustadas[1].inicio, ajustadas[1].fim) == (0.1, 0.7)   # entre as vizinhas
        assert (ajustadas[3].inicio, ajustadas[3].fim) == (1.0, 1.3)

    def test_o_numero_ouvido_divide_o_tempo(self):
        ouvidas = [Palavra("custava", 0.0, 0.5), Palavra("3.500", 0.6, 1.8)]
        ajustadas = transcricao.ajustar_ao_texto(ouvidas, "custava três mil e quinhentos")
        tempos = [(p.inicio, p.fim) for p in ajustadas[1:]]
        assert tempos[0][0] == 0.6 and tempos[-1][1] == 1.8
        assert all(a < b for a, b in tempos) and all(
            b1 <= a2 + 1e-9 for (_a1, b1), (a2, _b2) in pairwise(tempos))

    def test_outro_texto_nao_mexe(self):
        ouvidas = [Palavra("uma", 0.0, 0.3), Palavra("coisa", 0.4, 0.8)]
        assert transcricao.ajustar_ao_texto(ouvidas, "nada a ver com isso aqui") == ouvidas

    def test_a_transcricao_le_o_roteiro_ao_lado(self, tmp_path):
        from tests.conftest import fazer_video

        audio = fazer_video(tmp_path / "narracao.mp4", segundos=4.0)
        # o transcritor falso diz "Hoje eu vou mostrar como funciona o editor."
        audio.with_suffix(".roteiro.txt").write_text("Hoje EU vou mostrar como funciona o "
                                                      "EDITOR!", encoding="utf-8")
        palavras = render.obter_palavras(audio, 4.0, OpcoesDeEdicao(), lambda *a: None)
        assert [p.texto for p in palavras[:8]] == ["Hoje", "EU", "vou", "mostrar", "como",
                                                   "funciona", "o", "EDITOR!"]
        # a transcrição guardada continua a do Whisper; o ajuste vale de novo na volta
        de_novo = render.obter_palavras(audio, 4.0, OpcoesDeEdicao(), lambda *a: None)
        assert de_novo[1].texto == "EU"
        guardadas = [json.loads(c.read_text()) for c in render.pasta_de_cache().glob("*.json")]
        assert guardadas[0]["palavras"][1]["texto"] == "eu"


class TestOTerminal:
    def test_criar_listar_e_narrar(self, tmp_path, capsys):
        from editor import cli

        assert cli.main(["--criar-voz", "Ana"]) == 0
        texto = capsys.readouterr().out
        assert "Eu, Ana, autorizo" in texto and "--gravacao" in texto
        leitura = _leitura(tmp_path / "leitura.wav", len(voz_clonada.texto_de_leitura("Ana")))
        assert cli.main(["--criar-voz", "Ana", "--gravacao", str(leitura)]) == 0
        assert "--minha-voz ana" in capsys.readouterr().out
        assert cli.main(["--vozes"]) == 0
        assert "ana" in capsys.readouterr().out
        roteiro = tmp_path / "roteiro.txt"
        roteiro.write_text("O PEGI deu 18. Comenta aí!", encoding="utf-8")
        assert cli.main(["--minha-voz", "Ana", "--roteiro", str(roteiro),
                         "--pronuncia", "PEGI=pégui; GTA=gê tê á"]) == 0
        assert (tmp_path / "roteiro-narrado.wav").is_file()
        assert transcricao.texto_ao_lado(tmp_path / "roteiro-narrado.wav") == \
            "O PEGI deu 18. Comenta aí!"

    def test_a_leitura_com_problema_nao_salva(self, tmp_path, capsys, monkeypatch):
        from editor import cli

        monkeypatch.setattr(voz_clonada, "ouvir", lambda c, e: [])
        leitura = _leitura(tmp_path / "leitura.wav", 9)
        assert cli.main(["--criar-voz", "Ana", "--gravacao", str(leitura)]) == 1
        assert "REGRAVAR" in capsys.readouterr().out and voz_clonada.vozes() == []

    def test_o_motor_ja_instalado_e_os_erros(self, tmp_path, capsys):
        from editor import cli

        assert cli.main(["--instalar-voz"]) == 0
        assert "já está instalada" in capsys.readouterr().out
        assert cli.main(["--minha-voz", "ninguem", "--roteiro", str(tmp_path / "x.txt")]) == 2
        assert "--roteiro" in capsys.readouterr().err
        assert cli.main(["--criar-voz", "R2D2"]) == 2
