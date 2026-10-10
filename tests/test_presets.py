"""Os presets: valores válidos, distintos entre si, e o terminal aplicando um por baixo das
flags."""
from __future__ import annotations

from pathlib import Path

import pytest

from editor import cli, presets, render
from editor import saida as saida_mod
from editor.opcoes import OpcoesDeEdicao

MODELOS_DE_THUMB = {"classico", "numero", "pergunta", "alerta"}
CORES = {"amarelo", "rosa", "ciano", "lima", "laranja", "roxo", "vermelho"}


class TestOsValores:
    @pytest.mark.parametrize("nome", list(presets.PRESETS))
    def test_cada_preset_e_valido(self, nome):
        p = presets.PRESETS[nome]
        assert p.opcoes().problemas() == []
        assert set(p.edicao) == set(presets.EDICAO) and set(p.saida) == set(presets.SAIDA)
        assert p.saida["resolucao"] in saida_mod.RESOLUCOES and p.saida["fps"] in saida_mod.FPS
        assert p.saida["qualidade"] in saida_mod.QUALIDADES
        # O formato (o quadro da montagem e o tamanho da thumbnail) vem da plataforma.
        assert set(p.thumb) == {"modelo", "cor"}
        assert p.thumb["modelo"] in MODELOS_DE_THUMB and p.thumb["cor"] in CORES
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


def test_o_preset_nao_muda_o_formato_da_montagem(monkeypatch, tmp_path):
    """O formato vem da plataforma (na página) ou do --quadro: o preset só muda o estilo."""
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
    assert visto["montagem"].formato == "fundo"
    with pytest.raises(SystemExit):
        cli.main([str(eu), "--fundo", str(fundo), "--preset", "aula", "--quadro", "vertical"])
    assert visto["montagem"].formato == "vertical"


def _meu(titulo="Meu vlog", **edicao) -> dict:
    """Um preset como a página manda: as edições inteiras da tela."""
    base = presets.PRESETS["vlog"]
    return {"titulo": titulo, "frase": "O vlog do meu jeito.", "edicao": {**base.edicao, **edicao},
            "saida": dict(base.saida), "thumb": {"modelo": "pergunta", "cor": "roxo"}}


