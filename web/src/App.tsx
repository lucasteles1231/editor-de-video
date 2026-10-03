import React, {useCallback, useEffect, useRef, useState} from 'react';
import {api} from './api';
import {Painel} from './componentes/Painel';
import {PassoEdicoes, PassoEnvio, PassoLegenda, PassoSaida} from './componentes/Passos';
import {ThumbPasso, propsDaThumb} from './componentes/ThumbPasso';
import {gerarPng} from './thumb/exportar';
import {carregarFonte} from './thumb/medida';
import type {Edicao, Estado, Saida, Tarefa, ThumbConfig, VideoInfo} from './tipos';
import {comecarTour, tourJaVisto} from './tour';

const THUMB_PADRAO: ThumbConfig = {
  ativo: true, texto: '', destaque: -1, t: 0, icone: '', arranjo: 'embaixo', escurecer: 0.75,
  tamanhos: ['1280x720'],
};

/** O título sugerido: a primeira frase dita, até seis palavras, com a mais longa em destaque. */
function sugestaoDeTitulo(plano: {blocos: {texto: string}[]}): {texto: string; destaque: number} {
  const palavras: string[] = [];
  for (const b of plano.blocos ?? []) {
    for (const w of b.texto.split(/\s+/)) {
      palavras.push(w);
      if (/[.?!…]$/.test(w) || palavras.length >= 6) break;
    }
    if (palavras.length >= 6 || /[.?!…]$/.test(palavras[palavras.length - 1] ?? '')) break;
  }
  const limpas = palavras.map((w) => w.replace(/[.,;:!…]+$/, ''));
  let destaque = -1;
  let maior = 3;
  limpas.forEach((w, i) => {
    if (w.length > maior) {
      maior = w.length;
      destaque = i;
    }
  });
  // O Whisper às vezes começa a frase em minúscula ("gravou um vídeo..."); no título não.
  const texto = limpas.join(' ');
  return {texto: texto.charAt(0).toLocaleUpperCase('pt-BR') + texto.slice(1), destaque};
}

