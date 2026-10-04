"""O plano de edição: blocos de legenda, palavra-chave, adesivos, zoom, ícones e sons."""
from __future__ import annotations

from itertools import pairwise
from typing import ClassVar

from editor import icones, plano
from editor.opcoes import OpcoesDeEdicao
from editor.transcricao import Palavra


def _palavras(texto: str, passo: float = 0.4, pausas: dict[int, float] | None = None
              ) -> list[Palavra]:
    saida, t = [], 0.0
    for i, w in enumerate(texto.split()):
        t += (pausas or {}).get(i, 0.0)
        saida.append(Palavra(w, round(t, 3), round(t + passo - 0.08, 3)))
        t += passo
    return saida


class TestOsBlocos:
    def test_cabem_no_teto(self):
        ws = _palavras("o frio atinge o céu da boca e os vasos sanguíneos reagem rápido")
        blocos = plano.montar_blocos(ws, 10.0, plano.TETO_VERTICAL)
        assert all(len(b.texto) <= plano.TETO_VERTICAL for b in blocos)
        assert " ".join(b.texto for b in blocos) == " ".join(w.texto for w in ws)

    def test_nunca_terminam_em_palavra_pendurada(self):
        ws = _palavras("a luz do sol atravessa a atmosfera e se espalha pelo céu azul")
        blocos = plano.montar_blocos(ws, 10.0, plano.TETO_VERTICAL)
        for b in blocos[:-1]:
            assert b.palavras[-1].texto.lower() not in plano.PENDURADAS, b.texto

    def test_pontuacao_e_pausa_quebram(self):
        ws = _palavras("Primeira frase. Segunda frase aqui", pausas={})
        assert plano.montar_blocos(ws, 10.0, 40)[0].texto == "Primeira frase."
        ws = _palavras("uma pausa longa aqui", pausas={2: 0.5})
        assert [b.texto for b in plano.montar_blocos(ws, 10.0, 40)] == ["uma pausa", "longa aqui"]

    def test_o_bloco_some_antes_de_uma_fala_distante(self):
        ws = [Palavra("oi", 0.0, 0.3), Palavra("tchau", 3.0, 3.3)]
        primeiro = plano.montar_blocos(ws, 5.0, 40)[0]
        assert primeiro.fim < 1.0


class TestAPalavraChave:
    def test_a_mais_longa_que_nao_e_de_servico(self):
        assert plano.chave(["o", "frio", "atinge", "porque"]) == 2

    def test_adverbio_e_vazia_nao_contam(self):
        assert plano.chave(["completamente", "seco"]) == 1
        assert plano.chave(["e", "foi", "por", "isso", "que"]) == -1


class TestOsAdesivos:
    def _blocos(self, texto, duracao=40.0):
        ws = _palavras(texto, passo=1.0)
        return plano.montar_blocos(ws, duracao, plano.TETO_HORIZONTAL)

    def test_numero_ganha_de_nome_proprio_e_de_palavra_longa(self):
        blocos = self._blocos("A empresa Nubank cobra 3 reais pela transferência internacional")
        escolhidos = plano.escolher_adesivos(blocos, 13.0)
        assert len(escolhidos) == 1
        b = blocos[escolhidos[0].bloco]
        assert b.palavras[escolhidos[0].palavra].texto == "3"

    def test_espacados_e_no_maximo_um_a_cada_doze_segundos(self):
        texto = " ".join(f"custa {i} reais" for i in range(12))
        blocos = self._blocos(texto, duracao=36.0)
        escolhidos = plano.escolher_adesivos(blocos, 36.0)
        assert len(escolhidos) == 3
        tempos = [a.inicio for a in escolhidos]
        assert all(b - a >= plano.ADESIVO_ESPACO_S for a, b in pairwise(tempos))

    def test_fica_pelo_menos_meio_segundo(self):
        for a in plano.escolher_adesivos(self._blocos("custa 30 reais e 40 centavos hoje"), 13.0):
            assert a.fim - a.inicio >= plano.ADESIVO_MINIMO_S


class TestOsIcones:
    NOMES: ClassVar[set[str]] = set(icones.nomes())

    def test_plural_sinonimo_e_acento(self):
        assert plano.casar_icone("celulares", "", self.NOMES) == "celular"
        assert plano.casar_icone("aviões", "", self.NOMES) == "aviao"
        assert plano.casar_icone("grana", "", self.NOMES) == "dinheiro"
        assert plano.casar_icone("Foguete!", "", self.NOMES) == "foguete"

    def test_o_que_nao_chama(self):
        assert plano.casar_icone("mundo", "todo", self.NOMES) == ""
        assert plano.casar_icone("certo", "", self.NOMES) == ""
        assert plano.casar_icone("de", "", self.NOMES) == ""

    def test_espacados(self):
        ws = _palavras("dinheiro celular foguete carro", passo=1.0)
        escolhidos = plano.escolher_icones(ws, 10.0, self.NOMES)
        assert [i.nome for i in escolhidos] == ["dinheiro"]
        assert escolhidos[0].fim - escolhidos[0].inicio == plano.ICONE_DURA_S


