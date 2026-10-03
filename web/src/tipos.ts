/** Os formatos que o servidor fala — espelham editor/opcoes.py e editor/saida.py. */

export type Edicao = {
  cortes: boolean;
  zoom: boolean;
  adesivos: boolean;
  icones: boolean;
  sons: boolean;
  pausa_maxima: number;
  nivel_zoom: number;
  ancora_x: number;
  ancora_y: number;
  tamanho_legenda: number;
  idioma: string;
  modelo: string;
};

export type Saida = {
  formato: string;
  codec: string;
  resolucao: string;
  fps: string;
  qualidade: string;
  audio: string;
  srt: boolean;
  vtt: boolean;
};

export type Estado = {
  versao: string;
  formatos: Record<string, {codecs: string[]; audios: string[]}>;
  codecs: Record<string, string>;
  resolucoes: string[];
  fps: string[];
  qualidades: string[];
  modelos: {nome: string; tamanho: string; baixado: boolean}[];
  padroes: {edicao: Edicao; saida: Saida};
  pasta_saida: string;
  ocupado: boolean;
  gif_max_s: number;
};

export type VideoInfo = {
  id: string;
  nome: string;
  tamanho_bytes: number;
  largura: number;
  altura: number;
  fps: number;
  duracao: number;
  vertical: boolean;
  tem_audio: boolean;
};

export type Resultado = {
  video: string;
  plano: string;
  legendas: string[];
  thumbnails?: string[];
  palavras: number;
  duracao_original: number;
  duracao_final: number;
  segundos: number;
  largura: number;
  altura: number;
};

export type Tarefa = {
  id: string;
  estado: 'rodando' | 'pronto' | 'erro' | 'cancelado';
  etapa: string;
  etapa_nome: string;
  fracao: number;
  detalhe: string;
  falta_s: number | null;
  resultado: Resultado | null;
  erro: string;
  decorrido_s: number;
};

export type Arranjo = 'embaixo' | 'em-cima' | 'lado';

export type ThumbConfig = {
  ativo: boolean;
  texto: string;
  /** O índice da palavra que vira o adesivo amarelo; -1 nenhuma. */
  destaque: number;
  /** O instante do vídeo original usado de fundo. */
  t: number;
  icone: string;
  arranjo: Arranjo;
  escurecer: number;
  tamanhos: string[];
};
