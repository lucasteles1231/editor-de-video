"""Os presets: valores válidos, distintos entre si, e o terminal aplicando um por baixo das
flags."""
from __future__ import annotations

from pathlib import Path

import pytest

from editor import cli, montagem, presets, render
from editor import saida as saida_mod
from editor.opcoes import OpcoesDeEdicao

MODELOS_DE_THUMB = {"classico", "numero", "pergunta", "alerta"}
CORES = {"amarelo", "rosa", "ciano", "lima", "laranja", "roxo", "vermelho"}
TAMANHOS = {"1280x720", "1080x1920", "1080x1080"}


class TestOsValores:
    @pytest.mark.parametrize("nome", list(presets.PRESETS))
    def test_cada_preset_e_valido(self, nome):
        p = presets.PRESETS[nome]
        assert p.opcoes().problemas() == []
        assert set(p.edicao) == set(presets.EDICAO) and set(p.saida) == set(presets.SAIDA)
        assert p.saida["resolucao"] in saida_mod.RESOLUCOES and p.saida["fps"] in saida_mod.FPS
        assert p.saida["qualidade"] in saida_mod.QUALIDADES
        assert p.quadro in montagem.FORMATOS
        assert p.thumb["modelo"] in MODELOS_DE_THUMB and p.thumb["cor"] in CORES
        assert p.thumb["tamanhos"] and set(p.thumb["tamanhos"]) <= TAMANHOS
        assert p.titulo and p.frase

    def test_o_padrao_e_o_de_sempre(self):
        """A página abre marcando o Padrão: ele precisa bater com as opções sem escolha."""
        padrao = OpcoesDeEdicao().para_dict()
        assert presets.PRESETS["padrao"].edicao == {k: padrao[k] for k in presets.EDICAO}
        assert presets.PRESETS["padrao"].saida == {k: getattr(saida_mod.OpcoesDeSaida(), k)
                                                   for k in presets.SAIDA}

    def test_dois_presets_nunca_sao_iguais(self):
        """A página marca o primeiro que bate: dois iguais confundiriam a marca."""
        vistos = [(tuple(p.edicao.items()), tuple(p.saida.items()))
                  for p in presets.PRESETS.values()]
        assert len(set(vistos)) == len(vistos)

    def test_o_json_da_pagina(self):
        lista = presets.para_json()
        assert [p["nome"] for p in lista] == list(presets.PRESETS)
        assert lista[1]["edicao"]["tema_dos_sons"] == "gameplay"


class TestNoTerminal:
    @pytest.fixture
    def pedido(self, monkeypatch, tmp_path):
        """Roda o ``editar`` sem editar: guarda as opções que chegariam no render."""
        visto = {}

        def falso(entrada, destino, edicao, saida, **kw):
            visto.update(edicao=edicao, saida=saida, montagem=kw.get("montagem"))
            raise SystemExit(0)

        monkeypatch.setattr(render, "editar", falso)
        video = tmp_path / "eu.mp4"
        video.write_bytes(b"x")

        def rodar(*flags: str):
            with pytest.raises(SystemExit):
                cli.main([str(video), *flags])
            return visto

        return rodar

    def test_sem_preset_vale_o_padrao(self, pedido):
        v = pedido()
        assert v["edicao"].tema_dos_sons == "padrao" and v["edicao"].ritmo == 1.0
        assert v["saida"].fps == "original"

    def test_o_preset_aplica(self, pedido):
        v = pedido("--preset", "gameplay")
        e = v["edicao"]
        assert (e.tema_dos_sons, e.ritmo, e.som_nos_cortes, e.caracteres_por_linha) == (
            "gameplay", 1.5, True, 14)
        assert v["saida"].fps == "60"

    def test_a_flag_ganha_do_preset(self, pedido):
        v = pedido("--preset", "gameplay", "--ritmo", "1.2", "--fps", "30",
                   "--sem-som-nos-cortes", "--sem-zoom", "--idioma", "en")
        e = v["edicao"]
        assert (e.ritmo, e.som_nos_cortes, e.zoom, e.idioma) == (1.2, False, False, "en")
        assert e.tema_dos_sons == "gameplay" and v["saida"].fps == "30"

    def test_o_preset_que_para_a_pessoa_pode_voltar_a_mover(self, pedido):
        assert pedido("--preset", "podcast")["edicao"].mover is False
        assert pedido("--preset", "podcast", "--mover")["edicao"].mover is True

    def test_valor_fora_do_limite_volta_com_o_motivo(self, tmp_path, capsys):
        video = tmp_path / "eu.mp4"
        video.write_bytes(b"x")
        assert cli.main([str(video), "--ritmo", "3"]) == 2
        assert "ritmo" in capsys.readouterr().err

    def test_lista_os_presets(self, capsys):
        assert cli.main(["--presets"]) == 0
        saida = capsys.readouterr().out
        for p in presets.PRESETS.values():
            assert p.nome in saida and p.titulo in saida

    def test_preset_sem_video_explica(self, capsys):
        assert cli.main(["--preset", "gameplay"]) == 2       # e não abre a página
        assert "faltou o vídeo" in capsys.readouterr().err


def test_o_quadro_do_preset_vale_na_montagem(monkeypatch, tmp_path):
    visto = {}

    def falso(entrada, destino, edicao, saida, **kw):
        visto["montagem"] = kw.get("montagem")
        raise SystemExit(0)

    monkeypatch.setattr(render, "editar", falso)
    fundo, eu = Path(tmp_path / "fundo.mp4"), Path(tmp_path / "eu.mov")
    fundo.write_bytes(b"x")
    eu.write_bytes(b"x")
    monkeypatch.setattr("editor.video.tem_alfa", lambda c: True)
    with pytest.raises(SystemExit):
        cli.main([str(eu), "--fundo", str(fundo), "--preset", "aula"])
    assert visto["montagem"].formato == "horizontal"
    with pytest.raises(SystemExit):
        cli.main([str(eu), "--fundo", str(fundo), "--preset", "aula", "--quadro", "quadrado"])
    assert visto["montagem"].formato == "quadrado"
