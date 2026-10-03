/**
 * Medir e quebrar o título da thumbnail com a fonte de verdade (DejaVu Sans Bold),
 * carregada na página antes de qualquer medida.
 */
export const FAMILIA = 'DejaVu Sans';

let contexto: CanvasRenderingContext2D | null = null;

export function medir(texto: string, px: number): number {
  if (!contexto) contexto = document.createElement('canvas').getContext('2d');
  if (!contexto) return texto.length * px * 0.66;
  contexto.font = `700 ${px}px "${FAMILIA}", sans-serif`;
  return contexto.measureText(texto).width;
}

let carregada: Promise<void> | null = null;

/** Carrega a fonte servida pelo editor; as medidas só valem depois disto. */
export function carregarFonte(url = '/fontes/DejaVuSans-Bold.ttf'): Promise<void> {
  if (!carregada) {
    const face = new FontFace(FAMILIA, `url(${url})`, {weight: '700'});
    carregada = face.load().then((f) => {
      document.fonts.add(f);
    });
  }
  return carregada;
}

export type PalavraPosta = {texto: string; indice: number; x: number; largura: number};
/** ``base``: a linha de base, medida do topo da linha. */
export type Linha = {palavras: PalavraPosta[]; largura: number; altura: number; base: number};
export type Diagramacao = {px: number; linhas: Linha[]; altura: number};

/** O espaço extra que a palavra-destaque ocupa (ela vai num adesivo maior). */
export const DESTAQUE_ESCALA = 1.12;
export const DESTAQUE_SOBRA = 0.55;
/** O adesivo do destaque: altura (em relação à letra dele) e o giro, em graus. */
export const DESTAQUE_ALTURA = 1.32;
export const DESTAQUE_GIRO = -4;
/** Do centro do adesivo até a linha de base do texto dele, em relação à letra. */
export const DESTAQUE_BASE = 0.36;

const ALTURA_DA_LINHA = 1.22;

/**
 * A altura de uma linha e onde fica a linha de base dela. A linha do destaque é mais
 * alta: o adesivo é maior que a letra, e o giro levanta uma ponta e baixa a outra —
 * numa palavra comprida ("microfone?"), uns 30% da letra para cada lado. Com a altura
 * de uma linha comum, ele cobria o pé da linha de cima.
 */
function medidasDaLinha(palavras: PalavraPosta[], destaque: number, px: number
                        ): {altura: number; base: number} {
  const d = palavras.find((w) => w.indice === destaque);
  if (!d) return {altura: px * ALTURA_DA_LINHA, base: px * ALTURA_DA_LINHA * 0.8};
  const pxDestaque = px * DESTAQUE_ESCALA;
  const sobe = (d.largura / 2) * Math.sin((Math.abs(DESTAQUE_GIRO) * Math.PI) / 180);
  const altura = pxDestaque * DESTAQUE_ALTURA + 2 * sobe + px * 0.1;
  return {altura, base: altura / 2 + pxDestaque * DESTAQUE_BASE};
}

function larguraDe(texto: string, px: number, destaque: boolean): number {
  const w = medir(texto, destaque ? px * DESTAQUE_ESCALA : px);
  return destaque ? w + px * DESTAQUE_SOBRA : w;
}

/**
 * O maior tamanho de letra em que o título cabe em ``maxLinhas`` linhas dentro da
 * área, quebrando só entre palavras.
 */
export function diagramar(texto: string, destaque: number, larguraMax: number,
                          alturaMax: number, pxMax: number, maxLinhas = 3): Diagramacao {
  const palavras = texto.trim().split(/\s+/).filter(Boolean);
  for (let px = Math.round(pxMax); px >= 12; px = Math.floor(px * 0.94)) {
    const espaco = medir(' ', px);
    const linhas: {palavras: PalavraPosta[]; largura: number}[] = [];
    let atual: PalavraPosta[] = [];
    let largura = 0;
    let cabe = true;
    palavras.forEach((p, i) => {
      const w = larguraDe(p, px, i === destaque);
      if (w > larguraMax) cabe = false;
      const nova = atual.length ? largura + espaco + w : w;
      if (atual.length && nova > larguraMax) {
        linhas.push({palavras: atual, largura});
        atual = [];
        largura = 0;
      }
      atual.push({texto: p, indice: i, x: atual.length ? largura + espaco : 0, largura: w});
      largura = atual.length > 1 ? largura + espaco + w : w;
    });
    if (atual.length) linhas.push({palavras: atual, largura});
    const postas: Linha[] = linhas.map((l) => ({...l, ...medidasDaLinha(l.palavras, destaque, px)}));
    const altura = postas.reduce((soma, l) => soma + l.altura, 0);
    if (cabe && postas.length <= maxLinhas && altura <= alturaMax) {
      return {px, linhas: postas, altura};
    }
  }
  return {px: 12, linhas: [], altura: 0};
}