class TestOsMeus:
    """Os presets de quem usa: no presets.json da pasta de dados (a do teste, no conftest)."""

    def test_salvar_listar_e_usar(self):
        p = presets.salvar(_meu(ritmo=1.4))
        assert (p.nome, p.meu) == ("meu-vlog", True)
        assert presets.arquivo_dos_meus().is_file()
        todos = presets.todos()
        assert list(todos)[: len(presets.PRESETS)] == list(presets.PRESETS)   # os prontos antes
        assert todos["meu-vlog"].edicao["ritmo"] == 1.4
        assert todos["meu-vlog"].opcoes().problemas() == []
        pagina = {d["nome"]: d for d in presets.para_json()}
        assert pagina["meu-vlog"]["meu"] is True and pagina["padrao"]["meu"] is False

    def test_o_mesmo_nome_so_com_substituir(self):
        presets.salvar(_meu(ritmo=1.4))
        with pytest.raises(presets.PresetJaExiste):
            presets.salvar(_meu("meu  VLOG", ritmo=1.1))
        presets.salvar(_meu("meu  VLOG", ritmo=1.1), substituir=True)
        assert len(presets.meus()) == 1 and presets.meus()[0].edicao["ritmo"] == 1.1

    @pytest.mark.parametrize(("dados", "trecho"), [
        (_meu(""), "Dê um nome"),
        (_meu("Padrão"), "preset pronto"),
        (_meu("x" * 41), "40 letras"),
        (_meu("!!!"), "letra ou um número"),
        (_meu(ritmo=9.0), "ritmo"),
        (_meu(cortes="sim"), "cortes"),
        (_meu(tema_dos_sons="nenhum"), "tema de sons"),
        ({**_meu(), "saida": {"resolucao": "8k"}}, "saída"),
        ({**_meu(), "thumb": {"modelo": "outro", "cor": "rosa"}}, "thumbnail"),
        ("não é um preset", "não é um preset"),
    ])
    def test_o_que_e_recusado(self, dados, trecho):
        with pytest.raises(presets.PresetInvalido, match=trecho):
            presets.salvar(dados)
        assert presets.meus() == []

    def test_apagar(self):
        presets.salvar(_meu())
        presets.apagar("meu-vlog")
        assert presets.meus() == []
        with pytest.raises(presets.PresetInvalido):
            presets.apagar("padrao")                    # um pronto não se apaga

    def test_arquivo_estragado_nao_derruba(self):
        presets.arquivo_dos_meus().parent.mkdir(parents=True, exist_ok=True)
        presets.arquivo_dos_meus().write_text("{ isto não é json", encoding="utf-8")
        assert presets.meus() == [] and list(presets.todos()) == list(presets.PRESETS)

    def test_exportar_e_importar_em_outro_computador(self, monkeypatch, tmp_path):
        presets.salvar(_meu(ritmo=1.4))
        presets.salvar(_meu("Aula rápida", ritmo=0.9, voz="estudio"))
        arquivo = presets.exportar()
        assert arquivo["editor-de-video"] == "presets" and len(arquivo["presets"]) == 2
        # o outro computador: outra pasta de dados, com um preset que tem o mesmo nome
        outra = tmp_path / "outro-computador"
        outra.mkdir()
        monkeypatch.setattr("editor.ia.pasta_de_dados", lambda: outra)
        presets.salvar(_meu(ritmo=0.6))
        estragado = {"titulo": "Quebrado", "edicao": {"ritmo": "rápido"}}
        entraram, recusados = presets.importar(
            {**arquivo, "presets": [*arquivo["presets"], estragado]})
        assert entraram == ["Meu vlog", "Aula rápida"]
        assert len(recusados) == 1 and recusados[0].startswith("Quebrado:")
        meus = {p.nome: p for p in presets.meus()}
        assert meus["meu-vlog"].edicao["ritmo"] == 1.4          # o importado substitui
        assert meus["aula-rapida"].edicao["voz"] == "estudio"

    def test_importar_o_que_nao_e_preset(self):
        with pytest.raises(presets.PresetInvalido, match="não tem presets"):
            presets.importar({"cenas": []})

    def test_o_teto(self, monkeypatch):
        monkeypatch.setattr(presets, "TETO", 2)
        presets.salvar(_meu("Um"))
        presets.salvar(_meu("Dois"))
        with pytest.raises(presets.PresetInvalido, match="Cabem até 2"):
            presets.salvar(_meu("Três"))


class TestOsMeusNoTerminal:
    def test_salvar_pelo_terminal_e_usar(self, capsys, tmp_path, monkeypatch):
        assert cli.main(["--preset", "gameplay", "--ritmo", "1.3", "--qualidade", "leve",
                         "--salvar-preset", "Meu gameplay", "--frase", "Gameplay mais calmo"]) == 0
        assert "--preset meu-gameplay" in capsys.readouterr().out
        p = presets.todos()["meu-gameplay"]
        assert p.edicao["ritmo"] == 1.3 and p.edicao["tema_dos_sons"] == "gameplay"
        assert p.saida == {**presets.PRESETS["gameplay"].saida, "qualidade": "leve"}
        assert p.frase == "Gameplay mais calmo"
        assert cli.main(["--presets"]) == 0
        assert "meu-gameplay  Meu gameplay  (seu)" in capsys.readouterr().out
        # o --preset aceita o seu (o parser lê a lista na hora)
        a = cli.argumentos().parse_args(["video.mp4", "--preset", "meu-gameplay"])
        assert a.preset == "meu-gameplay"

    def test_nome_de_um_pronto_e_recusado(self, capsys):
        assert cli.main(["--salvar-preset", "Humor"]) == 2
        assert "preset pronto" in capsys.readouterr().err
