"""
A montagem em camadas: o fundo encaixado, a pessoa ou o personagem por cima, e onde
ela fica.

Os vídeos com transparência são feitos pelo próprio PyAV (MOV ProRes 4444 e WebM VP9
com alfa), com um busto opaco no meio e o resto transparente. O recorte é o falso
(conftest): a mesma silhueta de busto.
"""
from __future__ import annotations

import wave
from pathlib import Path

import av
import numpy as np
import pytest
from PIL import Image, ImageDraw

from editor import cortes, montagem, plano, recorte
from editor import video as video_mod
from editor.mover import Transformacao
from tests.conftest import fazer_video


def video_com_alfa(caminho: Path, *, codec="prores_ks", pix_fmt="yuva444p10le",
                   opcoes=None, largura=160, altura=240, segundos=1.0, fps=10) -> Path:
    """Um busto opaco (a silhueta falsa) que anda um pouco; o resto é transparente."""
    caminho = Path(caminho)
    if opcoes is None:
        opcoes = {"profile": "4"} if codec == "prores_ks" else {}
    busto = recorte._silhueta_falsa(altura, largura) > 0.5
    with av.open(str(caminho), "w") as c:
        s = c.add_stream(codec, rate=fps)
        s.width, s.height, s.pix_fmt = largura, altura, pix_fmt
        s.options = opcoes
        for k in range(round(segundos * fps)):
            q = np.zeros((altura, largura, 4), np.uint8)
            q[..., :3] = (30, 200, 60)
            q[busto, 3] = 255
            q[..., 0] = (k * 20) % 256
            f = av.VideoFrame.from_ndarray(q, format="rgba").reformat(format=pix_fmt)
            f.pts = k
            for p in s.encode(f):
                c.mux(p)
        for p in s.encode():
            c.mux(p)
    return caminho


