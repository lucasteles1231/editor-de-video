/** Os formatos que o servidor fala — espelham editor/opcoes.py e editor/saida.py. */
import type {Plataforma} from './plataformas';

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
  /** Na montagem em camadas, a pessoa (ou o personagem) muda de lugar em alguns cortes. */
  mover: boolean;
  /** De 0,5 a 2: mais alto, mais adesivos, ícones, zooms e sons, mais próximos. */
  ritmo: number;
  /** O zoom que o adesivo dá (0,06 = 6%). */
  empurrao: number;
  /** O silêncio que fica no lugar de uma pausa cortada, em segundos. */
  respiro: number;
  tema_dos_sons: string;
  som_nos_cortes: boolean;
  sons_por_palavra: boolean;
  volume_dos_sons: number;
  /** A largura da legenda; ``null`` é a automática (18 em pé, 32 deitado). */
  caracteres_por_linha: number | null;
  /** Na montagem: a cena numa janela 16:9 com câmera, e o personagem na borda dela. */
  janela: boolean;
  /** Os cartões animados escritos pelo Gemini. */
  animacoes: boolean;
  /** As palavras proibidas, separadas por vírgula (bipe na voz, asteriscos na legenda). */
  bipe: string;
  voz: Voz;
  estilo_da_legenda: EstiloDaLegenda;
};

export type Voz = 'original' | 'limpa' | 'estudio';
export type EstiloDaLegenda = 'classica' | 'destaques';

/** Um ponto de partida para um tipo de vídeo (editor/presets.py). O formato não é dele:
 *  vem da plataforma. */
export type Preset = {
  nome: string;
  titulo: string;
  frase: string;
  edicao: Partial<Edicao>;
  saida: Pick<Saida, 'resolucao' | 'fps' | 'qualidade'>;
  thumb: {modelo: Modelo; cor: Cor};
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
  presets: Preset[];
  /** O nome de cada tema de sons para quem usa. */
  temas_dos_sons: Record<string, string>;
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
  /** O vídeo já vem sem fundo (WebM VP9 ou MOV com transparência). */
  tem_alfa: boolean;
};

/** Como é o vídeo: um só, com a pessoa falando; ou um fundo e, por cima, a pessoa ou um
 *  personagem animado. */
export type Modo = 'um' | 'montagem';
export type PorCima = 'pessoa' | 'personagem' | 'nada';
/** De onde vem o fundo da montagem: um vídeo, ou a biblioteca de cenas (a pasta e a matriz). */
export type FonteDoFundo = 'video' | 'cenas';
export type FormatoDoQuadro = 'fundo' | 'vertical' | 'horizontal' | 'quadrado';
/** De onde vem o áudio: o vídeo de fundo, o vídeo da pessoa ou um áudio separado. */
/** ``voz``: a voz salva da pessoa narra um roteiro (a narração vai como áudio separado). */
export type Fala = 'fundo' | 'pessoa' | 'audio' | 'voz';
export type MontagemConfig = {
  fonteDoFundo: FonteDoFundo;
  porCima: PorCima;
  /** Como tirar o fundo da pessoa: o alfa do arquivo, ou o MODNet. */
  recorte: 'transparente' | 'modnet';
  formato: FormatoDoQuadro;
  tirarFundo: boolean;
  /** A escolha de quem edita (``null``: a primeira que tem som; ver fala.ts). */
  fala: Fala | null;
};

export type PersonagemInfo = {
  id: string; nome: string; tamanho_bytes: number; largura: number; altura: number;
  quadros: number; duracao: number; tem_alfa: boolean; fundo_de_cor: boolean;
};

export type AudioInfo = {id: string; nome: string; tamanho_bytes: number; duracao: number};

// ── "Minha voz" ──

/** O motor da voz sintetizada, instalado à parte (editor/motor_de_voz.py). */
export type MotorDeVoz = {
  instalado: boolean; falso: boolean; instalando: boolean; etapa: string; fracao: number; ultima: string;
  erro: string; espaco: string; tempo: string; aparelho: string; pasta: string;
};
export type VozSalva = {nome: string; apelido: string; criada: string; segundos: number; pronuncia: Record<string, string>};
export type MedidasDaLeitura = {segundos: number; lufs: number; snr_db: number; estouro: number};
export type ParagrafoDaLeitura = {
  indice: number; texto: string; estado: 'pendente' | 'ok' | 'refazer'; motivos: string[]; cobertura: number;
  ouvido: string; faltaram: string[]; medidas: MedidasDaLeitura | null;
};
export type GravacaoDaVoz = {id: string; nome: string; pronta: boolean; paragrafos: ParagrafoDaLeitura[]};
export type Narracao = {
  id: string; rodando: boolean; feitas: number; total: number; erro: string;
  audio: (AudioInfo & {reaproveitados: number; aparelho: string}) | null;
};

/** A biblioteca de cenas depois da matriz: a ficha e a capa (a cena forte que a thumbnail usa). */
export type BibliotecaInfo = {
  id: string; nome: string; cenas: number; duracao: number; evitadas: number;
  sem_clipe: string[]; sem_descricao: string[]; capa: VideoInfo;
};

/** Uma cena da matriz, como a tabela de revisão edita: as listas em texto, com vírgulas. */
export type CenaDaMatriz = {
  id: string; arquivo: string; descricao: string; categorias: string; personagens: string;
  periodo: string; energia: string; monetizacao: string; obs: string; duracao?: number;
};

/** A matriz sendo gerada pelo Gemini, e o resultado para revisar. */
export type GeracaoDaMatriz = {
  rodando: boolean; prontas: number; total: number; pedidos: number;
  por: string; aviso: string; erro: string; cenas: Record<string, unknown>[] | null;
};

/** Quem escreveu o roteiro (as cenas e os cartões) e quanto. */
export type ResumoDoRoteiro = {por: string; aviso: string; pedidos: number; cenas: number; cartoes: number};

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
  roteiro?: ResumoDoRoteiro | Record<string, never>;
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
  /** Onde o vídeo vai ser postado (passo 1); ``tamanhos`` sai delas, um por formato. */
  plataformas: Plataforma[];
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

/** As camadas da thumbnail na montagem: o vídeo de fundo (para a fonte "Vídeo") e, no lugar
 *  da pessoa recortada, o personagem. */
export type Camadas = {
  fundo: VideoInfo | null;
  personagem: {info: PersonagemInfo; recorte: RecorteInfo | null; tirarFundo: boolean} | null;
};

export type FotoPexels = {
  id: number; largura: number; altura: number; autor: string; autor_url: string; pagina: string;
  alt: string;
};