export const App: React.FC = () => {
  const [estado, setEstado] = useState<Estado | null>(null);
  const [erroGeral, setErroGeral] = useState('');
  const [edicao, setEdicao] = useState<Edicao | null>(null);
  const [saida, setSaida] = useState<Saida | null>(null);
  const [video, setVideo] = useState<VideoInfo | null>(null);
  const [envio, setEnvio] = useState<number | null>(null);
  const [erroEnvio, setErroEnvio] = useState('');
  const [thumb, setThumb] = useState<ThumbConfig>(THUMB_PADRAO);
  const [icones, setIcones] = useState<Record<string, string[]>>({});
  const [fonteOk, setFonteOk] = useState(false);
  const [tarefa, setTarefa] = useState<Tarefa | null>(null);
  const [previa, setPrevia] = useState(false);
  const [erroEdicao, setErroEdicao] = useState('');
  const [thumbs, setThumbs] = useState<{nome: string; url: string; jpgBytes: number}[]>([]);
  const [gerandoThumbs, setGerandoThumbs] = useState(false);
  const pararDeAcompanhar = useRef<(() => void) | null>(null);
  const thumbAtual = useRef(thumb);
  thumbAtual.current = thumb;

  useEffect(() => {
    api.estado()
      .then((e) => {
        setEstado(e);
        setEdicao(e.padroes.edicao);
        setSaida(e.padroes.saida);
      })
      .catch((e: Error) => setErroGeral(
        `Não consegui falar com o editor (${e.message}). Abra esta página pelo comando "editar".`));
    carregarFonte().then(() => setFonteOk(true)).catch(() => setFonteOk(true));
    api.icones().then(setIcones).catch(() => undefined);
    if (!tourJaVisto()) setTimeout(comecarTour, 700);
    return () => pararDeAcompanhar.current?.();
  }, []);

  const escolherArquivo = useCallback((arquivo: File) => {
    setErroEnvio('');
    setEnvio(0);
    setTarefa(null);
    setThumbs([]);
    api.enviar(arquivo, setEnvio)
      .then((v) => {
        setVideo(v);
        setThumb((t) => ({...t, t: Math.min(v.duracao / 3, Math.max(0, v.duracao - 0.2))}));
        api.quadroAutomatico(v.id).then((r) => setThumb((t) => ({...t, t: r.t}))).catch(() => undefined);
      })
      .catch((e: Error) => setErroEnvio(e.message))
      .finally(() => setEnvio(null));
  }, []);

  const gerarThumbs = useCallback(async (tarefaId: string, v: VideoInfo, config: ThumbConfig) => {
    setGerandoThumbs(true);
    const feitas: {nome: string; url: string; jpgBytes: number}[] = [];
    try {
      for (const tamanho of config.tamanhos) {
        const blob = await gerarPng(propsDaThumb(config, v, tamanho, icones, ''));
        const r = await api.salvarThumbnail(tarefaId, blob, tamanho);
        feitas.push({nome: r.png, url: api.arquivoUrl(tarefaId, r.png, true), jpgBytes: r.jpg_bytes});
      }
      setThumbs(feitas);
    } catch (e) {
      setErroEdicao(`A thumbnail não saiu: ${(e as Error).message}`);
    } finally {
      setGerandoThumbs(false);
    }
  }, [icones]);

  const quandoTerminar = useCallback(async (t: Tarefa, v: VideoInfo) => {
    if (t.estado !== 'pronto') return;
    let config = thumbAtual.current;
    if (!config.texto) {
      try {
        const sugestao = sugestaoDeTitulo(await api.plano(t.id));
        config = {...config, ...sugestao};
        setThumb(config);
      } catch {
        /* sem plano: fica o título digitado */
      }
    }
    if (config.ativo) await gerarThumbs(t.id, v, config);
  }, [gerarThumbs]);

  const editar = useCallback(async () => {
    if (!video || !edicao || !saida) return;
    setErroEdicao('');
    setThumbs([]);
    pararDeAcompanhar.current?.();
    try {
      const t = await api.criarTarefa(video.id, edicao, saida, previa ? 15 : null);
      setTarefa(t);
      pararDeAcompanhar.current = api.acompanhar(t.id, (nova) => {
        setTarefa(nova);
        if (nova.estado !== 'rodando') void quandoTerminar(nova, video);
      });
    } catch (e) {
      setErroEdicao((e as Error).message);
    }
  }, [video, edicao, saida, previa, quandoTerminar]);

  const regerar = () => {
    if (tarefa?.estado === 'pronto' && video) void gerarThumbs(tarefa.id, video, thumb);
  };

  return (
    <>
      <header className="cabecalho">
        <div className="marca">
          <span className="adesivo">editor</span>
          <span>de vídeo</span>
        </div>
        <nav>
          <button type="button" className="botao pequeno" onClick={comecarTour}>Tour</button>
          <a className="botao pequeno" href="https://github.com/lucasteles1231/editor-de-video"
            target="_blank" rel="noreferrer">Ajuda</a>
        </nav>
      </header>

      {erroGeral ? <div className="aviso erro" style={{margin: 24}}>{erroGeral}</div> : null}

      <main className="pagina">
        <div className="coluna">
          <div className="intro">
            <h1>Seu vídeo falado, <span className="destaque-amarelo">editado</span> no estilo dos Shorts.</h1>
            <p>Legenda karaokê, cortes de silêncio, zoom, palavras que saltam, ícones, sons e thumbnail —
              tudo feito aqui no seu computador.</p>
          </div>
          <PassoEnvio video={video} progresso={envio} erro={erroEnvio} aoEscolher={escolherArquivo} />
          {estado && edicao && saida ? (
            <>
              <PassoEdicoes edicao={edicao} mudar={(p) => setEdicao({...edicao, ...p})} />
              <PassoLegenda estado={estado} edicao={edicao} saida={saida}
                mudar={(p) => setEdicao({...edicao, ...p})} mudarSaida={(p) => setSaida({...saida, ...p})} />
              <PassoSaida estado={estado} saida={saida} video={video} mudar={(p) => setSaida({...saida, ...p})} />
              <ThumbPasso video={video} config={thumb} mudar={(p) => setThumb((t) => ({...t, ...p}))}
                icones={icones} fonteOk={fonteOk} />
              {tarefa?.estado === 'pronto' && thumb.ativo ? (
                <button type="button" className="botao" onClick={regerar} disabled={gerandoThumbs}>
                  {gerandoThumbs ? 'Gerando…' : 'Gerar as thumbnails de novo'}
                </button>
              ) : null}
            </>
          ) : null}
        </div>
        <Painel video={video} tarefa={tarefa} previa={previa} setPrevia={setPrevia} aoEditar={editar}
          aoCancelar={() => tarefa && api.cancelar(tarefa.id)} erro={erroEdicao} thumbs={thumbs}
          gerandoThumbs={gerandoThumbs} pastaSaida={estado?.pasta_saida ?? ''} />
      </main>
      <footer className="rodape">
        editor-de-video {estado?.versao ?? ''} · nasceu da edição do canal Instituto Palito ·{' '}
        <a href="https://github.com/lucasteles1231/editor-de-video" target="_blank" rel="noreferrer">código no GitHub</a>
      </footer>
    </>
  );
};
