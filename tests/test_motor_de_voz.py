"""
O motor da voz sintetizada: o falso (dos outros testes), os passos da instalação (com os
comandos simulados), a conversa por subprocesso (com um script de mentira no lugar do
modelo) e o script do motor, que roda no ambiente dele.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import textwrap
import wave
from pathlib import Path

import pytest

from editor import motor_de_voz


def _duracao(caminho: Path) -> float:
    with wave.open(str(caminho)) as w:
        return w.getnframes() / w.getframerate()


class TestOFalso:
    def test_instalado_e_um_tom_por_frase(self, tmp_path):
        assert motor_de_voz.instalado() and motor_de_voz.estado()["falso"]
        visto = []
        frases = [("Oi.", tmp_path / "a.wav"), ("Uma frase bem mais comprida.", tmp_path / "b.wav")]
        assert motor_de_voz.sintetizar(tmp_path / "ref.wav", "ref", frases,
                                       progresso=lambda f, t: visto.append((f, t))) == "falso"
        assert visto == [(1, 2), (2, 2)]
        assert _duracao(tmp_path / "a.wav") < _duracao(tmp_path / "b.wav")


@pytest.fixture
def de_verdade(monkeypatch):
    monkeypatch.delenv(motor_de_voz.VARIAVEL_FALSA, raising=False)


class TestAInstalacao:
    def test_os_passos_com_o_uv(self, de_verdade, monkeypatch):
        monkeypatch.setattr(motor_de_voz, "achar_uv", lambda: "/bin/uv")
        monkeypatch.setattr(motor_de_voz, "_uv_escolhe_o_torch", lambda uv: True)
        passos = dict(motor_de_voz.comandos())
        assert list(passos) == ["ambiente", "pacotes", "modelo", "teste"]
        assert passos["ambiente"][:4] == ["/bin/uv", "venv", "--python", "3.12"]
        assert passos["pacotes"][-3:] == ["--torch-backend", "auto", motor_de_voz.PACOTE]
        assert passos["modelo"][-3:] == ["--baixar", motor_de_voz.MODELO,
                                         str(motor_de_voz.pasta_do_modelo())]
        # o script roda isolado (-I) com o Python do ambiente do motor
        assert passos["teste"][:2] == [str(motor_de_voz.python_do_motor()), "-I"]

    def test_sem_o_uv_vale_o_pip(self, de_verdade, monkeypatch):
        monkeypatch.setattr(motor_de_voz, "achar_uv", lambda: None)
        passos = dict(motor_de_voz.comandos())
        assert passos["ambiente"] == [sys.executable, "-m", "venv",
                                      str(motor_de_voz.pasta() / ".venv")]
        assert passos["pacotes"][1:4] == ["-m", "pip", "install"]

    def test_instala_e_registra_a_placa(self, de_verdade, monkeypatch):
        rodados = []

        def rodar(comando, ao_ler, parar):
            rodados.append(comando)
            ao_ler("baixando...")
            if "--conferir" in comando:
                ao_ler(json.dumps({"aparelho": "mps", "torch": "2.14.1", "qwen_tts": "0.1.1"}))
                motor_de_voz.python_do_motor().parent.mkdir(parents=True, exist_ok=True)
                motor_de_voz.python_do_motor().write_text("")
            return 0

        monkeypatch.setattr(motor_de_voz, "_rodar", rodar)
        monkeypatch.setattr(motor_de_voz, "achar_uv", lambda: None)
        assert not motor_de_voz.instalado()
        registro = motor_de_voz.instalar()
        assert registro["aparelho"] == "mps" and len(rodados) == 4
        e = motor_de_voz.estado()
        assert e["instalado"] and not e["instalando"] and e["aparelho"] == "mps"
        motor_de_voz.desinstalar()
        assert not motor_de_voz.instalado() and not motor_de_voz.pasta().exists()

    def test_um_passo_que_falha(self, de_verdade, monkeypatch):
        def rodar(comando, ao_ler, parar):
            ao_ler("ERROR: No matching distribution found for qwen-tts")
            return 0 if "venv" in comando else 1

        monkeypatch.setattr(motor_de_voz, "_rodar", rodar)
        monkeypatch.setattr(motor_de_voz, "achar_uv", lambda: None)
        with pytest.raises(motor_de_voz.ErroDoMotor, match="No matching distribution"):
            motor_de_voz.instalar()
        e = motor_de_voz.estado()
        assert "Instalando o PyTorch" in e["erro"] and not e["instalando"]
        assert not e["instalado"]

    def test_uma_de_cada_vez(self, de_verdade, monkeypatch):
        import threading

        solta = threading.Event()

        def rodar(comando, ao_ler, parar):
            solta.wait(5)
            return 0

        monkeypatch.setattr(motor_de_voz, "_rodar", rodar)
        monkeypatch.setattr(motor_de_voz, "achar_uv", lambda: None)
        assert motor_de_voz.instalar_em_segundo_plano()["instalando"]
        with pytest.raises(motor_de_voz.ErroDoMotor, match="já está rodando"):
            motor_de_voz.instalar()
        with pytest.raises(motor_de_voz.ErroDoMotor, match="Espere"):
            motor_de_voz.desinstalar()
        motor_de_voz.cancelar_instalacao()
        solta.set()
        for _ in range(100):
            if not motor_de_voz.estado()["instalando"]:
                break
            threading.Event().wait(0.05)
        assert "cancelada" in motor_de_voz.estado()["erro"]


# O "motor" de mentira: lê o pedido como o de verdade e responde no mesmo formato.
_MOTOR_DE_MENTIRA = textwrap.dedent('''
    import json, sys, wave
    pedido = json.load(open(sys.argv[-1], encoding="utf-8"))
    print(json.dumps({"aparelho": "cpu"}), flush=True)
    print("uma linha que não é JSON", flush=True)
    for k, f in enumerate(pedido["frases"]):
        if "FALHE" in f["texto"]:
            print("Traceback: deu ruim no modelo", file=sys.stderr)
            sys.exit(3)
        with wave.open(f["saida"], "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
            w.writeframes(b"\\0\\0" * 2400 * len(f["texto"]))
        print(json.dumps({"feitas": k + 1, "total": len(pedido["frases"])}), flush=True)
''')


class TestASintese:
    @pytest.fixture
    def com_motor(self, de_verdade, monkeypatch, tmp_path):
        script = tmp_path / "motor.py"
        script.write_text(_MOTOR_DE_MENTIRA, encoding="utf-8")
        monkeypatch.setattr(motor_de_voz, "script", lambda: script)
        monkeypatch.setattr(motor_de_voz, "python_do_motor", lambda: Path(sys.executable))
        monkeypatch.setattr(motor_de_voz, "instalado", lambda: True)

    def test_a_conversa_pelo_subprocesso(self, com_motor, tmp_path):
        visto = []
        frases = [("Oi.", tmp_path / "1.wav"), ("Tudo bem?", tmp_path / "2.wav")]
        aparelho = motor_de_voz.sintetizar(tmp_path / "r.wav", "ref", frases,
                                           progresso=lambda f, t: visto.append(f))
        assert aparelho == "cpu" and visto == [1, 2]
        assert _duracao(tmp_path / "2.wav") == pytest.approx(0.9)

    def test_o_erro_do_motor_chega_inteiro(self, com_motor, tmp_path):
        with pytest.raises(motor_de_voz.ErroDoMotor, match=r"código 3.*deu ruim no modelo"):
            motor_de_voz.sintetizar(tmp_path / "r.wav", "ref", [("FALHE", tmp_path / "x.wav")])

    def test_sem_instalar(self, de_verdade, tmp_path):
        with pytest.raises(motor_de_voz.ErroDoMotor, match="não está instalada"):
            motor_de_voz.sintetizar(tmp_path / "r.wav", "ref", [("Oi.", tmp_path / "a.wav")])


class TestOScriptDoMotor:
    @pytest.fixture
    def script(self):
        spec = importlib.util.spec_from_file_location("motor_script", motor_de_voz.script())
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)          # só importa o que é da biblioteca padrão
        return modulo

    def test_os_argumentos(self, script, capsys):
        assert script.main([]) == 2 and "--baixar" in capsys.readouterr().err

    def test_grava_o_wav(self, script, tmp_path):
        script.gravar(str(tmp_path / "a.wav"), [0.0, 0.5, -2.0], 24000)
        with wave.open(str(tmp_path / "a.wav")) as w:
            assert (w.getnchannels(), w.getframerate(), w.getnframes()) == (1, 24000, 3)