class TestZoomESons:
    def test_alterna_nos_cortes_respeitando_o_espaco(self):
        zoom = plano.montar_zoom(20.0, [1.0, 3.0, 4.0, 8.0], [], 1.12)
        assert zoom == [(0.0, 1.0), (3.0, 1.12), (8.0, 1.0)]

    def test_sons_nao_se_atropelam(self):
        adesivos = [plano.Adesivo(0, 0, 1.0, 2.0, 0)]
        icones_ = [plano.Icone("dinheiro", 1.1, 2.6, 1), plano.Icone("carro", 7.0, 8.5, -1)]
        sons = plano.montar_sons(adesivos, icones_, [(0.0, 1.0), (1.05, 1.12), (9.0, 1.0)])
        tempos = sorted(s.t for s in sons)
        assert all(b - a >= plano.SOM_ESPACO_S for a, b in pairwise(tempos))
        assert [s.nome for s in sons if s.t == 1.0] == ["pop"]

    def test_opcoes_desligadas_somem_do_plano(self):
        ws = _palavras("custa 3 reais no celular e dinheiro", passo=0.6)
        op = OpcoesDeEdicao(adesivos=False, icones=False, sons=False, zoom=False)
        p = plano.montar(ws, 6.0, vertical=True, cortes=[2.0], opcoes=op,
                         nomes_de_icones=set(icones.nomes()))
        assert not p.adesivos and not p.icones and not p.sons and p.zoom == [(0.0, 1.0)]


class TestAPessoaQueMudaDeLugar:
    """A pessoa só sai do lugar em cortes, só em alguns trechos, e sempre do mesmo jeito."""

    CORTES: ClassVar[list[float]] = [2.5, 5.0, 8.0, 10.75, 12.24, 13.55, 14.94]

    def _movimentos(self, adesivos=(), icones=(), cortes=None, duracao=18.0, vertical=True):
        return plano.montar_movimentos(duracao, cortes or self.CORTES, list(adesivos),
                                       list(icones), vertical=vertical)

    def test_comecam_em_cortes_e_respeitam_o_espaco(self):
        ms = self._movimentos(icones=[plano.Icone("dinheiro", 12.8, 14.3, -1)])
        assert ms, "nenhum movimento"
        for m in ms:
            assert m.inicio in self.CORTES
            assert m.fim - m.inicio >= plano.MOVER_MINIMO_S
        for a, b in pairwise(ms):
            assert b.inicio - a.fim >= plano.MOVER_ESPACO_S

    def test_o_icone_fica_do_lado_livre(self):
        """Com um ícone no trecho, a pessoa vai para o lado oposto ao dele."""
        ms = self._movimentos(icones=[plano.Icone("dinheiro", 12.8, 14.3, -1)])
        do_icone = next(m for m in ms if m.inicio == 12.24)
        assert do_icone.posicao == "direita"
        ms = self._movimentos(icones=[plano.Icone("dinheiro", 12.8, 14.3, 1)])
        assert next(m for m in ms if m.inicio == 12.24).posicao == "esquerda"

    def test_com_adesivo_ela_vem_para_perto(self):
        adesivo = plano.Adesivo(0, 0, 8.4, 9.5, 0)
        ms = self._movimentos(adesivos=[adesivo])
        assert next(m for m in ms if m.inicio == 8.0).posicao == "perto"

    def test_perto_nao_se_repete(self):
        """Cada trecho com um adesivo, um depois do outro: perto, e depois outra coisa."""
        cortes = [5.0, 7.0, 10.0, 12.0, 15.0, 17.0, 20.0, 22.0]
        adesivos = [plano.Adesivo(0, 0, c + 0.3, c + 1.2, 0) for c in cortes[::2]]
        ms = self._movimentos(adesivos=adesivos, cortes=cortes, duracao=26.0)
        assert [m.inicio for m in ms] == cortes[::2]
        assert all(a.posicao != b.posicao for a, b in pairwise(ms))
        assert ms[0].posicao == "perto"

    def test_sem_enfase_so_depois_de_parada(self):
        ms = self._movimentos()
        assert ms[0].inicio >= plano.MOVER_PARADA_S

    def test_trecho_longo_volta_deslizando(self):
        ms = self._movimentos(cortes=[6.0], duracao=20.0)
        assert ms == [plano.Movimento(6.0, 6.0 + plano.MOVER_MAXIMO_S, "longe", False)]

    def test_o_mesmo_video_sai_sempre_igual(self):
        icone = [plano.Icone("dinheiro", 12.8, 14.3, -1)]
        assert self._movimentos(icones=icone) == self._movimentos(icones=icone)

    def test_desligado_por_padrao_e_sem_cortes(self):
        ws = _palavras("um dois três quatro cinco seis sete oito nove dez onze doze",
                       pausas={4: 1.0, 8: 1.0})
        nomes = set(icones.nomes())
        p = plano.montar(ws, 20.0, vertical=True, cortes=self.CORTES, opcoes=OpcoesDeEdicao(),
                         nomes_de_icones=nomes)
        assert p.movimentos == []
        ligado = OpcoesDeEdicao(mover_pessoa=True)
        p = plano.montar(ws, 20.0, vertical=True, cortes=self.CORTES, opcoes=ligado,
                         nomes_de_icones=nomes)
        assert p.movimentos
        # sai do lugar com um whoosh
        whooshes = {s.t for s in p.sons if s.nome == "whoosh"}
        assert p.movimentos[0].inicio in whooshes
        sem_cortes = OpcoesDeEdicao(mover_pessoa=True, cortes=False)
        p = plano.montar(ws, 20.0, vertical=True, cortes=[], opcoes=sem_cortes,
                         nomes_de_icones=nomes)
        assert p.movimentos == []