def gif(caminho: Path, *, transparente=True, quadros=4, lado=60, duracao=80,
        fundo=(255, 0, 255)) -> Path:
    """Um personagem redondo que abre e fecha a boca."""
    imagens = []
    for k in range(quadros):
        im = Image.new("RGBA", (lado, lado), (0, 0, 0, 0) if transparente else (*fundo, 255))
        d = ImageDraw.Draw(im)
        d.ellipse((8, 8, lado - 8, lado - 4), fill=(250, 200, 0, 255))
        boca = 2 + 4 * (k % 2)
        d.rectangle((lado // 2 - 8, lado - 22, lado // 2 + 8, lado - 22 + boca),
                    fill=(60, 20, 20, 255))
        imagens.append(im)
    imagens[0].save(caminho, save_all=True, append_images=imagens[1:], duration=duracao,
                    loop=0, disposal=2)
    return Path(caminho)


def audio_wav(caminho: Path, *, segundos=4.0, falas=((0.3, 1.5), (2.4, 3.7))) -> Path:
    taxa = 48_000
    t = np.arange(round(segundos * taxa)) / taxa
    som = np.zeros_like(t)
    for ini, fim in falas:
        trecho = (t >= ini) & (t < fim)
        som[trecho] = 0.3 * np.sin(2 * np.pi * 220 * t[trecho])
    with wave.open(str(caminho), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taxa)
        w.writeframes((som * 32767).astype("<i2").tobytes())
    return Path(caminho)


def _plano(movimentos=(), vertical=True) -> plano.Plano:
    return plano.Plano(10.0, vertical, [], [], [(0.0, 1.0)], [], [], [],
                       movimentos=list(movimentos))


# ── o vídeo com transparência ─────────────────────────────────────────────


class TestOAlfaDoArquivo:
    @pytest.mark.parametrize("codec, pix_fmt, nome", [
        ("prores_ks", "yuva444p10le", "p.mov"), ("libvpx-vp9", "yuva420p", "p.webm"),
        ("png", "rgba", "png.mov"), ("qtrle", "argb", "anim.mov")])
    def test_le_o_alfa(self, tmp_path, codec, pix_fmt, nome):
        caminho = video_com_alfa(tmp_path / nome, codec=codec, pix_fmt=pix_fmt)
        assert video_mod.tem_alfa(caminho)
        _t, q = next(video_mod.quadros(caminho, alfa=True))
        busto = recorte._silhueta_falsa(*q.shape[:2]) > 0.5
        assert q.shape[2] == 4
        assert q[busto, 3].mean() > 240 and q[~busto, 3].mean() < 15

    def test_video_comum_nao_tem_alfa(self, tmp_path):
        assert not video_mod.tem_alfa(fazer_video(tmp_path / "v.mp4", segundos=0.5))


class TestOCursor:
    def test_anda_para_frente_e_repete_o_mesmo_quadro(self, tmp_path):
        v = fazer_video(tmp_path / "v.mp4", segundos=1.0, fps=10)
        c = video_mod.Cursor(v)
        a, b = c.em(0.31), c.em(0.33)
        assert a is b                                 # o mesmo quadro (0,3 s), sem decodificar
        assert c.em(0.45) is not a

    def test_volta_ao_comeco_quando_acaba(self, tmp_path):
        v = fazer_video(tmp_path / "v.mp4", segundos=1.0, fps=10)
        c = video_mod.Cursor(v)
        primeiro = c.em(0.0).copy()
        c.em(0.95)
        assert np.array_equal(c.em(1.02), primeiro)  # 1,02 s vira 0,02 s


def test_para_origem_e_o_inverso_de_para_saida():
    linha = cortes.Linha([cortes.Trecho(0.0, 1.0), cortes.Trecho(2.0, 3.5),
                          cortes.Trecho(5.0, 6.0)])
    for t in (0.0, 0.5, 1.2, 2.4, 2.6, 3.4):
        assert linha.para_saida(linha.para_origem(t)) == pytest.approx(t)
    assert linha.para_origem(99.0) == pytest.approx(6.0)


def test_duracao_do_audio(tmp_path):
    assert video_mod.duracao_do_audio(audio_wav(tmp_path / "n.wav", segundos=2.5)) == \
        pytest.approx(2.5, abs=0.05)
    with pytest.raises(ValueError):
        video_mod.duracao_do_audio(fazer_video(tmp_path / "v.mp4", com_audio=False))


# ── as entradas ──────────────────────────────────────────────────────────


class TestAMontagem:
    def test_problemas(self, tmp_path):
        f = tmp_path / "f.mp4"
        assert montagem.Montagem(f).problemas()                       # nada por cima
        assert montagem.Montagem(f, pessoa=f, personagem=f).problemas()
        assert montagem.Montagem(f, pessoa=f, recorte="x").problemas()
        assert montagem.Montagem(f, pessoa=f, formato="redondo").problemas()
        assert montagem.Montagem(f, personagem=f, formato="vertical").problemas() == []

    def test_de_onde_vem_a_fala(self, tmp_path):
        fundo = fazer_video(tmp_path / "f.mp4", segundos=0.5)
        muda = fazer_video(tmp_path / "p.mp4", segundos=0.5, com_audio=False)
        falando = fazer_video(tmp_path / "pf.mp4", segundos=0.5)
        audio = audio_wav(tmp_path / "a.wav")
        assert montagem.Montagem(fundo, pessoa=falando, audio=audio).fonte_da_fala() == audio
        assert montagem.Montagem(fundo, pessoa=falando).fonte_da_fala() == falando
        assert montagem.Montagem(fundo, pessoa=muda).fonte_da_fala() == fundo
        boneco = gif(tmp_path / "b.gif")
        assert montagem.Montagem(fundo, personagem=boneco).fonte_da_fala() == fundo
        assert montagem.Montagem(fundo, personagem=boneco, audio=audio).fonte_da_fala() == audio


# ── o quadro final ───────────────────────────────────────────────────────


class TestOQuadroFinal:
    @pytest.mark.parametrize("formato, fundo, esperado", [
        ("fundo", (1920, 1080), (1920, 1080)), ("vertical", (1920, 1080), (1080, 1920)),
        ("horizontal", (1080, 1920), (1920, 1080)), ("quadrado", (1920, 1080), (1080, 1080))])
    def test_tamanho(self, formato, fundo, esperado):
        assert montagem.tamanho_do_quadro(formato, *fundo) == esperado

    def test_encaixe_deitado_num_quadro_em_pe(self):
        x, y, w, h = montagem.encaixe(1920, 1080, 1080, 1920)
        assert (x, w) == (0, 1080) and h == 608
        assert y + h / 2 == pytest.approx(0.4 * 1920, abs=1)       # um pouco acima do meio

    def test_encaixe_do_mesmo_formato_ocupa_tudo(self):
        assert montagem.encaixe(1280, 720, 1280, 720) == (0, 0, 1280, 720)

    def test_as_sobras_tem_o_fundo_e_nao_preto(self):
        img = Image.new("RGB", (160, 90), (200, 120, 40))
        s = np.asarray(montagem.sobras(img, 90, 160)).astype(int)
        assert s.shape == (160, 90, 3)
        r, _g, b = s[5, 5]
        assert r > b and r > 60                       # a cor do fundo, escurecida


# ── o personagem ─────────────────────────────────────────────────────────


class TestOPersonagem:
    def test_gif_transparente_em_loop(self, tmp_path):
        p = montagem.ler_personagem(gif(tmp_path / "p.gif", quadros=4, duracao=80))
        assert len(p.quadros) == 4 and p.tem_alfa
        assert p.duracao == pytest.approx(0.32)
        assert p.quadro_em(0.0) is p.quadros[0]
        assert p.quadro_em(0.09) is p.quadros[1]
        assert p.quadro_em(0.33) is p.quadros[0]       # deu a volta
        assert p.quadros[0][0, 0, 3] == 0 and p.quadros[0][30, 30, 3] == 255

    def test_fundo_de_cor_unica_sai(self, tmp_path):
        p = montagem.ler_personagem(gif(tmp_path / "p.gif", transparente=False))
        assert not p.tem_alfa
        q = p.quadros[0]
        assert q[0, 0, 3] == 0 and q[30, 30, 3] == 255
        mantido = montagem.ler_personagem(gif(tmp_path / "m.gif", transparente=False),
                                          tirar_fundo=False)
        assert mantido.quadros[0][0, 0, 3] == 255

    def test_duracao_zero_vira_100_ms(self, tmp_path):
        p = montagem.ler_personagem(gif(tmp_path / "p.gif", duracao=0))
        assert p.duracoes[0] == pytest.approx(0.1)

    def test_arquivo_que_nao_e_imagem(self, tmp_path):
        ruim = tmp_path / "x.gif"
        ruim.write_bytes(b"isto nao e um gif")
        with pytest.raises(montagem.PersonagemInvalido):
            montagem.ler_personagem(ruim)

    def test_quadros_demais(self, tmp_path, monkeypatch):
        monkeypatch.setattr(montagem, "PERSONAGEM_TETO_QUADROS", 3)
        with pytest.raises(montagem.PersonagemInvalido, match="quadros"):
            montagem.ler_personagem(gif(tmp_path / "p.gif", quadros=4))


# ── onde ela fica ────────────────────────────────────────────────────────


class _Camada(montagem.Camada):
    """Uma camada de 200 × 400 com a silhueta falsa (um busto encostado embaixo)."""

    def __init__(self, largura=200, altura=400):
        self.largura, self.altura = largura, altura
        self._medir([recorte._silhueta_falsa(altura, largura)])

    def rgba(self, t_origem, t_saida):
        q = np.zeros((self.altura, self.largura, 4), np.uint8)
        q[..., :3] = 255
        q[..., 3] = (recorte._silhueta_falsa(self.altura, self.largura) * 255).astype(np.uint8)
        return q


class TestAPosicao:
    def _base(self, tr: Transformacao, c: montagem.Camada) -> tuple[float, float]:
        p = c.pessoa
        return tr.ponto((p.x0 + p.x1) / 2 * c.largura, p.y1 * c.altura)

    def test_casa_em_pe_e_embaixo_no_meio(self):
        c = _Camada()
        tr = montagem.casa(c, 1080, 1920)
        x, y = self._base(tr, c)
        assert x == pytest.approx(540, abs=1) and y == pytest.approx(1920, abs=1)
        altura = (c.pessoa.y1 - c.pessoa.y0) * c.altura * tr.escala
        assert altura == pytest.approx(0.5 * 1920, rel=0.01)

    def test_casa_deitada_e_no_canto_direito(self):
        c = _Camada()
        tr = montagem.casa(c, 1920, 1080)
        direita, _ = tr.ponto(c.pessoa.x1 * c.largura, 0)
        assert direita == pytest.approx(1920 * 0.97, abs=1)

    def test_cada_posicao(self):
        c = _Camada()
        W, H = 1080, 1920
        de_casa = montagem.casa(c, W, H)

        def centro_x(tr):
            return self._base(tr, c)[0] / W

        esquerda = montagem.alvo("esquerda", de_casa, c, W, H)
        assert esquerda.ponto(c.pessoa.x0 * c.largura, 0)[0] == pytest.approx(0.03 * W)
        direita = montagem.alvo("direita", de_casa, c, W, H)
        assert direita.ponto(c.pessoa.x1 * c.largura, 0)[0] == pytest.approx(0.97 * W)
        assert centro_x(montagem.alvo("meio", de_casa, c, W, H)) == pytest.approx(0.5)
        cima = montagem.alvo("cima", de_casa, c, W, H)
        assert cima.ponto(0, c.pessoa.y0 * c.altura)[1] == pytest.approx(0.06 * H)
        baixo = montagem.alvo("baixo", de_casa, c, W, H)
        assert baixo.dy == pytest.approx(de_casa.dy + 0.15 * H)
        perto = montagem.alvo("perto", de_casa, c, W, H)
        r = c.rosto
        rosto = ((r.x0 + r.x1) / 2 * c.largura, (r.y0 + r.y1) / 2 * c.altura)
        assert perto.escala == pytest.approx(de_casa.escala * 1.35)
        assert perto.ponto(*rosto) == pytest.approx(de_casa.ponto(*rosto))  # o rosto fica
        longe = montagem.alvo("longe", de_casa, c, W, H)
        assert longe.escala == pytest.approx(de_casa.escala * 0.7)
        assert self._base(longe, c) == pytest.approx(self._base(de_casa, c))  # a base fica
        with pytest.raises(ValueError):
            montagem.alvo("diagonal", de_casa, c, W, H)


# ── o quadro composto ────────────────────────────────────────────────────


class TestOMontador:
    def _montador(self, tmp_path, movimentos=(), formato="vertical", personagem=True):
        fundo = fazer_video(tmp_path / "f.mp4", largura=320, altura=180, segundos=2.0)
        info = video_mod.sondar(fundo)
        larg, alt = montagem.tamanho_do_quadro(formato, info.largura, info.altura)
        if personagem:
            m = montagem.Montagem(fundo, personagem=gif(tmp_path / "p.gif", lado=80),
                                  formato=formato)
        else:
            m = montagem.Montagem(fundo, pessoa=video_com_alfa(tmp_path / "p.mov"),
                                  recorte="transparente", formato=formato)
        return montagem.Montador(m, _plano(movimentos, vertical=alt > larg), larg, alt, info)

    def test_compoe_no_tamanho_do_quadro(self, tmp_path):
        mo = self._montador(tmp_path)
        img = mo.quadro(0.5, 0.5)
        assert img.size == (180, 320)
        q = np.asarray(img).astype(int)
        # o personagem amarelo está embaixo, no meio
        x, y = mo.casa.ponto((mo.camada.pessoa.x0 + mo.camada.pessoa.x1) / 2 * mo.camada.largura,
                             (mo.camada.pessoa.y0 + mo.camada.pessoa.y1) / 2 * mo.camada.altura)
        r, g, b = q[int(y), int(x)]
        assert r > 200 and g > 150 and b < 80

    def test_a_pessoa_com_alfa_aparece(self, tmp_path):
        mo = self._montador(tmp_path, personagem=False, formato="fundo")
        img = np.asarray(mo.quadro(0.2, 0.2)).astype(int)
        p = mo.camada.pessoa
        x, y = mo.casa.ponto((p.x0 + p.x1) / 2 * mo.camada.largura,
                             (p.y0 + p.y1) / 2 * mo.camada.altura + 30)
        assert img[int(y), int(x), 1] > 150                   # o verde da pessoa

    def test_anda_no_movimento_e_volta_para_casa(self, tmp_path):
        mov = plano.Movimento(1.0, 1.8, "esquerda", True)
        mo = self._montador(tmp_path, movimentos=[mov])
        assert mo.transformacao(0.5) == mo.casa
        no_meio = mo.transformacao(1.5)
        assert no_meio.dx < mo.casa.dx                         # foi para a esquerda
        assert mo.lado_livre(1.5) == 1 and mo.lado_livre(0.5) == 0
        assert mo.transformacao(1.9) == mo.casa                # voltou no corte

    def test_ja_estava_la_vem_para_perto(self, tmp_path):
        """Deitado, a casa é embaixo à direita: ir para a direita não mudaria nada."""
        mov = plano.Movimento(1.0, 1.8, "direita", True)
        mo = self._montador(tmp_path, movimentos=[mov], formato="horizontal")
        assert mo.transformacao(1.5).escala > mo.casa.escala * 1.2
