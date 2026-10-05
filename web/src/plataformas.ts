/**
 * As plataformas onde o vídeo vai ser postado, escolhidas no passo 1. Cada uma pede um
 * formato de thumbnail e corta a capa do seu jeito; a recomendação sai do formato do vídeo.
 *
 * Pesquisado em 05/10/2026:
 * - YouTube: 1280×720 (16:9), aparece inteira.
 * - Shorts: capa 1080×1920. Na busca e no início, o YouTube mostra só o meio dela, em 3:2.
 *   A capa própria só vale para o Programa de Parcerias, pelo computador (desde 25/07/2026).
 * - TikTok: capa 1080×1920. O perfil mostra o meio em 3:4, com as visualizações embaixo.
 * - Reels: capa 1080×1920. O perfil mostra o meio em 3:4, e o feed, em 4:5.
 */
import type {FormatoDoQuadro, VideoInfo} from './tipos';

export type Plataforma = 'youtube' | 'shorts' | 'tiktok' | 'reels';

/** Uma faixa da capa que aparece num lugar da plataforma, em frações da altura. Com
 *  ``soTexto``, só a chamada precisa caber nela: na busca do YouTube, a capa do Short
 *  aparece em 3:2, e o que se recomenda é manter o texto no meio (o rosto pode passar). */
export type Recorte = {onde: string; proporcao: string; y0: number; y1: number; soTexto?: boolean};

export const PLATAFORMAS: Record<Plataforma, {
  nome: string; curto: string; tamanho: string; emPe: boolean; recortes: Recorte[]; nota?: string;
}> = {
  youtube: {nome: 'YouTube', curto: 'YouTube', tamanho: '1280x720', emPe: false, recortes: []},
  shorts: {
    nome: 'YouTube Shorts', curto: 'Shorts', tamanho: '1080x1920', emPe: true,
    recortes: [{onde: 'a busca do YouTube', proporcao: '3:2', y0: 0.3125, y1: 0.6875, soTexto: true}],
    nota: 'A capa própria de um Short só vale para quem está no Programa de Parcerias do YouTube, e só pelo computador.',
  },
  tiktok: {
    nome: 'TikTok', curto: 'TikTok', tamanho: '1080x1920', emPe: true,
    recortes: [{onde: 'o perfil do TikTok', proporcao: '3:4', y0: 0.125, y1: 0.875}],
  },
  reels: {
    nome: 'Instagram Reels', curto: 'Reels', tamanho: '1080x1920', emPe: true,
    recortes: [{onde: 'o perfil do Instagram', proporcao: '3:4', y0: 0.125, y1: 0.875},
      {onde: 'o feed do Instagram', proporcao: '4:5', y0: 0.1484, y1: 0.8516}],
  },
};

export const ORDEM: Plataforma[] = ['youtube', 'shorts', 'tiktok', 'reels'];

const deitado = (v: VideoInfo) => v.largura > v.altura * 1.2;

/** Deitado, o YouTube; em pé ou quadrado, as três de vídeo curto. */
export function recomendadas(video: VideoInfo | null): Plataforma[] {
  if (!video) return [];
  return deitado(video) ? ['youtube'] : ['shorts', 'tiktok', 'reels'];
}

/** "Shorts, TikTok e Reels". */
export function juntar(nomes: string[]): string {
  return nomes.length < 2 ? nomes.join('') : `${nomes.slice(0, -1).join(', ')} e ${nomes[nomes.length - 1]}`;
}

/** As plataformas marcadas que pedem este tamanho, na ordem de sempre. */
export function deTamanho(lista: Plataforma[], tamanho: string): Plataforma[] {
  return ORDEM.filter((p) => lista.includes(p) && PLATAFORMAS[p].tamanho === tamanho);
}

/** Os tamanhos de thumbnail que as plataformas pedem, um por formato. */
export function tamanhosDe(lista: Plataforma[]): string[] {
  return [...new Set(ORDEM.filter((p) => lista.includes(p)).map((p) => PLATAFORMAS[p].tamanho))];
}

export type Faixa = {y0: number; y1: number};

/** A faixa da capa que aparece em todos os recortes das plataformas deste tamanho: a da
 *  chamada e, em ``rosto``, a do rosto (sem os recortes que valem só para o texto). */
export function faixaSegura(lista: Plataforma[], tamanho: string): Faixa & {rosto: Faixa} {
  const texto = {y0: 0, y1: 1};
  const rosto = {y0: 0, y1: 1};
  for (const p of deTamanho(lista, tamanho)) {
    for (const r of PLATAFORMAS[p].recortes) {
      for (const f of r.soTexto ? [texto] : [texto, rosto]) {
        f.y0 = Math.max(f.y0, r.y0);
        f.y1 = Math.min(f.y1, r.y1);
      }
    }
  }
  return {...texto, rosto};
}

/** Os recortes para desenhar na prévia, sem repetir: o 3:4 do TikTok e o do Instagram são
 *  o mesmo. */
export function recortesDe(lista: Plataforma[], tamanho: string): {nome: string; y0: number; y1: number}[] {
  const grupos = new Map<string, {onde: string[]; proporcao: string; y0: number; y1: number}>();
  for (const p of deTamanho(lista, tamanho)) {
    for (const r of PLATAFORMAS[p].recortes) {
      const chave = `${r.y0}-${r.y1}`;
      const g = grupos.get(chave) ?? {onde: [], proporcao: r.proporcao, y0: r.y0, y1: r.y1};
      g.onde.push(r.onde);
      grupos.set(chave, g);
    }
  }
  return [...grupos.values()].map((g) => ({nome: `${juntar(g.onde)} (${g.proporcao})`, y0: g.y0, y1: g.y1}));
}

/** Na montagem, o quadro que as plataformas pedem; ``null`` quando elas se misturam. */
export function quadroDe(lista: Plataforma[]): FormatoDoQuadro | null {
  const emPe = lista.filter((p) => PLATAFORMAS[p].emPe).length;
  if (!lista.length) return null;
  return emPe === lista.length ? 'vertical' : emPe === 0 ? 'horizontal' : null;
}

/** O que avisar quando o vídeo não combina com o que foi marcado. */
export function avisos(lista: Plataforma[], video: VideoInfo | null, montagem: boolean): string[] {
  const saida: string[] = [];
  const algumaEmPe = lista.some((p) => PLATAFORMAS[p].emPe);
  if (montagem) {
    if (algumaEmPe && lista.includes('youtube')) {
      saida.push('O YouTube é deitado e as outras são em pé: o vídeo sai no formato escolhido no passo 4.');
    }
    return saida;
  }
  if (!video) return saida;
  if (!deitado(video) && lista.includes('youtube')) {
    saida.push('Em pé e com até 3 minutos, o YouTube publica este vídeo como Short: vale marcar Shorts também.');
  }
  if (deitado(video) && algumaEmPe) {
    saida.push('Este vídeo é deitado: no YouTube ele não vira Short, e no TikTok e nos Reels aparece com faixas. '
      + 'Para encher a tela, use a montagem em camadas com o quadro em pé.');
  }
  return saida;
}
