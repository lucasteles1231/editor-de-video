"""O bloqueio do Windows 11 (Controle Inteligente de Aplicativos) vira uma explicação, no
terminal e na edição que falhou."""
from __future__ import annotations

import time

import pytest

from editor import bloqueio, cli, render
from editor.opcoes import OpcoesDeEdicao
from editor.saida import OpcoesDeSaida
from editor.tarefas import Gerente, Tarefa

#: O erro como saiu no Windows 11 em português (04/10/2026).
DO_WINDOWS = ("DLL load failed while importing logging: Uma política de Controle de "
              "Aplicativo bloqueou este arquivo.")


def _barrado():
    raise ImportError(DO_WINDOWS)


class TestReconhecer:
    def test_em_portugues_e_em_ingles(self):
        assert bloqueio.bloqueado(ImportError(DO_WINDOWS))
        assert bloqueio.bloqueado(ImportError(
            "DLL load failed while importing _ext: An Application Control policy has "
            "blocked this file."))

    def test_pelo_codigo(self):
        erro = OSError("qualquer texto")
        erro.winerror = bloqueio.CODIGO
        assert bloqueio.bloqueado(erro)

    def test_outros_erros_nao(self):
        assert not bloqueio.bloqueado(ImportError("No module named 'av'"))
        assert not bloqueio.bloqueado(ImportError(
            "DLL load failed while importing _ext: Não foi possível encontrar o módulo "
            "especificado."))                        # o do Visual C++, que tem outra saída

    def test_a_explicacao_diz_o_caminho_e_o_erro(self):
        texto = bloqueio.explicar(ImportError(DO_WINDOWS))
        assert "Controle Inteligente de Aplicativos" in texto and "Desligado" in texto
        assert DO_WINDOWS in texto


class TestNoTerminal:
    def test_explica_e_sai(self, monkeypatch, capsys):
        monkeypatch.setattr(bloqueio, "_carregar", _barrado)
        assert cli.main(["--presets"]) == 1
        erro = capsys.readouterr().err
        assert "Controle Inteligente de Aplicativos" in erro and "Traceback" not in erro

    def test_outro_erro_de_importacao_sobe(self, monkeypatch):
        def outro():
            raise ImportError("No module named 'av'")

        monkeypatch.setattr(bloqueio, "_carregar", outro)
        with pytest.raises(ImportError):
            cli.main(["--presets"])

    def test_sem_bloqueio_segue(self, capsys):
        assert cli.main(["--presets"]) == 0
        assert "gameplay" in capsys.readouterr().out


def test_a_edicao_que_falha_pelo_bloqueio_explica(monkeypatch, tmp_path):
    """O Whisper só carrega na hora de transcrever: se o Windows barrar o dele, a página
    recebe a explicação, e não o erro cru."""
    def falso(*a, **kw):
        raise ImportError(DO_WINDOWS)

    monkeypatch.setattr(render, "editar", falso)
    t = Gerente().iniciar(Tarefa(tmp_path / "v.mp4", tmp_path / "v-editado.mp4",
                                 OpcoesDeEdicao(), OpcoesDeSaida()))
    fim = time.monotonic() + 5
    while t.estado == "rodando" and time.monotonic() < fim:
        time.sleep(0.02)
    assert t.estado == "erro"
    assert t.erro.startswith("O Windows bloqueou") and DO_WINDOWS in t.erro
