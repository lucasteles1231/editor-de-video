"""
O editor inteiro, do vídeo de entrada ao editado: transcrever → cortar → planejar →
desenhar e gravar.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

import numpy as np
from PIL import Image

from editor import cartoes as cartoes_mod
from editor import (
    cenas,
    censura,
    cortes,
    exportar,
    icones,
    plano,
    recorte,
    roteiro,
    sons,
    transcricao,
    voz,
)
from editor import janela as janela_mod
from editor import saida as saida_mod
from editor import video as video_mod
from editor.legenda import Legenda
from editor.montagem import Montador, Montagem, camada_da_montagem, tamanho_do_quadro
from editor.opcoes import OpcoesDeEdicao

logger = logging.getLogger(__name__)

#: O fade nas bordas de cada corte, para o áudio não estalar.
FADE_S = 0.008
#: O empurrão de zoom no adesivo entra em 150 ms e volta em 300 ms (a força vem do plano,
#: 6% sem escolha).
EMPURRAO_ENTRA_S = 0.15
EMPURRAO_SAI_S = 0.30

#: (etapa, fração de 0 a 1 dela, detalhe)
Progresso = Callable[[str, float, str], None]


class Cancelado(Exception):
    """A edição foi cancelada por quem pediu."""


@dataclass
class Resultado:
    video: Path
    plano: Path
    legendas: list[Path] = field(default_factory=list)
    palavras: int = 0
    duracao_original: float = 0.0
    duracao_final: float = 0.0
    segundos: float = 0.0
    largura: int = 0
    altura: int = 0
    #: O resumo do roteiro: quem escolheu as cenas e os cartões, quantos, e o aviso.
    roteiro: dict = field(default_factory=dict)

    def para_dict(self) -> dict:
        return {"video": str(self.video), "plano": str(self.plano),
                "legendas": [str(p) for p in self.legendas], "palavras": self.palavras,
                "duracao_original": round(self.duracao_original, 2),
                "duracao_final": round(self.duracao_final, 2),
                "segundos": round(self.segundos, 1), "largura": self.largura,
                "altura": self.altura, "roteiro": self.roteiro}


def pasta_de_cache() -> Path:
    from platformdirs import user_cache_dir

    pasta = Path(user_cache_dir("editor-de-video", appauthor=False)) / "transcricoes"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def obter_palavras(entrada: Path, duracao: float, edicao: OpcoesDeEdicao,
                   progresso: Progresso) -> list[transcricao.Palavra]:
    """A transcrição guardada deste arquivo (vídeo ou áudio), ou uma nova."""
    # as palavras do bipe vão de dica: sem ela, o Whisper escreve "coca ainda"
    dica = transcricao.dica_das_palavras(censura.lista(edicao.bipe))
    origem = transcricao.identidade(entrada, idioma=edicao.idioma, modelo=edicao.modelo,
                                    dica=dica)
    chave = hashlib.sha1(json.dumps(origem, sort_keys=True).encode()).hexdigest()[:16]
    guardada = pasta_de_cache() / f"{chave}.json"
    palavras = transcricao.carregar(guardada, origem=origem)
    if palavras is not None:
        progresso("transcrevendo", 1.0, "transcrição reaproveitada")
        return palavras
    if not transcricao.modelo_baixado(edicao.modelo):
        progresso("transcrevendo", 0.0,
                  f"baixando o modelo {edicao.modelo} ({transcricao.MODELOS[edicao.modelo]}),"
                  " só na primeira vez")
    palavras = transcricao.transcrever(
        entrada, idioma=edicao.idioma, modelo=edicao.modelo, duracao=duracao,
        progresso=lambda f: progresso("transcrevendo", f, ""), dica=dica)
    transcricao.salvar(palavras, guardada, origem=origem)
    return palavras


def empurrao(p: plano.Plano, t: float) -> float:
    """O quanto a mais de zoom o adesivo dá em ``t`` (0 sem empurrão)."""
    extra, forca = 0.0, p.forca_do_empurrao
    for a, b in p.empurroes:
        if a <= t < b:
            extra = max(extra, forca * min(1.0, (t - a) / EMPURRAO_ENTRA_S))
        elif b <= t < b + EMPURRAO_SAI_S:
            extra = max(extra, forca * (1 - (t - b) / EMPURRAO_SAI_S))
    return extra


def nivel_base(p: plano.Plano, t: float) -> float:
    """O nível de zoom dos cortes em ``t``, sem o empurrão do adesivo."""
    nivel = 1.0
    for inicio, n in p.zoom:
        if inicio <= t:
            nivel = n
        else:
            break
    return nivel


def nivel_de_zoom(p: plano.Plano, t: float) -> float:
    return nivel_base(p, t) * (1 + empurrao(p, t))


def janela(largura: int, altura: int, nivel: float, ax: float, ay: float
           ) -> tuple[float, float, float, float]:
    """A janela do quadro original que o zoom mostra."""
    cw, ch = largura / nivel, altura / nivel
    x0 = min(max(ax * largura - cw / 2, 0.0), largura - cw)
    y0 = min(max(ay * altura - ch / 2, 0.0), altura - ch)
    return x0, y0, x0 + cw, y0 + ch


def montar_audio(audio: np.ndarray, linha: cortes.Linha, plano_: plano.Plano,
                 volume: float = 1.0) -> np.ndarray:
    """O áudio só com os trechos que ficam, com fade nas bordas, e os efeitos por baixo."""
    taxa = video_mod.TAXA
    fade = max(1, int(FADE_S * taxa))
    pedacos = []
    for t in linha.trechos:
        p = audio[int(t.ini * taxa):int(t.fim * taxa)].copy()
        if len(p) > 2 * fade:
            rampa = np.linspace(0.0, 1.0, fade, dtype=np.float32)[:, None]
            p[:fade] *= rampa
            p[-fade:] *= rampa[::-1]
        pedacos.append(p)
    voz = np.concatenate(pedacos) if pedacos else np.zeros((0, 2), np.float32)
    alvo = round(linha.duracao * taxa)
    if len(voz) < alvo:
        voz = np.concatenate([voz, np.zeros((alvo - len(voz), 2), np.float32)])
    if plano_.sons:
        voz = sons.misturar(voz, sons.trilha(plano_.sons, linha.duracao, taxa, volume))
    return np.ascontiguousarray(voz.astype(np.float32))


def _icones(img: Image.Image, p: plano.Plano, t: float, lado_livre: int = 0,
            area: tuple[float, float, float, float] | None = None) -> None:
    """Os ícones do momento. Com a pessoa num lado, eles vão para o outro. Com ``area``
    (a janela), eles ficam dentro dela, no alto."""
    if any(c.inicio <= t < c.fim for c in p.cartoes):
        return                      # o cartão já ilustra o momento
    largura, altura = img.size
    raio = round(min(largura, altura) * 0.09)
    for k, ic in enumerate(p.icones):
        if not ic.inicio <= t < ic.fim:
            continue
        s = icones.escala(t - ic.inicio, ic.fim - ic.inicio)
        if s <= 0.02:
            continue
        balao = icones.balao(ic.nome, raio, semente=k + 1)
        if abs(s - 1.0) > 0.01:
            lado = max(2, round(balao.width * s))
            balao = balao.resize((lado, lado), Image.BILINEAR)
        lado = lado_livre or ic.lado
        if area is not None:
            ax, ay, aw, ah = area
            cx, cy = ax + aw * (0.5 + 0.34 * lado), ay + ah * 0.28
        elif p.vertical:
            cx, cy = largura * (0.5 + 0.30 * lado), altura * 0.27
        else:
            cx, cy = largura * (0.5 + 0.40 * lado), altura * 0.22
        img.paste(balao, (round(cx - balao.width / 2), round(cy - balao.height / 2)), balao)


@dataclass
class _Fala:
    """O que a fala decidiu: a linha do tempo, o plano, as palavras no vídeo editado e o
    áudio da fala (o som final sai depois, com os efeitos dos cartões)."""

    linha: cortes.Linha
    plano: plano.Plano
    palavras: int
    duracao: float
    audio: np.ndarray | None
    no_editado: list = field(default_factory=list)
    som: np.ndarray | None = None


@dataclass
class _Preparada:
    """A fala pronta para planejar: o arquivo (o original, ou o WAV com as partes juntas e
    a voz tratada), a duração, as palavras já no tempo dele (quando ele foi montado) e
    onde vai bipe."""

    arquivo: Path
    duracao: float
    tem_audio: bool
    palavras: list | None = None
    bipes: list[tuple[float, float]] = field(default_factory=list)


def _duracao_e_audio(caminho: Path) -> tuple[float, bool]:
    try:
        info = video_mod.sondar(caminho)
        return info.duracao, info.tem_audio
    except ValueError:                        # um áudio sem vídeo
        return video_mod.duracao_do_audio(caminho), True


def pasta_de_vozes() -> Path:
    pasta = pasta_de_cache().parent / "vozes"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def _gravar_wav(caminho: Path, estereo: np.ndarray) -> None:
    import wave

    pcm = (np.clip(estereo, -1, 1) * 32767).astype("<i2")
    with wave.open(str(caminho), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(voz.TAXA)
        w.writeframes(pcm.tobytes())


def _preparar_fala(arquivos: list[Path], edicao: OpcoesDeEdicao, avisar: Progresso,
                   parar: Callable[[], bool]) -> _Preparada:
    """A fala como vai para o plano. Um arquivo só, sem tratar e sem bipe, vai como veio;
    senão as partes são transcritas uma a uma (cada transcrição fica guardada), juntadas,
    tratadas e bipadas, num WAV da pasta de cache."""
    proibidas = censura.lista(edicao.bipe)
    if len(arquivos) == 1 and edicao.voz == "original" and not proibidas:
        duracao, tem_audio = _duracao_e_audio(arquivos[0])
        return _Preparada(arquivos[0], duracao, tem_audio)
    por_parte = []
    for k, arquivo in enumerate(arquivos):
        duracao, tem_audio = _duracao_e_audio(arquivo)

        def parte(etapa: str, fracao: float, detalhe: str, k=k) -> None:
            avisar(etapa, (k + fracao) / len(arquivos),
                   detalhe or (f"parte {k + 1} de {len(arquivos)}" if len(arquivos) > 1
                               else ""))

        por_parte.append(obter_palavras(arquivo, duracao, edicao, parte) if tem_audio else [])
        if parar():
            raise Cancelado
    avisar("cortando", 0.0, "tratando a voz" if edicao.voz != "original" else
           "juntando as partes")
    mono = [video_mod.ler_audio_mono(a, voz.TAXA) for a in arquivos]
    junto, partes = voz.juntar(mono, edicao.voz)
    palavras = voz.palavras_nas_partes(por_parte, partes)
    estereo = voz.tratar(junto, edicao.voz)
    bipes = voz.trechos_do_bipe(palavras, junto, proibidas) if proibidas else []
    estereo = voz.bipar(estereo, bipes)
    chave = hashlib.sha1(json.dumps(
        [transcricao.identidade(a, idioma=edicao.idioma, modelo=edicao.modelo)
         for a in arquivos] + [edicao.voz, proibidas], sort_keys=True).encode()).hexdigest()
    wav = pasta_de_vozes() / f"{chave[:16]}.wav"
    _gravar_wav(wav, estereo)
    return _Preparada(wav, len(junto) / voz.TAXA, True, palavras, bipes)


def _planejar(fala: Path, duracao_da_fala: float, tem_audio: bool, edicao: OpcoesDeEdicao,
              saida_r: saida_mod.OpcoesDeSaida, previa_s: float | None, *, vertical: bool,
              mover: bool, avisar: Progresso, parar: Callable[[], bool],
              palavras: list | None = None, bipes: Sequence[tuple[float, float]] = ()
              ) -> _Fala:
    """Transcreve (se as palavras não vieram prontas), corta e planeja a partir do
    arquivo da fala."""
    duracao = duracao_da_fala if not previa_s else min(duracao_da_fala, previa_s)
    if saida_r.formato == "gif":
        duracao = min(duracao, saida_mod.GIF_MAX_S)
    if palavras is None:
        palavras = obter_palavras(fala, duracao_da_fala, edicao, avisar) if tem_audio else []
    palavras = [p for p in palavras if p.inicio < duracao]
    if parar():
        raise Cancelado

    avisar("cortando", 0.0, "")
    audio = (video_mod.ler_audio(fala, duracao_da_fala)[: int(duracao * video_mod.TAXA)]
             if tem_audio else np.zeros((0, 2), np.float32))
    if edicao.cortes and palavras:
        trechos = cortes.calcular(palavras, audio.mean(axis=1) if len(audio) else None,
                                  video_mod.TAXA, duracao, pausa_maxima=edicao.pausa_maxima,
                                  respiro=edicao.respiro)
    else:
        trechos = [cortes.Trecho(0.0, duracao)]
    linha = cortes.Linha(trechos)
    # A legenda mostra as palavras proibidas com a sílaba escondida, como o bipe.
    proibidas = censura.lista(edicao.bipe)
    vistas = ([transcricao.Palavra(censura.censurar_texto(w.texto, proibidas), w.inicio, w.fim)
               for w in palavras] if proibidas else palavras)
    no_editado = linha.palavras(vistas)
    p = plano.montar(no_editado, linha.duracao, vertical=vertical, cortes=linha.cortes,
                     opcoes=edicao, nomes_de_icones=set(icones.nomes()), mover=mover)
    p.trechos = [(round(tr.ini, 3), round(tr.fim, 3)) for tr in linha.trechos]
    for a0, b0 in bipes:
        a1, b1 = linha.para_saida(a0), linha.para_saida(b0)
        if a1 is not None and b1 is not None:
            p.bipes.append((round(a1, 3), round(b1, 3)))
    avisar("cortando", 1.0, f"{len(trechos)} trecho(s), {linha.duracao:.1f} s de "
                            f"{duracao:.1f} s")
    return _Fala(linha, p, len(palavras), duracao, audio if tem_audio else None, no_editado)


def _escrever_roteiro(f: _Fala, edicao: OpcoesDeEdicao, avisar: Progresso,
                      biblioteca: cenas.Biblioteca | None = None) -> roteiro.Roteiro | None:
    """As cenas (com a biblioteca) e os cartões (com as animações), pelo Gemini ou pelas
    palavras; os sons dos cartões entram no plano."""
    destaques = edicao.estilo_da_legenda == "destaques"
    if biblioteca is None and not edicao.animacoes and not destaques:
        return None
    avisar("cortando", 1.0, "o Gemini está escolhendo as cenas e os cartões"
           if biblioteca is not None else "o Gemini está escrevendo os cartões"
           if edicao.animacoes else "o Gemini está marcando os destaques da legenda")
    r = roteiro.escrever(f.no_editado, f.linha.duracao, biblioteca=biblioteca,
                         cartoes=edicao.animacoes, idioma=edicao.idioma,
                         nomes_de_icones=icones.nomes(), proibidas=censura.lista(edicao.bipe),
                         destaques=destaques)
    f.plano.cartoes = r.cartoes
    f.plano.roteiro = r.para_json()
    if destaques and r.destaques:
        f.plano.blocos = plano.montar_paginas(f.no_editado, f.linha.duracao, r.destaques)
    if r.aviso:
        avisar("cortando", 1.0, r.aviso)
    return r


def _mixar(f: _Fala, edicao: OpcoesDeEdicao) -> None:
    """O som final: a fala cortada e os efeitos, com os dos cartões, e nenhum efeito em
    cima de um bipe."""
    p = f.plano
    if p.sons or p.cartoes:
        p.sons = (plano.com_sons_dos_cartoes(p.sons, p.cartoes, p.bipes) if edicao.sons
                  else [])
    if f.audio is not None:
        f.som = montar_audio(f.audio, f.linha, p, edicao.volume_dos_sons)


def _resumo(r: roteiro.Roteiro | None) -> dict:
    if r is None:
        return {}
    return {"por": r.por, "aviso": r.aviso, "pedidos": r.pedidos,
            "cenas": sum(len(e) for e in r.escolhas), "cartoes": len(r.cartoes)}


#: Fora da janela, os cartões da janela ficam nesta faixa de um quadro em pé (longe da
#: legenda, embaixo, e da interface do Shorts, em cima).
FAIXA_DOS_CARTOES = (0.10, 0.62)


def _cartoes_no_quadro(img: Image.Image, cartoes: Sequence, t: float) -> Image.Image:
    """Os cartões por cima de um quadro inteiro (o vídeo único e a montagem sem janela):
    os do palco num 16:9 na altura do rosto, os da janela numa faixa do quadro."""
    ativos = [c for c in cartoes if c.inicio <= t < c.fim]
    if not ativos:
        return img
    tela = img.convert("RGBA")
    largura, altura = tela.size
    em_pe = altura > largura * 1.2
    if any(c.no_palco for c in ativos):
        ap = round(largura * 9 / 16) if em_pe else altura
        palco = Image.new("RGBA", (largura, ap), (0, 0, 0, 0))
        for c in ativos:
            cartoes_mod.desenhar(palco, c, t, palco=True)
        y = round(altura * 0.4 - ap / 2) if em_pe else 0
        tela.alpha_composite(palco, (0, max(0, y)))
    if any(not c.no_palco for c in ativos):
        y0, y1 = (round(altura * FAIXA_DOS_CARTOES[0]), round(altura * FAIXA_DOS_CARTOES[1])) \
            if em_pe else (0, altura)
        faixa = Image.new("RGBA", (largura, y1 - y0), (0, 0, 0, 0))
        for c in ativos:
            cartoes_mod.desenhar(faixa, c, t, palco=False)
        tela.alpha_composite(faixa, (0, y0))
    return tela.convert("RGB")


def _numero_do_numpy(valor):
    """Um número do numpy no plano vira o número do Python (o JSON não conhece os dele)."""
    if isinstance(valor, np.generic):
        return valor.item()
    raise TypeError(f"{type(valor).__name__} não vai para o JSON")


def _terminar(p: plano.Plano, destino: Path, saida_r: saida_mod.OpcoesDeSaida,
              avisar: Progresso) -> tuple[Path, list[Path]]:
    plano_json = destino.with_name(destino.stem + ".plano.json")
    plano_json.write_text(json.dumps(p.para_json(), ensure_ascii=False, indent=1,
                                     default=_numero_do_numpy), encoding="utf-8")
    legendas = exportar.gravar(p, destino, com_srt=saida_r.srt, com_vtt=saida_r.vtt)
    avisar("pronto", 1.0, "")
    return plano_json, legendas


def editar(entrada: Path | None, destino: Path, edicao: OpcoesDeEdicao,
           opcoes_saida: saida_mod.OpcoesDeSaida, *, previa_s: float | None = None,
           progresso: Progresso | None = None,
           cancelar: Callable[[], bool] | None = None,
           montagem: Montagem | None = None) -> Resultado:
    """Edita ``entrada`` (ou a ``montagem``, em camadas) e grava em ``destino``.

    Levanta :class:`Cancelado` se pedirem."""
    comeco = time.monotonic()
    avisar = progresso or (lambda etapa, fracao, detalhe: None)
    parar = cancelar or (lambda: False)
    erros = edicao.problemas() + opcoes_saida.problemas()
    if montagem is not None:
        erros += montagem.problemas()
    if erros:
        raise ValueError("; ".join(erros))
    saida_r = opcoes_saida.resolvidas()
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    if montagem is not None:
        return _editar_montagem(montagem, destino, edicao, saida_r, previa_s, avisar, parar,
                                comeco)

    entrada = Path(entrada)
    info = video_mod.sondar(entrada)
    prep = (_preparar_fala([entrada], edicao, avisar, parar) if info.tem_audio
            else _Preparada(entrada, info.duracao, False))
    f = _planejar(prep.arquivo, info.duracao, info.tem_audio, edicao, saida_r, previa_s,
                  vertical=info.vertical, mover=False, avisar=avisar, parar=parar,
                  palavras=prep.palavras, bipes=prep.bipes)
    r = _escrever_roteiro(f, edicao, avisar)
    _mixar(f, edicao)
    linha, p, duracao, som_final = f.linha, f.plano, f.duracao, f.som

    largura, altura = saida_mod.tamanho(info.largura, info.altura, saida_r.resolucao,
                                        saida_r.formato)
    fps = saida_mod.fps_de_saida(info.fps, saida_r.fps, saida_r.formato)
    legenda = Legenda(largura, altura, vertical=info.vertical, tamanho=edicao.tamanho_legenda)
    passo = 1.0 / float(fps)
    total_quadros = max(1, round(linha.duracao * float(fps)))

    with video_mod.Gravador(destino, saida_r, largura, altura, fps,
                            com_audio=som_final is not None) as gravador:
        if som_final is not None:
            gravador.preparar_audio(som_final)
        ultimo = None
        for t_src, matriz in video_mod.quadros(entrada, info.rotacao):
            if t_src > duracao:
                break
            t_out = linha.para_saida(t_src)
            if t_out is None:
                continue
            ultimo = matriz
            while gravador.indice < total_quadros and gravador.indice * passo <= t_out + passo / 2:
                _desenhar_quadro(gravador, matriz, p, legenda, edicao, largura, altura,
                                 gravador.indice * passo)
                if gravador.indice % 15 == 0:
                    avisar("desenhando", gravador.indice / total_quadros,
                           f"quadro {gravador.indice} de {total_quadros}")
                    if parar():
                        raise Cancelado
        while ultimo is not None and gravador.indice < total_quadros:
            _desenhar_quadro(gravador, ultimo, p, legenda, edicao, largura, altura,
                             gravador.indice * passo)
        avisar("finalizando", 0.5, "fechando o arquivo")

    plano_json, legendas = _terminar(p, destino, saida_r, avisar)
    return Resultado(destino, plano_json, legendas, f.palavras, duracao, linha.duracao,
                     time.monotonic() - comeco, largura, altura, _resumo(r))


def _desenhar_quadro(gravador: video_mod.Gravador, matriz: np.ndarray, p: plano.Plano,
                     legenda: Legenda, edicao: OpcoesDeEdicao, largura: int, altura: int,
                     t: float) -> None:
    img = Image.fromarray(matriz)
    nivel = nivel_de_zoom(p, t)
    caixa = janela(img.width, img.height, nivel, edicao.ancora_x, edicao.ancora_y)
    if nivel > 1.0005 or img.size != (largura, altura):
        img = img.resize((largura, altura), Image.BILINEAR, box=caixa)
    img = _cartoes_no_quadro(img, p.cartoes, t)
    _icones(img, p, t)
    legenda.desenhar(img, p, t)
    gravador.quadro(np.asarray(img))


def _editar_montagem(montagem: Montagem, destino: Path, edicao: OpcoesDeEdicao,
                     saida_r: saida_mod.OpcoesDeSaida, previa_s: float | None,
                     avisar: Progresso, parar: Callable[[], bool], comeco: float) -> Resultado:
    """O vídeo em camadas: o fundo (um vídeo, ou as cenas da biblioteca) e, por cima, a
    pessoa, o personagem ou nada; com ou sem a janela e a câmera.

    O laço anda pelos quadros de saída: o fundo de vídeo e a pessoa buscam o quadro do
    instante de origem (os vídeos podem ter fps diferentes); as cenas e o personagem
    andam pelo tempo de saída, para não pular nos cortes."""
    biblioteca = None
    if montagem.cenas is not None:
        avisar("transcrevendo", 0.0, "lendo a biblioteca de cenas")
        biblioteca = cenas.ler_matriz(Path(montagem.matriz).read_text(encoding="utf-8"),
                                      cenas.clipes_da_pasta(Path(montagem.cenas)))
        info_do_fundo, base, fps_base = None, (1920, 1080), Fraction(30)
    else:
        info_do_fundo = video_mod.sondar(montagem.fundo)
        base, fps_base = (info_do_fundo.largura, info_do_fundo.altura), info_do_fundo.fps
    prep = _preparar_fala(montagem.arquivos_da_fala(), edicao, avisar, parar)
    if not prep.tem_audio:
        avisar("transcrevendo", 1.0, "sem fala: o vídeo sai sem cortes e sem legenda")

    largura, altura = saida_mod.tamanho(*tamanho_do_quadro(montagem.formato, *base),
                                        saida_r.resolucao, saida_r.formato)
    f = _planejar(prep.arquivo, prep.duracao, prep.tem_audio, edicao, saida_r, previa_s,
                  vertical=altura > largura, mover=edicao.mover, avisar=avisar, parar=parar,
                  palavras=prep.palavras, bipes=prep.bipes)
    r = _escrever_roteiro(f, edicao, avisar, biblioteca)
    _mixar(f, edicao)
    linha, p = f.linha, f.plano

    if montagem.pessoa is not None and montagem.recorte == "modnet":
        if not recorte.modelo_baixado():
            avisar("desenhando", 0.0, f"baixando o modelo de recorte ({recorte.TAMANHO}), "
                                      "só na primeira vez")
        if not recorte.preparar_modelo():
            raise RuntimeError("Não consegui baixar o modelo de recorte. Confira a internet, "
                               "ou envie o vídeo da pessoa já sem fundo.")
    if biblioteca is not None and r is not None:
        fundo = cenas.FundoDeCenas(cenas.montar_trilha(r.blocos, r.escolhas, biblioteca))
    else:
        fundo = video_mod.Cursor(montagem.fundo, info_do_fundo.rotacao,
                                 duracao=info_do_fundo.duracao)
    na_saida = biblioteca is not None
    camada = camada_da_montagem(montagem)
    falas = janela_mod.falas(f.no_editado)
    deitado = largura > altura * 1.2
    if edicao.janela:
        planos = janela_mod.dirigir(linha.duracao, p.cartoes, p.zoom, deitado=deitado)
        if not edicao.mover:
            # Parado: a janela e a câmera continuam, e o personagem fica no centro.
            planos = [janela_mod.Plano(x.t, x.janela, "centro", x.zoom, x.foco, x.prioridade)
                      for x in planos]
        montador = janela_mod.MontadorDeJanela(largura, altura, fundo=fundo,
                                               fundo_na_saida=na_saida, camada=camada,
                                               planos=planos, cartoes=p.cartoes, falas=falas)
    else:
        montador = Montador(montagem, p, largura, altura, info_do_fundo, mover=edicao.mover,
                            fundo=fundo if na_saida else None, fundo_na_saida=na_saida,
                            camada=camada, falas=falas)
    fps = saida_mod.fps_de_saida(fps_base, saida_r.fps, saida_r.formato)
    legenda = Legenda(largura, altura, vertical=altura > largura,
                      tamanho=edicao.tamanho_legenda)
    passo = 1.0 / float(fps)
    total_quadros = max(1, round(linha.duracao * float(fps)))

    with video_mod.Gravador(destino, saida_r, largura, altura, fps,
                            com_audio=f.som is not None) as gravador:
        if f.som is not None:
            gravador.preparar_audio(f.som)
        for i in range(total_quadros):
            t_saida = i * passo
            t_origem = linha.para_origem(t_saida)
            if edicao.janela:
                img, estado = montador.quadro(t_origem, t_saida, extra=empurrao(p, t_saida))
                area = (estado.x, estado.y, estado.largura, estado.altura)
                _icones(img, p, t_saida, 0, area)
                legenda.desenhar(img, p, t_saida, base=None if deitado else estado.legenda)
            else:
                img = montador.quadro(t_origem, t_saida, nivel=nivel_base(p, t_saida),
                                      extra=empurrao(p, t_saida))
                img = _cartoes_no_quadro(img, p.cartoes, t_saida)
                _icones(img, p, t_saida, montador.lado_livre(t_saida))
                legenda.desenhar(img, p, t_saida)
            gravador.quadro(np.asarray(img))
            if i % 15 == 0:
                avisar("desenhando", i / total_quadros, f"quadro {i} de {total_quadros}")
                if parar():
                    raise Cancelado
        avisar("finalizando", 0.5, "fechando o arquivo")

    plano_json, legendas = _terminar(p, destino, saida_r, avisar)
    return Resultado(destino, plano_json, legendas, f.palavras, f.duracao, linha.duracao,
                     time.monotonic() - comeco, largura, altura, _resumo(r))


__all__ = ["Cancelado", "Resultado", "editar", "empurrao", "janela", "montar_audio",
           "nivel_base", "nivel_de_zoom"]
