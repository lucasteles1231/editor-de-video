/**
 * A conversa com o servidor local. Toda chamada leva o token da sessão, que chega na
 * URL aberta pelo comando `editar` e fica guardado na aba (sessionStorage).
 */
import type {Edicao, Estado, Saida, Tarefa, VideoInfo} from './tipos';

const CHAVE = 'editor-token';
const daUrl = new URLSearchParams(location.search).get('t');
if (daUrl) {
  sessionStorage.setItem(CHAVE, daUrl);
  // Tira o token da barra de endereço: ele não precisa ficar à vista.
  history.replaceState(null, '', location.pathname);
}
export const token = sessionStorage.getItem(CHAVE) ?? '';

/** Para o que o navegador busca sozinho (player, imagens): o token vai na URL. */
export const comToken = (url: string) =>
  `${url}${url.includes('?') ? '&' : '?'}t=${encodeURIComponent(token)}`;

async function erroDe(r: Response): Promise<Error> {
  const corpo = await r.json().catch(() => ({}));
  return new Error(corpo.detail ?? corpo.erro ?? `erro ${r.status}`);
}

async function pedir<T>(caminho: string, init: RequestInit = {}): Promise<T> {
  const r = await fetch(caminho, {
    ...init,
    headers: {...(init.headers ?? {}), 'X-Editor-Token': token},
  });
  if (!r.ok) throw await erroDe(r);
  return r.json() as Promise<T>;
}

export const api = {
  estado: () => pedir<Estado>('/api/estado'),

  /** Envia o vídeo com progresso (o fetch não informa progresso de envio). */
  enviar: (arquivo: File, aoProgresso: (fracao: number) => void) =>
    new Promise<VideoInfo>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', '/api/videos');
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
        if (xhr.status >= 200 && xhr.status < 300) resolve(corpo as VideoInfo);
        else reject(new Error(corpo.detail ?? corpo.erro ?? `erro ${xhr.status}`));
      };
      xhr.onerror = () => reject(new Error('o envio falhou — o editor ainda está aberto?'));
      const dados = new FormData();
      dados.append('arquivo', arquivo);
      xhr.send(dados);
    }),

  criarTarefa: (videoId: string, edicao: Edicao, saida: Saida, previaS: number | null) =>
    pedir<Tarefa>('/api/tarefas', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({video_id: videoId, edicao, saida, previa_s: previaS}),
    }),

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
  abrirPasta: () => pedir('/api/abrir-pasta', {method: 'POST'}),
};
