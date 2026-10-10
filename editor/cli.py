"""
O comando ``editar``.

    editar                       abre a interface no navegador
    editar video.mp4             edita direto no terminal
    editar video.mp4 --formato webm --resolucao 720p --sem-cortes
    editar video.mp4 --preset gameplay --ritmo 1.2
    editar --presets             os presets de edição
    editar --formatos            o que este computador consegue gravar

As flags de edição e de saída começam vazias: sem elas vale o preset (o padrão, se nenhum
for escolhido); com elas, a flag ganha do preset.
"""
from __future__ import annotations

import argparse
import contextlib
import logging
import sys
import time
from pathlib import Path

from editor import __version__, bloqueio, presets, sons
from editor import saida as saida_mod
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
        epilog="Sem nenhum vídeo, abre a interface no navegador. Os padrões das edições e "
               "da saída são os do preset (sem --preset, os do padrão).", add_help=False)
    # Os títulos e a ajuda que o argparse escreve em inglês.
    p._positionals.title = "argumento"
    p._optionals.title = "opções"
    p.add_argument("-h", "--ajuda", "--help", action="help", help="mostra esta ajuda e sai")
    p.add_argument("video", nargs="?", type=Path, help="o vídeo a editar")
    p.add_argument("-o", "--saida", type=Path, help="onde gravar (padrão: <nome>-editado.<ext>)")
    g = p.add_argument_group("edição")
    g.add_argument("--preset", choices=list(presets.PRESETS),
                   help="o ponto de partida (veja --presets); as outras flags ganham dele")
    g.add_argument("--sem-cortes", dest="cortes", action="store_const", const=False,
                   help="não corta os silêncios")
    g.add_argument("--sem-zoom", dest="zoom", action="store_const", const=False,
                   help="sem zoom de ênfase")
    g.add_argument("--sem-adesivos", dest="adesivos", action="store_const", const=False,
                   help="sem palavras que saltam")
    g.add_argument("--sem-icones", dest="icones", action="store_const", const=False,
                   help="sem ícones automáticos")
    g.add_argument("--sem-sons", dest="sons", action="store_const", const=False,
                   help="sem efeitos sonoros")
    g.add_argument("--pausa", dest="pausa_maxima", type=float, metavar="SEGUNDOS",
                   help="pausa máxima mantida (padrão 0.45)")
    g.add_argument("--respiro", type=float, metavar="SEGUNDOS",
                   help="o silêncio que fica no lugar de uma pausa cortada (padrão 0.15)")
    g.add_argument("--zoom", dest="nivel_zoom", type=float, metavar="NIVEL",
                   help="nível do zoom (1.12 = 12%%)")
    g.add_argument("--empurrao", type=float, metavar="NIVEL",
                   help="o zoom que o adesivo dá (0.06 = 6%%; 0 desliga)")
    g.add_argument("--ritmo", type=float, metavar="NIVEL",
                   help="de 0.5 a 2: mais alto, mais efeitos e mais próximos (padrão 1)")
    g.add_argument("--ancora", type=_ancora, default=(0.5, 0.40),
                   help="centro do zoom em x,y (padrão 0.5,0.4)")
    g.add_argument("--tamanho-legenda", dest="tamanho_legenda", type=float, metavar="NIVEL",
                   help="1.0 padrão, 0.8 menor, 1.25 maior")
    g.add_argument("--caracteres-por-linha", dest="caracteres_por_linha", type=int,
                   metavar="N", help="a largura da legenda (padrão: 18 em pé, 32 deitado)")
    g.add_argument("--tema-dos-sons", dest="tema_dos_sons", choices=list(sons.temas()),
                   help="o jeito dos efeitos sonoros (padrão: o pop e o whoosh)")
    g.add_argument("--volume-dos-sons", dest="volume_dos_sons", type=float, metavar="NIVEL",
                   help="de 0.3 a 1.5 (padrão 1)")
    g.add_argument("--som-nos-cortes", dest="som_nos_cortes", action="store_const",
                   const=True, help="um som curto e baixo em cada corte")
    g.add_argument("--sem-som-nos-cortes", dest="som_nos_cortes", action="store_const",
                   const=False, help=argparse.SUPPRESS)
    g.add_argument("--sem-sons-por-palavra", dest="sons_por_palavra", action="store_const",
                   const=False, help='sem os sons por palavra ("dinheiro" chama moedas)')
    g.add_argument("--sons-por-palavra", dest="sons_por_palavra", action="store_const",
                   const=True, help=argparse.SUPPRESS)
    g.add_argument("--animacoes", dest="animacoes", action="store_const", const=True,
                   help="cartões animados escritos pelo Gemini (selo, lista, quadro, enquete, "
                        "carimbo, destaque, flash)")
    g.add_argument("--sem-animacoes", dest="animacoes", action="store_const", const=False,
                   help=argparse.SUPPRESS)
    g.add_argument("--bipe", metavar="PALAVRAS",
                   help='palavras proibidas, separadas por vírgula ("cocaína, sexo"): uma '
                        "sílaba vira bipe na voz e asteriscos na legenda")
    g.add_argument("--voz", choices=["original", "limpa", "estudio"],
                   help="o tratamento da voz (padrão: original)")
    g.add_argument("--legenda", dest="estilo_da_legenda", choices=["classica", "destaques"],
                   help="classica (uma linha, karaokê) ou destaques (páginas de até 4 "
                        "palavras, cores e a frase de efeito numa pílula)")
    g.add_argument("--idioma", default="pt", help="idioma da fala (pt, en, es...)")
    g.add_argument("--modelo", default="small", choices=list(MODELOS),
                   help="tamanho do Whisper (padrão small)")
    g.add_argument("--previa", type=float, metavar="SEGUNDOS",
                   help="edita só os primeiros segundos, para testar rápido")
    m = p.add_argument_group("montagem em camadas (um fundo e, por cima, você ou um personagem)")
    m.add_argument("--fundo", type=Path, metavar="VIDEO",
                   help="o vídeo de fundo, sem pessoa (tela gravada, jogo, slides)")
    m.add_argument("--cenas", type=Path, metavar="PASTA",
                   help="no lugar do fundo: a pasta da biblioteca de cenas (com --matriz)")
    m.add_argument("--matriz", type=Path, metavar="ARQUIVO",
                   help="o catálogo das cenas (o cenas.json): arquivo e descrição de cada uma")
    m.add_argument("--pessoa", type=Path, metavar="VIDEO",
                   help="o vídeo de você falando, que vai por cima do fundo")
    m.add_argument("--personagem", type=Path, metavar="ANIMACAO",
                   help="um GIF, PNG animado ou WebP de personagem, em loop por cima")
    m.add_argument("--audio", type=Path, nargs="+", metavar="ARQUIVO",
                   help="o áudio separado (a narração gravada à parte); vários, um por "
                        "parágrafo, são juntados na ordem")
    m.add_argument("--fala", choices=["fundo", "pessoa", "audio"],
                   help="de onde vem o áudio (padrão: o --audio; senão a pessoa, se tiver "
                        "som; senão o fundo)")
    m.add_argument("--recorte", choices=["modnet", "transparente"],
                   help="como tirar o fundo da pessoa (padrão: o alfa do arquivo, se houver)")
    m.add_argument("--quadro", default="fundo",
                   choices=["fundo", "vertical", "horizontal", "quadrado"],
                   help="o formato do vídeo final (padrão: o do fundo)")
    m.add_argument("--parada", dest="mover", action="store_const", const=False,
                   help="a pessoa ou o personagem não muda de lugar")
    m.add_argument("--janela", dest="janela", action="store_const", const=True,
                   help="a cena numa janela 16:9 com câmera, e o personagem na borda dela")
    m.add_argument("--sem-janela", dest="janela", action="store_const", const=False,
                   help=argparse.SUPPRESS)
    m.add_argument("--mover", dest="mover", action="store_const", const=True,
                   help=argparse.SUPPRESS)
    m.add_argument("--manter-fundo-do-personagem", action="store_true",
                   help="não tira o fundo de cor única do personagem")
    s = p.add_argument_group("saída")
    s.add_argument("--formato", choices=list(saida_mod.FORMATOS),
                   help="padrão: a extensão do -o, ou mp4")
    s.add_argument("--codec", default="", choices=list(saida_mod.CODECS),
                   help="padrão: o melhor do formato")
    s.add_argument("--resolucao", choices=list(saida_mod.RESOLUCOES),
                   help="padrão: original")
    s.add_argument("--fps", choices=list(saida_mod.FPS), help="padrão: original")
    s.add_argument("--qualidade", choices=list(saida_mod.QUALIDADES), help="padrão: alta")
    s.add_argument("--srt", action="store_true", help="grava também a legenda .srt")
    s.add_argument("--vtt", action="store_true", help="grava também a legenda .vtt")
    i = p.add_argument_group("interface")
    i.add_argument("--porta", type=int, default=0, help="porta da interface (padrão: livre)")
    i.add_argument("--sem-navegador", action="store_true", help="não abre o navegador")
    p.add_argument("--formatos", action="store_true",
                   help="mostra o que este computador consegue gravar")
    p.add_argument("--presets", action="store_true", help="mostra os presets de edição")
    g2 = p.add_argument_group("a matriz da biblioteca de cenas")
    g2.add_argument("--gerar-matriz", type=Path, metavar="PASTA",
                    help="escreve o cenas.json de uma pasta de clipes: o Gemini descreve cada "
                         "cena (sem a chave, sai um rascunho para completar)")
    g2.add_argument("--assunto", metavar="TEXTO", default="",
                    help='do que são as cenas ("trailers do GTA 6"): ajuda a reconhecer '
                         "personagens")
    v = p.add_argument_group("minha voz (opcional: a sua voz narrando um roteiro)")
    v.add_argument("--instalar-voz", action="store_true",
                   help="instala o motor da voz sintetizada (~3,5 GB, num ambiente à parte)")
    v.add_argument("--criar-voz", metavar="NOME",
                   help="sem --gravacao, mostra o texto a ler; com ela, confere a leitura e "
                        "salva a voz")
    v.add_argument("--gravacao", type=Path, metavar="ARQUIVO",
                   help="a leitura do texto inteiro, gravada num arquivo (MP3, WAV, M4A)")
    v.add_argument("--vozes", action="store_true", help="mostra as vozes salvas")
    v.add_argument("--minha-voz", metavar="NOME",
                   help="narra o --roteiro com a voz salva; com --cenas ou --fundo, a "
                        "narração vira o áudio da montagem")
    v.add_argument("--roteiro", type=Path, metavar="ARQUIVO",
                   help="o texto a narrar (.txt), um parágrafo por bloco")
    v.add_argument("--pronuncia", metavar="LISTA",
                   help='como o motor deve ler uma palavra: "PEGI=pégui; GTA=gê tê á" (a '
                        "legenda continua com a grafia do roteiro)")
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


