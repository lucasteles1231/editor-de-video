/**
 * A conversa com o servidor local. Toda chamada leva o token da sessão, que chega na
 * URL aberta pelo comando `editar` e fica guardado na aba (sessionStorage).
 */
import type {
  AudioInfo, BibliotecaInfo, Edicao, Estado, EstadoChave, EstadoIa, FotoPexels, GeracaoDaMatriz, GravacaoDaVoz, Ideia,
  ImagemFundo, MotorDeVoz, Narracao, PersonagemInfo, Preset, PresetsImportados, RecorteInfo, Saida, Tarefa,
  VideoInfo, VozSalva,
} from './tipos';

const CHAVE = 'editor-token';
const daUrl = new URLSearchParams(location.search).get('t');
if (daUrl) {
  sessionStorage.setItem(CHAVE, daUrl);
  // Tira o token da barra de endereço: ele não precisa ficar à vista.
  history.replaceState(null, '', location.pathname + location.hash);
}
export const token = sessionStorage.getItem(CHAVE) ?? '';

/** Para o que o navegador busca sozinho (player, imagens): o token vai na URL. */
export const comToken = (url: string) =>
  `${url}${url.includes('?') ? '&' : '?'}t=${encodeURIComponent(token)}`;

async function erroDe(r: Response): Promise<Error> {
  const corpo = await r.json().catch(() => ({}));
  return new Error(corpo.detail ?? corpo.erro ?? `erro ${r.status}`);
}

const JSON_ = {'Content-Type': 'application/json'};

async function pedir<T>(caminho: string, init: RequestInit = {}): Promise<T> {
  const r = await fetch(caminho, {
    ...init,
    headers: {...(init.headers ?? {}), 'X-Editor-Token': token},
  });
  if (!r.ok) throw await erroDe(r);
  return r.json() as Promise<T>;
}

/** Envia um arquivo com progresso (o fetch não informa progresso de envio). */
function enviarArquivo<T>(rota: string, arquivo: File, aoProgresso: (fracao: number) => void): Promise<T> {
  return new Promise<T>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', rota);
      xhr.setRequestHeader('X-Editor-Token', token);
      xhr.upload.onprogress = (e) => e.lengthComputable && aoProgresso(e.loaded / e.total);
      xhr.onload = () => {
        const corpo = (() => {
          try {
            return JSON.parse(xhr.responseText);
          } catch {
            return {};
          }
        })();
        if (xhr.status >= 200 && xhr.status < 300) resolve(corpo as T);
        else reject(new Error(corpo.detail ?? corpo.erro ?? `erro ${xhr.status}`));
      };
      xhr.onerror = () => reject(new Error('o envio falhou — o editor ainda está aberto?'));
      const dados = new FormData();
      dados.append('arquivo', arquivo);
      xhr.send(dados);
  });
}

/** O que a página pede para montar: os ids das camadas e as escolhas. O fundo é um vídeo
 *  (``fundo_id``) ou a biblioteca de cenas (``biblioteca_id``); os áudios, um ou vários, na
 *  ordem em que tocam. */
export type PedidoDeMontagem = {
  fundo_id?: string; biblioteca_id?: string; pessoa_id?: string; personagem_id?: string;
  audio_ids?: string[];
  recorte: 'transparente' | 'modnet'; formato: string; tirar_fundo_do_personagem: boolean;
  fala: 'fundo' | 'pessoa' | 'audio';
};

