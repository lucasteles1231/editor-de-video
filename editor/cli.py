"""
O comando ``editar``.

    editar                       abre a interface no navegador
    editar video.mp4             edita direto no terminal
    editar video.mp4 --formato webm --resolucao 720p --sem-cortes
    editar --formatos            o que este computador consegue gravar
"""
from __future__ import annotations

import argparse
import contextlib
import logging
import sys
import time
from pathlib import Path

from editor import __version__
from editor import saida as saida_mod
from editor.opcoes import OpcoesDeEdicao
from editor.transcricao import MODELOS


def _utf8() -> None:
    """Acentos no console antigo do Windows: sem isto, "transcrição" quebra a saída."""
    for fluxo in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            fluxo.reconfigure(encoding="utf-8", errors="replace")


def _ancora(texto: str) -> tuple[float, float]:
    try:
        x, y = (float(v) for v in texto.split(","))
    except ValueError as erro:
        raise argparse.ArgumentTypeError("use x,y entre 0 e 1, por exemplo 0.5,0.4") from erro
    return x, y


class _Formato(argparse.HelpFormatter):
    def add_usage(self, usage, actions, groups, prefix=None):
        super().add_usage(usage, actions, groups, prefix or "uso: ")


def argumentos() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="editar", formatter_class=_Formato,
        description="Edita vídeos falados no estilo dos Shorts: legenda karaokê, cortes de "
                    "silêncio, zoom, adesivos, ícones e sons. Tudo no seu computador.",
        epilog="Sem nenhum vídeo, abre a interface no navegador.", add_help=False)
    # Os títulos e a ajuda que o argparse escreve em inglês.
    p._positionals.title = "argumento"
    p._optionals.title = "opções"
    p.add_argument("-h", "--ajuda", "--help", action="help", help="mostra esta ajuda e sai")
    p.add_argument("video", nargs="?", type=Path, help="o vídeo a editar")
    p.add_argument("-o", "--saida", type=Path, help="onde gravar (padrão: <nome>-editado.<ext>)")
    g = p.add_argument_group("edição")
    g.add_argument("--sem-cortes", action="store_true", help="não corta os silêncios")
    g.add_argument("--sem-zoom", action="store_true", help="sem zoom de ênfase")
    g.add_argument("--sem-adesivos", action="store_true", help="sem palavras que saltam")
    g.add_argument("--sem-icones", action="store_true", help="sem ícones automáticos")
    g.add_argument("--sem-sons", action="store_true", help="sem efeitos sonoros")
    g.add_argument("--pausa", type=float, default=0.45, help="pausa máxima mantida (s)")
    g.add_argument("--zoom", type=float, default=1.12, help="nível do zoom (1.12 = 12%%)")
    g.add_argument("--ancora", type=_ancora, default=(0.5, 0.40),
                   help="centro do zoom em x,y (padrão 0.5,0.4)")
    g.add_argument("--tamanho-legenda", type=float, default=1.0,
                   help="1.0 padrão, 0.8 menor, 1.25 maior")
    g.add_argument("--idioma", default="pt", help="idioma da fala (pt, en, es...)")
    g.add_argument("--modelo", default="small", choices=list(MODELOS),
                   help="tamanho do Whisper (padrão small)")
    g.add_argument("--previa", type=float, metavar="SEGUNDOS",
                   help="edita só os primeiros segundos, para testar rápido")
    m = p.add_argument_group("montagem em camadas (um fundo e, por cima, você ou um personagem)")
    m.add_argument("--fundo", type=Path, metavar="VIDEO",
                   help="o vídeo de fundo, sem pessoa (tela gravada, jogo, slides)")
    m.add_argument("--pessoa", type=Path, metavar="VIDEO",
                   help="o vídeo de você falando, que vai por cima do fundo")
    m.add_argument("--personagem", type=Path, metavar="ANIMACAO",
                   help="um GIF, PNG animado ou WebP de personagem, em loop por cima")
    m.add_argument("--audio", type=Path, metavar="ARQUIVO",
                   help="a narração à parte (sem ela, vale o som da pessoa ou do fundo)")
    m.add_argument("--recorte", choices=["modnet", "transparente"],
                   help="como tirar o fundo da pessoa (padrão: o alfa do arquivo, se houver)")
    m.add_argument("--quadro", default="fundo",
                   choices=["fundo", "vertical", "horizontal", "quadrado"],
                   help="o formato do vídeo final (padrão: o do fundo)")
    m.add_argument("--parada", action="store_true",
                   help="a pessoa ou o personagem não muda de lugar")
    m.add_argument("--manter-fundo-do-personagem", action="store_true",
                   help="não tira o fundo de cor única do personagem")
    s = p.add_argument_group("saída")
    s.add_argument("--formato", choices=list(saida_mod.FORMATOS),
                   help="padrão: a extensão do -o, ou mp4")
    s.add_argument("--codec", default="", choices=list(saida_mod.CODECS),
                   help="padrão: o melhor do formato")
    s.add_argument("--resolucao", default="original", choices=list(saida_mod.RESOLUCOES))
    s.add_argument("--fps", default="original", choices=list(saida_mod.FPS))
    s.add_argument("--qualidade", default="alta", choices=list(saida_mod.QUALIDADES))
    s.add_argument("--srt", action="store_true", help="grava também a legenda .srt")
    s.add_argument("--vtt", action="store_true", help="grava também a legenda .vtt")
    i = p.add_argument_group("interface")
    i.add_argument("--porta", type=int, default=0, help="porta da interface (padrão: livre)")
    i.add_argument("--sem-navegador", action="store_true", help="não abre o navegador")
    p.add_argument("--formatos", action="store_true",
                   help="mostra o que este computador consegue gravar")
    p.add_argument("--versao", action="version", version=f"editor-de-video {__version__}",
                   help="mostra a versão e sai")
    return p


