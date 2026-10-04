/**
 * Medir e quebrar o texto da thumbnail com as fontes de verdade, carregadas na página
 * antes de qualquer medida: a Anton na chamada, a DejaVu Sans Bold no resto.
 */
export const FAMILIA = 'DejaVu Sans';
/** A fonte da chamada. Condensada: no mesmo espaço cabe uns 40% mais letra que na DejaVu
 *  (medido no Stickman), e a chamada é lida num quadro de 120 px de largura. */
export const TITULO = 'Anton';

let contexto: CanvasRenderingContext2D | null = null;

function pincel(px: number, familia: string): CanvasRenderingContext2D | null {
  if (!contexto) contexto = document.createElement('canvas').getContext('2d');
  if (contexto) contexto.font = `${familia === TITULO ? 400 : 700} ${px}px "${familia}", sans-serif`;
  return contexto;
}

export function medir(texto: string, px: number, familia = FAMILIA): number {
  const c = pincel(px, familia);
  if (!c) return texto.length * px * (familia === TITULO ? 0.45 : 0.66);
  return c.measureText(texto).width;
}

/** Quanto a tinta sobe e desce da linha de base. Com acento, sobe mais que a maiúscula:
 *  "PULMÃO" tem o til acima do P, e a linha de cima não pode encostar nele. */
export function tinta(texto: string, px: number, familia = TITULO): {sobe: number; desce: number} {
  const c = pincel(px, familia);
  if (!c) return {sobe: px * 0.8, desce: px * 0.05};
  const m = c.measureText(texto);
  return {sobe: m.actualBoundingBoxAscent, desce: Math.max(0, m.actualBoundingBoxDescent)};
}

let carregadas: Promise<void> | null = null;

/** Carrega as fontes servidas pelo editor; as medidas só valem depois disto. */
export function carregarFonte(): Promise<void> {
  if (!carregadas) {
    const faces = [new FontFace(FAMILIA, 'url(/fontes/DejaVuSans-Bold.ttf)', {weight: '700'}),
      new FontFace(TITULO, 'url(/fontes/Anton-Regular.ttf)', {weight: '400'})];
    carregadas = Promise.all(faces.map((f) => f.load())).then((prontas) => {
      for (const f of prontas) document.fonts.add(f);
    });
  }
  return carregadas;
}

export type PalavraPosta = {texto: string; indice: number; x: number; largura: number};
/** ``base``: a linha de base, medida do topo da linha. */
export type Linha = {palavras: PalavraPosta[]; largura: number; altura: number; base: number};
export type Diagramacao = {px: number; linhas: Linha[]; altura: number};

/** O adesivo da palavra de destaque, em relação à letra: a folga em volta da tinta. */
export const ADESIVO_FOLGA_X = 0.2;
export const ADESIVO_FOLGA_Y = 0.13;
export const ADESIVO_GIRO = -4;
/** O vão entre uma linha e a seguinte, além da tinta. */
const VAO = 0.1;

function larguraDe(texto: string, px: number, destaque: boolean, familia: string): number {
  const w = medir(texto, px, familia);
  return destaque ? w + 2 * px * ADESIVO_FOLGA_X : w;
}

/**
 * A altura de uma linha e a linha de base dela, pela tinta medida. A linha do destaque é
 * mais alta: o adesivo tem folga em volta da letra, e o giro levanta uma ponta e baixa a
 * outra — numa palavra comprida, uns 30% da letra para cada lado.
 */
function medidasDaLinha(palavras: PalavraPosta[], destaque: number, px: number,
                        familia: string): {altura: number; base: number} {
  let sobe = 0;
  let desce = 0;
  for (const w of palavras) {
    const t = tinta(w.texto, px, familia);
    sobe = Math.max(sobe, t.sobe);
    desce = Math.max(desce, t.desce);
  }
  const d = palavras.find((w) => w.indice === destaque);
  if (!d) return {altura: sobe + desce + px * VAO, base: sobe + (px * VAO) / 2};
  const folga = px * ADESIVO_FOLGA_Y;
  const giro = (d.largura / 2) * Math.sin((Math.abs(ADESIVO_GIRO) * Math.PI) / 180);
  const altura = sobe + desce + 2 * folga + 2 * giro + px * VAO;
  return {altura, base: giro + folga + sobe + (px * VAO) / 2};
}

export type OpcoesDeDiagramacao = {maxLinhas?: number; familia?: string; maiusculas?: boolean};

/** O texto como vai aparecer: a chamada da thumbnail é sempre em maiúsculas. */
export function comoAparece(texto: string, maiusculas = true): string {
  const limpo = texto.trim().replace(/\s+/g, ' ');
  return maiusculas ? limpo.toLocaleUpperCase('pt-BR') : limpo;
}

/**
 * O maior tamanho de letra em que o texto cabe em ``maxLinhas`` linhas dentro da área,
 * quebrando só entre palavras.
 */
export function diagramar(texto: string, destaque: number, larguraMax: number,
                          alturaMax: number, pxMax: number,
                          opcoes: OpcoesDeDiagramacao = {}): Diagramacao {
  const {maxLinhas = 3, familia = TITULO, maiusculas = true} = opcoes;
  const palavras = comoAparece(texto, maiusculas).split(' ').filter(Boolean);
  for (let px = Math.round(pxMax); px >= 12; px = Math.floor(px * 0.95)) {
    const espaco = medir(' ', px, familia);
    const linhas: {palavras: PalavraPosta[]; largura: number}[] = [];
    let atual: PalavraPosta[] = [];
    let largura = 0;
    let cabe = true;
    palavras.forEach((p, i) => {
      const w = larguraDe(p, px, i === destaque, familia);
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
    const postas: Linha[] = linhas.map((l) => ({...l, ...medidasDaLinha(l.palavras, destaque, px, familia)}));
    const altura = postas.reduce((soma, l) => soma + l.altura, 0);
    if (cabe && postas.length <= maxLinhas && altura <= alturaMax) {
      return {px, linhas: postas, altura};
    }
  }
  return {px: 12, linhas: [], altura: 0};
}