export const api = {
  estado: () => pedir<Estado>('/api/estado'),

  enviar: (arquivo: File, aoProgresso: (fracao: number) => void) =>
    enviarArquivo<VideoInfo>('/api/videos', arquivo, aoProgresso),
  enviarPersonagem: (arquivo: File, aoProgresso: (fracao: number) => void) =>
    enviarArquivo<PersonagemInfo>('/api/personagens', arquivo, aoProgresso),
  enviarAudio: (arquivo: File, aoProgresso: (fracao: number) => void) =>
    enviarArquivo<AudioInfo>('/api/audios', arquivo, aoProgresso),

  // ── a biblioteca de cenas: abre, recebe os clipes um a um e, por fim, a matriz ──
  novaBiblioteca: (nome: string) =>
    pedir<{id: string; nome: string}>('/api/bibliotecas', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({nome}),
    }),
  enviarClipe: (biblioteca: string, arquivo: File, aoProgresso: (fracao: number) => void) =>
    enviarArquivo<{clipes: number}>(`/api/bibliotecas/${biblioteca}/clipes`, arquivo, aoProgresso),
  enviarMatriz: (biblioteca: string, arquivo: File) =>
    enviarArquivo<BibliotecaInfo>(`/api/bibliotecas/${biblioteca}/matriz`, arquivo, () => undefined),
  /** O Gemini descreve os clipes da biblioteca (em segundo plano: acompanhe pelo andamento). */
  gerarMatriz: (biblioteca: string, assunto: string) =>
    pedir<GeracaoDaMatriz>(`/api/bibliotecas/${biblioteca}/gerar-matriz`, {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({assunto}),
    }),
  andamentoDaMatriz: (biblioteca: string) => pedir<GeracaoDaMatriz>(`/api/bibliotecas/${biblioteca}/gerar-matriz`),
  matrizAtual: (biblioteca: string) =>
    pedir<{cenas: Record<string, unknown>[]}>(`/api/bibliotecas/${biblioteca}/matriz`),
  quadroDaCenaUrl: (biblioteca: string, arquivo: string) =>
    comToken(`/api/bibliotecas/${biblioteca}/quadro?arquivo=${encodeURIComponent(arquivo)}&largura=320`),

  /** Edita um vídeo só (``videoId``) ou a montagem em camadas. */
  criarTarefa: (alvo: {videoId: string} | {montagem: PedidoDeMontagem}, edicao: Edicao, saida: Saida,
                previaS: number | null) =>
    pedir<Tarefa>('/api/tarefas', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({...('videoId' in alvo ? {video_id: alvo.videoId} : {montagem: alvo.montagem}),
        edicao, saida, previa_s: previaS}),
    }),

  personagemQuadroUrl: (id: string, tirarFundo: boolean) =>
    comToken(`/api/personagens/${id}/quadro.png?tirar_fundo=${tirarFundo ? 1 : 0}`),
  personagemArquivoUrl: (id: string) => comToken(`/api/personagens/${id}/arquivo`),
  personagemRecorte: (id: string, tirarFundo: boolean) =>
    pedir<RecorteInfo>(`/api/personagens/${id}/recorte?tirar_fundo=${tirarFundo ? 1 : 0}`),

  /** Acompanha a edição ao vivo; devolve a função que para de acompanhar. */
  acompanhar(id: string, aoMudar: (t: Tarefa) => void): () => void {
    const fonte = new EventSource(comToken(`/api/tarefas/${id}/eventos`));
    fonte.onmessage = (e) => {
      const t = JSON.parse(e.data) as Tarefa;
      aoMudar(t);
      if (t.estado !== 'rodando') fonte.close();
    };
    fonte.onerror = () => {
      // Se a conexão cair, consulta uma vez e para.
      fonte.close();
      pedir<Tarefa>(`/api/tarefas/${id}`).then(aoMudar).catch(() => undefined);
    };
    return () => fonte.close();
  },

  cancelar: (id: string) => pedir(`/api/tarefas/${id}/cancelar`, {method: 'POST'}),
  videoUrl: (videoId: string) => comToken(`/api/videos/${videoId}/arquivo`),
  /** Os sons de um tema em fila, para ouvir antes de editar. */
  somDoTemaUrl: (tema: string, volume: number) =>
    comToken(`/api/sons/${encodeURIComponent(tema)}.wav?volume=${volume.toFixed(2)}`),
  quadroUrl: (videoId: string, t: number, largura = 1280) =>
    comToken(`/api/videos/${videoId}/quadro?segundo=${t.toFixed(2)}&largura=${largura}`),
  quadroAutomatico: (videoId: string) =>
    pedir<{t: number}>(`/api/videos/${videoId}/quadro-automatico`),
  icones: () => pedir<Record<string, string[]>>('/api/icones'),
  arquivoUrl: (tarefaId: string, tipo: string, inline = false) =>
    comToken(`/api/tarefas/${tarefaId}/arquivo/${encodeURIComponent(tipo)}${inline ? '?inline=1' : ''}`),
  plano: (tarefaId: string) =>
    fetch(comToken(`/api/tarefas/${tarefaId}/arquivo/plano?inline=1`)).then((r) => r.json()),
  salvarThumbnail: (tarefaId: string, imagem: Blob, nome: string) => {
    const dados = new FormData();
    dados.append('imagem', imagem, `${nome}.png`);
    dados.append('nome', nome);
    return pedir<{png: string; jpg: string; jpg_bytes: number}>(
      `/api/tarefas/${tarefaId}/thumbnail`, {method: 'POST', body: dados});
  },
  /** O botão "Baixar" do passo 5: salva na pasta (com o nome do vídeo editado, se a edição
   *  já terminou) e devolve os nomes para baixar. */
  salvarThumbnailDoPasso: (imagem: Blob, tamanho: string, videoId: string, tarefaId: string) => {
    const dados = new FormData();
    dados.append('imagem', imagem, `${tamanho}.png`);
    dados.append('tamanho', tamanho);
    dados.append('video_id', videoId);
    if (tarefaId) dados.append('tarefa_id', tarefaId);
    return pedir<{png: string; jpg: string; jpg_bytes: number}>('/api/thumbnails', {method: 'POST', body: dados});
  },
  thumbnailUrl: (nome: string) => comToken(`/api/thumbnails/${encodeURIComponent(nome)}`),
  abrirPasta: () => pedir('/api/abrir-pasta', {method: 'POST'}),

  // A chave do Gemini vai para o servidor local e nunca volta: o estado só diz o fim dela.
  salvarChave: (chave: string) =>
    pedir<EstadoIa>('/api/ia/chave', {
      method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({chave}),
    }),
  apagarChave: () => pedir<EstadoIa>('/api/ia/chave', {method: 'DELETE'}),
  ideias: (tarefaId: string, evitar: string[], plataformas: string[]) =>
    pedir<{variantes: Ideia[]; modelo: string; segundos: number}>(`/api/tarefas/${tarefaId}/thumbs-ia`, {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({evitar, plataformas}),
    }),
  recorteInfo: (videoId: string, t: number) =>
    pedir<RecorteInfo>(`/api/videos/${videoId}/recorte?segundo=${t.toFixed(2)}`),
  recorteUrl: (videoId: string, t: number, largura = 1280) =>
    comToken(`/api/videos/${videoId}/recorte.png?segundo=${t.toFixed(2)}&largura=${largura}`),

  // ── o fundo da thumbnail ──
  enviarImagem: (arquivo: File) => {
    const dados = new FormData();
    dados.append('arquivo', arquivo);
    return pedir<ImagemFundo>('/api/imagens', {method: 'POST', body: dados});
  },
  imagemUrl: (imagem: ImagemFundo) => comToken(imagem.url),
  salvarChavePexels: (chave: string) =>
    pedir<EstadoChave>('/api/pexels/chave', {
      method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({chave}),
    }),
  apagarChavePexels: () => pedir<EstadoChave>('/api/pexels/chave', {method: 'DELETE'}),
  buscarPexels: (consulta: string, orientacao: string) =>
    pedir<{fotos: FotoPexels[]}>('/api/pexels/buscar', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({consulta, orientacao}),
    }),
  previaPexels: (id: number) => comToken(`/api/pexels/foto/${id}`),
  usarPexels: (id: number) =>
    pedir<ImagemFundo>('/api/pexels/usar', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({id}),
    }),
  gerarFundo: (cena: string, proporcao: string, lado: string) =>
    pedir<ImagemFundo & {restantes: number; nova: boolean}>('/api/fundo-gerado', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({cena, proporcao, lado}),
    }),
  maoUrl: (estilo: string, tom: string) => `/maos/mao-${estilo}-${tom}.${estilo === '3d' ? 'png' : 'svg'}`,

  // ── os presets de quem usa ──
  /** Salva o que está na tela como um preset seu (``substituir``: o mesmo nome por cima). */
  salvarPreset: (preset: Omit<Preset, 'nome' | 'meu'>, substituir: boolean) =>
    pedir<{salvo: string; presets: Preset[]}>('/api/presets', {
      method: 'POST', headers: JSON_, body: JSON.stringify({...preset, substituir}),
    }),
  apagarPreset: (nome: string) => pedir<{presets: Preset[]}>(`/api/presets/${encodeURIComponent(nome)}`,
    {method: 'DELETE'}),
  exportarPresetsUrl: () => comToken('/api/presets/exportar'),
  importarPresets: (arquivo: File) =>
    enviarArquivo<PresetsImportados>('/api/presets/importar', arquivo, () => undefined),

  // ── "Minha voz": o motor, a leitura, as vozes salvas e a narração ──
  vozes: () => pedir<{motor: MotorDeVoz; vozes: VozSalva[]}>('/api/vozes'),
  motorDeVoz: () => pedir<MotorDeVoz>('/api/vozes/motor'),
  instalarVoz: () => pedir<MotorDeVoz>('/api/vozes/motor', {method: 'POST'}),
  cancelarInstalacao: () => pedir<MotorDeVoz>('/api/vozes/motor/cancelar', {method: 'POST'}),
  desinstalarVoz: () => pedir<MotorDeVoz>('/api/vozes/motor', {method: 'DELETE'}),
  novaGravacao: (nome: string) =>
    pedir<GravacaoDaVoz>('/api/vozes/gravacoes', {method: 'POST', headers: JSON_, body: JSON.stringify({nome})}),
  /** Um parágrafo gravado pelo microfone (ou regravado): volta a gravação com a nota dele. */
  gravarParagrafo: (gravacao: string, indice: number, audio: Blob, nome: string) => {
    const dados = new FormData();
    dados.append('arquivo', audio, nome);
    return pedir<GravacaoDaVoz>(`/api/vozes/gravacoes/${gravacao}/paragrafos/${indice}`, {method: 'PUT', body: dados});
  },
  /** A leitura inteira, gravada fora da página. */
  enviarLeitura: (gravacao: string, arquivo: File, aoProgresso: (fracao: number) => void) =>
    enviarArquivo<GravacaoDaVoz>(`/api/vozes/gravacoes/${gravacao}/leitura`, arquivo, aoProgresso),
  paragrafoUrl: (gravacao: string, indice: number, versao: number) =>
    comToken(`/api/vozes/gravacoes/${gravacao}/paragrafos/${indice}.wav?v=${versao}`),
  salvarVoz: (gravacao: string) => pedir<VozSalva>(`/api/vozes/gravacoes/${gravacao}/salvar`, {method: 'POST'}),
  apagarVoz: (apelido: string) => pedir<{vozes: VozSalva[]}>(`/api/vozes/${apelido}`, {method: 'DELETE'}),
  referenciaUrl: (apelido: string) => comToken(`/api/vozes/${apelido}/referencia.wav`),
  salvarPronuncia: (apelido: string, texto: string) =>
    pedir<VozSalva>(`/api/vozes/${apelido}/pronuncia`, {method: 'PUT', headers: JSON_, body: JSON.stringify({texto})}),
  narrar: (apelido: string, roteiro: string, pronuncia: string) =>
    pedir<Narracao>(`/api/vozes/${apelido}/narrar`, {
      method: 'POST', headers: JSON_, body: JSON.stringify({roteiro, pronuncia}),
    }),
  narracao: (id: string) => pedir<Narracao>(`/api/vozes/narracoes/${id}`),
  cancelarNarracao: (id: string) => pedir(`/api/vozes/narracoes/${id}/cancelar`, {method: 'POST'}),
  audioUrl: (id: string) => comToken(`/api/audios/${id}/arquivo`),
};
