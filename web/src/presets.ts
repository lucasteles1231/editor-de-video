/**
 * Os presets na página: escolher um preenche as edições, a saída e o modelo e a cor da
 * thumbnail (o formato vem da plataforma); o cartão marcado é calculado pelo que está na
 * tela.
 */
import type {Edicao, Preset, Saida, ThumbConfig} from './tipos';

const igual = (a: unknown, b: unknown) =>
  typeof a === 'number' && typeof b === 'number' ? Math.abs(a - b) < 1e-6 : a === b;

/** O preset cujas edições e saída batem com as da tela; ``null`` é "Personalizado". A
 *  thumbnail fica fora da conta: é só o ponto de partida, e uma ideia do Gemini já troca a
 *  cor dela. */
export function presetMarcado(presets: Preset[], edicao: Edicao, saida: Saida): string | null {
  const bate = (p: Preset) =>
    Object.entries(p.edicao).every(([k, v]) => igual(edicao[k as keyof Edicao], v))
    && Object.entries(p.saida).every(([k, v]) => igual(saida[k as keyof Saida], v));
  return presets.find(bate)?.nome ?? null;
}

type Tela = {edicao: Edicao; saida: Saida; thumb: ThumbConfig};

/** O preset aplicado. O idioma, o modelo do Whisper e o centro do zoom ficam como estão. */
export function aplicarPreset(p: Preset, tela: Tela): Tela {
  return {
    edicao: {...tela.edicao, ...p.edicao},
    saida: {...tela.saida, ...p.saida},
    thumb: {...tela.thumb, modelo: p.thumb.modelo, cor: p.thumb.cor},
  };
}