class _Barra:
    """O progresso numa linha só do terminal."""

    def __init__(self) -> None:
        self.etapa = ""

    def __call__(self, etapa: str, fracao: float, detalhe: str) -> None:
        if etapa != self.etapa and self.etapa:
            print()
        self.etapa = etapa
        texto = f"  {etapa:<12} {fracao * 100:5.1f}%  {detalhe}"
        print(f"\r{texto[:110]:<110}", end="", flush=True)


def _formato_de(caminho: Path | None) -> str | None:
    if caminho is None:
        return None
    ext = caminho.suffix.lower().lstrip(".")
    return ext if ext in saida_mod.FORMATOS else None


def main(argv: list[str] | None = None) -> int:
    _utf8()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    a = argumentos().parse_args(argv)

    if a.formatos:
        for formato, d in saida_mod.disponiveis().items():
            print(f"{formato:5} vídeo: {', '.join(d['codecs']):24} áudio: "
                  f"{', '.join(d['audios']) or '—'}")
        return 0

    if a.video is None and a.fundo is None and not (a.pessoa or a.personagem or a.audio):
        from editor.servidor import abrir

        return abrir(porta=a.porta, navegador=not a.sem_navegador)

    montagem, erro = _montagem(a)
    if erro:
        print(erro, file=sys.stderr)
        return 2
    principal = montagem.fundo if montagem is not None else a.video
    edicao = OpcoesDeEdicao(cortes=not a.sem_cortes, zoom=not a.sem_zoom,
                            adesivos=not a.sem_adesivos, icones=not a.sem_icones,
                            sons=not a.sem_sons, pausa_maxima=a.pausa, nivel_zoom=a.zoom,
                            ancora_x=a.ancora[0], ancora_y=a.ancora[1],
                            tamanho_legenda=a.tamanho_legenda, idioma=a.idioma,
                            modelo=a.modelo, mover=not a.parada)
    # Sem --formato, vale a extensão do -o: "-o final.mov" grava MOV.
    formato = a.formato or _formato_de(a.saida) or "mp4"
    saida = saida_mod.OpcoesDeSaida(formato=formato, codec=a.codec, resolucao=a.resolucao,
                                    fps=a.fps, qualidade=a.qualidade, srt=a.srt, vtt=a.vtt)
    erros = edicao.problemas() + saida.problemas()
    if montagem is not None:
        erros += montagem.problemas()
    if erros:
        for e in erros:
            print(f"erro: {e}", file=sys.stderr)
        return 2
    destino = a.saida or principal.with_name(f"{principal.stem}-editado.{formato}")

    from editor.render import editar

    print(f"editando {principal.name} → {destino.name}")
    comeco = time.monotonic()
    r = editar(None if montagem is not None else a.video, destino, edicao, saida,
               previa_s=a.previa, progresso=_Barra(), montagem=montagem)
    print(f"\n\npronto em {time.monotonic() - comeco:.0f} s: {r.video}")
    print(f"  {r.duracao_original:.1f} s → {r.duracao_final:.1f} s  ·  {r.largura}×{r.altura}"
          f"  ·  {r.palavras} palavras")
    for extra in (r.plano, *r.legendas):
        print(f"  {extra}")
    return 0


def _montagem(a: argparse.Namespace):
    """A montagem pedida nas flags (ou ``None`` sem ``--fundo``), e o erro, se houver.

    ``editar eu.mp4 --fundo tela.mp4`` também vale: com ``--fundo`` e sem ``--pessoa`` nem
    ``--personagem``, o vídeo do argumento é a pessoa."""
    from editor import video as video_mod
    from editor.montagem import Montagem

    if a.fundo is None:
        if a.pessoa or a.personagem or a.audio:
            return None, "--pessoa, --personagem e --audio vão junto com --fundo"
        if a.video is None or not a.video.is_file():
            return None, f"não achei o vídeo: {a.video}"
        return None, ""
    pessoa = a.pessoa
    if a.video is not None:
        if pessoa is not None or a.personagem is not None:
            return None, "na montagem, passe a pessoa só por --pessoa (ou o personagem)"
        pessoa = a.video
    for nome, caminho in (("fundo", a.fundo), ("pessoa", pessoa),
                          ("personagem", a.personagem), ("áudio", a.audio)):
        if caminho is not None and not caminho.is_file():
            return None, f"não achei o {nome}: {caminho}"
    recorte = a.recorte
    if pessoa is not None and recorte is None:
        recorte = "transparente" if video_mod.tem_alfa(pessoa) else "modnet"
    return Montagem(a.fundo, pessoa=pessoa, personagem=a.personagem, audio=a.audio,
                    recorte=recorte or "modnet", formato=a.quadro,
                    tirar_fundo_do_personagem=not a.manter_fundo_do_personagem), ""


__all__ = ["argumentos", "main"]
