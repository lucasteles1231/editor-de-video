"""O recorte da pessoa, sem o modelo: a sessão do onnxruntime é uma imitação."""
from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from editor import recorte


class _Sessao:
    """Faz o papel do MODNet: devolve a máscara que o teste mandar, no tamanho pedido."""

    def __init__(self, mascara: np.ndarray):
        self.mascara = mascara
        self.entradas: list[np.ndarray] = []

    def get_inputs(self):
        return [type("Entrada", (), {"name": "input"})()]

    def run(self, _saidas, feed):
        x = feed["input"]
        self.entradas.append(x)
        alt, lar = x.shape[2:]
        img = Image.fromarray((self.mascara * 255).astype(np.uint8)).resize((lar, alt))
        return [np.asarray(img, dtype=np.float32)[None, None] / 255.0]


def _busto(altura=640, largura=360) -> np.ndarray:
    return recorte._silhueta_falsa(altura, largura)


class TestOModelo:
    def test_tamanho_de_entrada(self):
        alt, lar = recorte.tamanho_de_entrada(2048, 1080)
        assert alt % 32 == 0 and lar % 32 == 0 and min(alt, lar) == 512
        assert recorte.tamanho_de_entrada(720, 1280) == (512, 896)

    def test_preparar_normaliza_de_menos_um_a_um(self):
        quadro = np.zeros((100, 200, 3), np.uint8)
        quadro[:, 100:] = 255
        x = recorte.preparar(quadro)
        assert x.shape == (1, 3, 512, 1024) and x.dtype == np.float32
        assert x[0, :, 0, 0].tolist() == [-1.0, -1.0, -1.0]
        assert x[0, :, 0, -1].tolist() == [1.0, 1.0, 1.0]

    def test_mascara_volta_no_tamanho_do_quadro(self, monkeypatch):
        monkeypatch.delenv(recorte.VARIAVEL_FALSA, raising=False)
        sessao = _Sessao(_busto())
        monkeypatch.setattr(recorte, "_carregar", lambda: sessao)
        quadro = np.full((640, 360, 3), 128, np.uint8)
        alfa = recorte.mascara(quadro)
        assert alfa.shape == (640, 360) and alfa.min() >= 0.0 and alfa.max() <= 1.0
        assert sessao.entradas[0].shape[2:] == recorte.tamanho_de_entrada(640, 360)


class TestAsCaixas:
    def test_busto(self):
        pessoa, rosto = recorte.caixas(_busto())
        assert pessoa is not None and rosto is not None
        # o rosto fica em cima e é mais estreito que os ombros
        assert rosto.y0 == pytest.approx(pessoa.y0) and rosto.y1 < 0.5
        assert (rosto.x1 - rosto.x0) < (pessoa.x1 - pessoa.x0) * 0.6

    def test_quadro_sem_ninguem(self):
        assert recorte.caixas(np.zeros((100, 100), np.float32)) == (None, None)

    def test_mancha_solta_sai(self):
        """Visto com fala real: pedaços do tampo da mesa vinham junto e esticavam a
        caixa da pessoa até a borda do quadro."""
        alfa = _busto()
        alfa[600:630, 10:60] = 0.7                  # uma mancha longe da pessoa
        limpo = recorte.so_a_pessoa(alfa)
        assert limpo[600:630, 10:60].max() == 0.0
        assert limpo[200, 180] == pytest.approx(1.0)          # a cabeça continua
        pessoa, _ = recorte.caixas(limpo)
        assert pessoa.x0 > 0.1

    def test_borda_macia_fica(self):
        alfa = _busto()
        alfa[alfa == 0] = 0.0
        borda = np.argwhere((alfa[:, :-1] == 1) & (alfa[:, 1:] == 0))[0]
        alfa[borda[0], borda[1] + 1] = 0.4                  # cabelo: alfa parcial
        limpo = recorte.so_a_pessoa(alfa)
        assert limpo[borda[0], borda[1] + 1] == pytest.approx(0.4)


def test_png_tem_transparencia():
    quadro = np.full((64, 32, 3), 200, np.uint8)
    alfa = np.zeros((64, 32), np.float32)
    alfa[10:50, 8:24] = 1.0
    with Image.open(io.BytesIO(recorte.png(quadro, alfa))) as im:
        assert im.mode == "RGBA" and im.size == (32, 64)
        assert im.getpixel((0, 0))[3] == 0 and im.getpixel((16, 30))[3] == 255


def test_falso_nao_baixa_nada():
    assert recorte.modelo_baixado()
    r = recorte.recortar(np.zeros((320, 180, 3), np.uint8))
    assert r.ok and r.rosto.y1 < r.pessoa.y1
