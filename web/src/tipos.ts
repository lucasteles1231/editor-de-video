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
  ia: EstadoIa;
  recorte: {baixado: boolean; tamanho: string};
  pexels: EstadoChave;
  geracao: {restantes: number; teto: number};
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

/** Uma caixa em frações do quadro (de 0 a 1). */
export type Caixa = {x0: number; y0: number; x1: number; y1: number};

export type Modelo = 'classico' | 'numero' | 'pergunta' | 'alerta';
export type Cor = 'amarelo' | 'rosa' | 'ciano' | 'lima' | 'laranja' | 'roxo' | 'vermelho';
/** O que vai atrás da pessoa recortada: um quadro do vídeo, uma imagem ou a cor. */
export type Fundo = 'video' | 'imagem' | 'cor';
/** De que lado fica o texto na thumbnail horizontal (a pessoa vai no outro). */
export type Lado = 'esquerda' | 'direita';
export type Luz = 'nenhuma' | 'contorno' | 'halo' | 'raios';
export type AlvoDaMao = 'nenhuma' | 'titulo' | 'alvo';
export type EstiloDaMao = '3d' | 'vetor';
export type TomDaMao = 'default' | 'light' | 'medium-light' | 'medium' | 'medium-dark' | 'dark';

/** Uma imagem de fundo guardada pelo editor: enviada, do Pexels ou gerada. */
export type ImagemFundo = {
  id: string; largura: number; altura: number; origem: string; credito: string; url: string;
};

export type ThumbConfig = {
  ativo: boolean;
  texto: string;
  /** O índice da palavra que vira o adesivo; -1 nenhuma. */
  destaque: number;
  /** O instante do vídeo original de onde sai a pessoa. */
  t: number;
  icone: string;
  modelo: Modelo;
  cor: Cor;
  selo: string;
  numero: string;
  // ── o fundo ──
  fundo: Fundo;
  /** O quadro do conteúdo (fundo 'video'); null é o mesmo da pessoa. */
  fundoT: number | null;
  /** A região do quadro do conteúdo que importa (vem da IA). */
  foco: Caixa | null;
  imagem: ImagemFundo | null;
  /** 0 a 1. */
  desfoque: number;
  escurecer: number;
  vinheta: boolean;
  tom: boolean;
  // ── a pessoa ──
  recorte: boolean;
  lado: Lado;
  /** O deslocamento e o tamanho escolhidos à mão, sobre a posição automática. */
  pessoaDx: number;
  pessoaDy: number;
  pessoaEscala: number;
  espelhar: boolean;
  contorno: boolean;
  luz: Luz;
  realce: boolean;
  // ── a mão ──
  mao: AlvoDaMao;
  maoEstilo: EstiloDaMao;
  maoTom: TomDaMao;
  /** A posição escolhida à mão, em frações do quadro; null é a automática. */
  maoX: number | null;
  maoY: number | null;
  maoEscala: number;
  // ── o que a IA viu ──
  seta: boolean;
  /** O que a seta e a mão apontam, no quadro de ``rostoT``. */
  alvo: Caixa | null;
  /** O rosto que a IA viu, e em que instante: noutro quadro ele não vale mais. */
  rosto: Caixa | null;
  rostoT: number | null;
  /** O que a ideia sugeriu buscar no Pexels e a cena para gerar. */
  busca: string;
  cena: string;
  tamanhos: string[];
};

/** Uma ideia do Gemini, já conferida pelo servidor. */
export type Ideia = {
  ideia: string;
  modelo: Modelo;
  chamada: string;
  destaque: number;
  numero: string;
  selo: string;
  icone: string;
  cor: Cor;
  fundo: 'video' | 'desfocado' | 'cor' | 'banco' | 'gerado';
  quadro_fundo: number;
  t_fundo: number | null;
  foco: Caixa | null;
  busca: string;
  cena: string;
  recorte: boolean;
  quadro: number;
  t: number;
  rosto: Caixa | null;
  luz: Luz;
  mao: AlvoDaMao;
  seta: boolean;
  alvo: Caixa | null;
  /** A imagem que a página buscou (banco) ou gerou para esta ideia. */
  imagem?: ImagemFundo | null;
};

export type EstadoIa = {configurada: boolean; origem: string; final: string; falsa: boolean};
export type EstadoChave = {configurada: boolean; origem: string; final: string};

export type RecorteInfo = {ok: boolean; pessoa: Caixa | null; rosto: Caixa | null};

export type FotoPexels = {
  id: number; largura: number; altura: number; autor: string; autor_url: string; pagina: string;
  alt: string;
};