def _gerar_matriz(pasta: Path, assunto: str) -> int:
    """O ``cenas.json`` da pasta (ou ``cenas-gerada.json``, se já existe um): para revisar
    e usar com ``--cenas PASTA --matriz``."""
    import json

    from editor import catalogo

    if not pasta.is_dir():
        print(f"não achei a pasta {pasta}", file=sys.stderr)
        return 2
    clipes = catalogo.clipes_relativos(pasta)
    if not clipes:
        print(f"a pasta {pasta} não tem clipes (MP4, MOV, WebM, MKV)", file=sys.stderr)
        return 2

    def andou(prontas: int, total: int, pedidos: int) -> None:
        print(f"\r  descrevendo {prontas} de {total} cenas ({pedidos} pedidos ao Gemini)",
              end="", flush=True)

    g = catalogo.gerar(clipes, assunto=assunto, progresso=andou)
    print()
    destino = pasta / "cenas.json"
    if destino.exists():
        destino = pasta / "cenas-gerada.json"
    destino.write_text(json.dumps(g.cenas, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
    quem = {"gemini": "pelo Gemini", "falsa": "pela IA de teste",
            "rascunho": "como rascunho (sem o Gemini)"}.get(g.por, "")
    print(f"{len(g.cenas)} cenas descritas {quem}: {destino}")
    if g.aviso:
        print(f"aviso: {g.aviso}")
    print("Revise as descrições antes de usar: é delas que sai a escolha das cenas.")
    return 0


def _instalar_voz() -> int:
    from editor import motor_de_voz

    if motor_de_voz.instalado():
        print(f"a voz sintetizada já está instalada em {motor_de_voz.pasta()}")
        return 0
    print(f"instalando a voz sintetizada: {motor_de_voz.ESPACO}, {motor_de_voz.TEMPO}")
    try:
        r = motor_de_voz.instalar(progresso=lambda etapa, fracao, linha: print(
            f"\r  {etapa:<36} {fracao * 100:5.1f}%  {linha[:50]:<50}", end="", flush=True))
    except motor_de_voz.ErroDoMotor as erro:
        print(f"\nerro: {erro}", file=sys.stderr)
        return 1
    print(f"\npronto: o motor vai usar {r.get('aparelho') or 'o processador'}")
    return 0


def _criar_voz(nome: str, gravacao: Path | None) -> int:
    import tempfile

    from editor import voz_clonada

    try:
        nome = voz_clonada.nome_valido(nome)
    except voz_clonada.VozInvalida as erro:
        print(f"erro: {erro}", file=sys.stderr)
        return 2
    if gravacao is None:
        print("Leia o texto abaixo em voz alta, num lugar silencioso, com uma pausa entre os "
              "parágrafos.\nGrave num arquivo e rode de novo com --gravacao ARQUIVO.\n")
        print("\n\n".join(voz_clonada.texto_de_leitura(nome)))
        return 0
    if not gravacao.is_file():
        print(f"não achei a gravação: {gravacao}", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="voz-") as tmp:
        g = voz_clonada.Gravacao(nome, Path(tmp))
        print("conferindo a leitura (o Whisper transcreve cada parágrafo)…")
        g.receber_leitura(gravacao)
        for p in g.paragrafos:
            marca = "ok" if p.estado == "ok" else "REGRAVAR"
            print(f"  {p.indice + 1:2d}. {marca:<8} {p.cobertura:4.0%}  {p.texto[:60]}…")
            for m in p.motivos:
                print(f"      {m}")
        if not g.pronta():
            print("A voz não foi salva: grave de novo os parágrafos marcados (pela página dá "
                  "para regravar só eles).", file=sys.stderr)
            return 1
        v = voz_clonada.salvar(g)
    print(f"voz salva: {v['nome']} ({v['segundos']:.0f} s de referência). "
          f"Use com --minha-voz {v['apelido']}")
    return 0


def _narrar(nome: str, roteiro: Path | None, pronuncia: str | None, destino: Path | None
            ) -> tuple[Path | None, str]:
    """O roteiro narrado com a voz salva (e o erro, se houver)."""
    from editor import motor_de_voz, voz_clonada

    if roteiro is None or not roteiro.is_file():
        return None, "--minha-voz precisa do --roteiro (o arquivo .txt com o texto)"
    slug = voz_clonada.apelido(nome)
    lista = (voz_clonada.ler_pronuncia(pronuncia.replace(";", "\n"))
             if pronuncia is not None else None)
    destino = destino or roteiro.with_name(f"{roteiro.stem}-narrado.wav")
    try:
        n = voz_clonada.narrar(slug, roteiro.read_text(encoding="utf-8"), destino,
                               pronuncia=lista, progresso=lambda f, t: print(
                                   f"\r  narrando {f} de {t} pedaços", end="", flush=True))
    except (voz_clonada.VozInvalida, motor_de_voz.ErroDoMotor) as erro:
        return None, f"erro: {erro}"
    print(f"\nnarração: {n.caminho} ({n.segundos:.1f} s)")
    return n.caminho, ""


def main(argv: list[str] | None = None) -> int:
    _utf8()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    a = argumentos().parse_args(argv)

    # No Windows 11, o Controle Inteligente de Aplicativos pode barrar o PyAV. Sem ele
    # nada funciona, então a explicação vem antes de tudo, no lugar do traceback.
    aviso = bloqueio.conferir()
    if aviso:
        print(aviso, file=sys.stderr)
        return 1

    if a.formatos:
        for formato, d in saida_mod.disponiveis().items():
            print(f"{formato:5} vídeo: {', '.join(d['codecs']):24} áudio: "
                  f"{', '.join(d['audios']) or '—'}")
        return 0

    if a.presets:
        for pr in presets.PRESETS.values():
            print(f"{pr.nome:13} {pr.titulo}\n{'':13} {pr.frase}")
        return 0

    if a.gerar_matriz is not None:
        return _gerar_matriz(a.gerar_matriz, a.assunto)

    if a.instalar_voz:
        return _instalar_voz()
    if a.criar_voz is not None:
        return _criar_voz(a.criar_voz, a.gravacao)
    if a.vozes:
        from editor import voz_clonada

        lista = voz_clonada.vozes()
        for v in lista:
            print(f"{v['apelido']:20} {v['nome']} · criada em {v['criada']}")
        if not lista:
            print("nenhuma voz salva: crie uma com --criar-voz NOME")
        return 0
    if a.minha_voz is not None:
        if a.audio:
            print("--minha-voz já é o áudio: não passe --audio junto", file=sys.stderr)
            return 2
        so_narrar = a.fundo is None and a.cenas is None
        narracao, erro = _narrar(a.minha_voz, a.roteiro,
                                 a.pronuncia, a.saida if so_narrar else None)
        if erro:
            print(erro, file=sys.stderr)
            return 2
        if so_narrar:
            return 0
        a.audio, a.fala = [narracao], "audio"

    if a.video is None and a.fundo is None and not (a.pessoa or a.personagem or a.audio
                                                    or a.fala or a.preset or a.cenas):
        from editor.servidor import abrir

        return abrir(porta=a.porta, navegador=not a.sem_navegador)

    preset = presets.PRESETS[a.preset or "padrao"]
    montagem, erro = _montagem(a)
    if erro:
        print(erro, file=sys.stderr)
        return 2
    # Com a biblioteca, o vídeo sai ao lado da pasta das cenas ("cenas-editado.mp4").
    principal = (a.video if montagem is None
                 else Path(montagem.fundo or montagem.cenas))
    # A flag passada ganha do preset.
    edicao = preset.opcoes(**{k: getattr(a, k) for k in presets.EDICAO
                              if getattr(a, k) is not None},
                           ancora_x=a.ancora[0], ancora_y=a.ancora[1], idioma=a.idioma,
                           modelo=a.modelo)
    # Sem --formato, vale a extensão do -o: "-o final.mov" grava MOV.
    formato = a.formato or _formato_de(a.saida) or "mp4"
    da_saida = {k: getattr(a, k) or preset.saida[k] for k in presets.SAIDA}
    saida = saida_mod.OpcoesDeSaida(formato=formato, codec=a.codec, srt=a.srt, vtt=a.vtt,
                                    **da_saida)
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

    if a.fundo is None and a.cenas is None:
        if a.pessoa or a.personagem or a.audio or a.fala:
            return None, ("--pessoa, --personagem, --audio e --fala vão junto com --fundo "
                          "ou --cenas")
        if a.video is None:
            return None, ("faltou o vídeo: editar video.mp4 --preset gameplay (na página, os "
                          "presets ficam no passo 2)")
        if not a.video.is_file():
            return None, f"não achei o vídeo: {a.video}"
        return None, ""
    pessoa = a.pessoa
    if a.video is not None:
        if pessoa is not None or a.personagem is not None:
            return None, "na montagem, passe a pessoa só por --pessoa (ou o personagem)"
        pessoa = a.video
    audios = list(a.audio or [])
    for nome, caminho in (("fundo", a.fundo), ("pessoa", pessoa), ("personagem", a.personagem),
                          ("matriz", a.matriz), *(("áudio", x) for x in audios)):
        if caminho is not None and not caminho.is_file():
            return None, f"não achei o {nome}: {caminho}"
    if a.cenas is not None and not a.cenas.is_dir():
        return None, f"não achei a pasta das cenas: {a.cenas}"
    recorte = a.recorte
    if pessoa is not None and recorte is None:
        recorte = "transparente" if video_mod.tem_alfa(pessoa) else "modnet"
    return Montagem(a.fundo, pessoa=pessoa, personagem=a.personagem, audios=tuple(audios),
                    cenas=a.cenas, matriz=a.matriz,
                    recorte=recorte or "modnet", formato=a.quadro,
                    tirar_fundo_do_personagem=not a.manter_fundo_do_personagem,
                    fala=a.fala), ""


__all__ = ["argumentos", "main"]
