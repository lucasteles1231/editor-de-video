"""As imagens de fundo: o que entra, o que é recusado e o que fica guardado."""
from __future__ import annotations

import io
import os
import time

import pytest
from PIL import Image

from editor import imagens


def _png(tamanho=(300, 200), modo="RGB", cor=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new(modo, tamanho, cor).save(buf, "PNG")
    return buf.getvalue()


def test_guarda_e_devolve():
    info = imagens.guardar(_png(), origem="envio")
    assert (info.largura, info.altura, info.origem) == (300, 200, "envio")
    assert imagens.abrir(info.id) == info
    with Image.open(imagens.caminho(info.id)) as im:
        assert im.format == "JPEG" and im.size == (300, 200)


def test_mesmo_conteudo_mesmo_arquivo():
    assert imagens.guardar(_png(), origem="envio").id == imagens.guardar(_png(), origem="envio").id


def test_transparencia_vira_fundo_escuro():
    info = imagens.guardar(_png(modo="RGBA", cor=(0, 0, 0, 0)), origem="envio")
    with Image.open(imagens.caminho(info.id)) as im:
        assert max(im.getpixel((5, 5))) < 40


def test_foto_de_celular_deitada_fica_de_pe_e_sem_metadados():
    img = Image.new("RGB", (400, 200), (10, 200, 10))
    exif = img.getexif()
    exif[0x0112] = 6                                     # girada 90°
    exif[0x010F] = "Celular de alguém"                   # a marca: some ao gravar de novo
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    info = imagens.guardar(buf.getvalue(), origem="envio")
    assert (info.largura, info.altura) == (200, 400)
    with Image.open(imagens.caminho(info.id)) as im:
        assert not im.getexif()


@pytest.mark.parametrize("dados", [b"isso nao e imagem", b"GIF89a quebrado"])
def test_recusa_o_que_nao_e_imagem(dados):
    with pytest.raises(imagens.ImagemRecusada):
        imagens.guardar(dados, origem="envio")


def test_recusa_grande_demais():
    with pytest.raises(imagens.ImagemRecusada, match="teto"):
        imagens.guardar(b"0" * (imagens.TETO_BYTES + 1), origem="envio")


def test_id_estranho_nao_vira_caminho():
    assert imagens.caminho("../../etc/passwd") is None
    assert imagens.abrir("0123456789abcdef") is None


def test_achar_a_gerada_pela_chave():
    info = imagens.guardar(_png(cor=(1, 2, 3)), origem="gerada", credito="um estúdio",
                           chave="abc")
    assert imagens.achar("abc") == info and imagens.achar("outra") is None


def test_limpeza_poupa_as_geradas():
    velha = imagens.guardar(_png(cor=(9, 9, 9)), origem="envio")
    paga = imagens.guardar(_png(cor=(8, 8, 8)), origem="gerada", chave="x")
    antigo = time.time() - imagens.GUARDAR_S - 60
    for iid in (velha.id, paga.id):
        for sufixo in (".jpg", ".json"):
            os.utime(imagens.pasta() / f"{iid}{sufixo}", (antigo, antigo))
    imagens.limpar_antigas()
    assert imagens.caminho(velha.id) is None and imagens.caminho(paga.id) is not None
