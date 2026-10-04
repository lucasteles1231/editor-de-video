import React, {useCallback, useEffect, useRef, useState} from 'react';
import {api} from './api';
import {Painel} from './componentes/Painel';
import {PassoEdicoes, PassoEnvio, PassoLegenda, PassoSaida} from './componentes/Passos';
import {ThumbPasso, chaveDoRecorte, propsDaThumb, type Recortes} from './componentes/ThumbPasso';
import {PROPORCAO} from './componentes/thumb/AbaFundo';
import {gerarPng} from './thumb/exportar';
import {carregarFonte} from './thumb/medida';
import type {Edicao, Estado, EstadoChave, EstadoIa, Ideia, Saida, Tarefa, ThumbConfig, VideoInfo} from './tipos';
import {comecarTour, tourJaVisto} from './tour';

const THUMB_PADRAO: ThumbConfig = {
  ativo: true, texto: '', destaque: -1, t: 0, icone: '', modelo: 'classico', cor: 'amarelo', selo: '',
  numero: '', fundo: 'video', fundoT: null, foco: null, imagem: null, desfoque: 0.6, escurecer: 0.75,
  vinheta: false, tom: false, recorte: true, lado: 'esquerda', pessoaDx: 0, pessoaDy: 0, pessoaEscala: 1,
  espelhar: false, contorno: true, luz: 'nenhuma', realce: true, mao: 'nenhuma', maoEstilo: '3d',
  maoTom: 'default', maoX: null, maoY: null, maoEscala: 1, seta: false, alvo: null, rosto: null,
  rostoT: null, busca: '', cena: '', tamanhos: ['1280x720'],
};

/** Uma ideia do Gemini vira a ficha dos controles: dali em diante tudo é editável. A
 *  posição volta ao automático, e o fundo de banco ou gerado espera a imagem chegar (até
 *  lá, fica a cor). */
function aplicarIdeia(config: ThumbConfig, ideia: Ideia): ThumbConfig {
  const base: ThumbConfig = {
    ...config, texto: ideia.chamada, destaque: ideia.destaque, t: ideia.t, icone: ideia.icone,
    modelo: ideia.modelo, cor: ideia.cor, selo: ideia.selo, numero: ideia.numero, recorte: ideia.recorte,
    seta: ideia.seta, alvo: ideia.alvo, rosto: ideia.rosto, rostoT: ideia.t, luz: ideia.luz, mao: ideia.mao,
    busca: ideia.busca, cena: ideia.cena, foco: ideia.foco, pessoaDx: 0, pessoaDy: 0, pessoaEscala: 1,
    espelhar: false, maoX: null, maoY: null,
  };
  if (ideia.fundo === 'video') return {...base, fundo: 'video', fundoT: ideia.t_fundo, desfoque: 0.1};
  if (ideia.fundo === 'desfocado') return {...base, fundo: 'video', fundoT: null, desfoque: 0.6};
  if ((ideia.fundo === 'banco' || ideia.fundo === 'gerado') && ideia.imagem) {
    return {...base, fundo: 'imagem', imagem: ideia.imagem, desfoque: 0.05};
  }
  return {...base, fundo: 'cor'};
}

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
  const [recortes, setRecortes] = useState<Recortes>({});
  const [ia, setIa] = useState<EstadoIa | null>(null);
  const [usarIa, setUsarIa] = useState(true);
  const [ideias, setIdeias] = useState<Ideia[]>([]);
  const [pensando, setPensando] = useState(false);
  const [erroIa, setErroIa] = useState('');
  const [escolhida, setEscolhida] = useState(-1);
  const [pexels, setPexels] = useState<EstadoChave>({configurada: false, origem: '', final: ''});
  const [geracao, setGeracao] = useState({restantes: 0, teto: 0});
  const [gerando, setGerando] = useState<number | null>(null);
  const pararDeAcompanhar = useRef<(() => void) | null>(null);
  const recortesPedidos = useRef(new Set<string>());
  const thumbAtual = useRef(thumb);
  thumbAtual.current = thumb;
  const iaAtual = useRef({ia, usarIa});
  iaAtual.current = {ia, usarIa};
  const pexelsAtual = useRef(pexels);
  pexelsAtual.current = pexels;

  /** O recorte de um instante, pedido uma vez só (o servidor também guarda). */
  const pedirRecorte = useCallback((v: VideoInfo, t: number) => {
    const chave = `${v.id}:${chaveDoRecorte(t)}`;
    if (recortesPedidos.current.has(chave)) return;
    recortesPedidos.current.add(chave);
    setRecortes((r) => ({...r, [chave]: null}));
    api.recorteInfo(v.id, t)
      .then((info) => setRecortes((r) => ({...r, [chave]: info})))
      .catch(() => setRecortes((r) => ({...r, [chave]: {ok: false, pessoa: null, rosto: null}})));
  }, []);
  const recorteDe = (v: VideoInfo | null, t: number) => (v ? recortes[`${v.id}:${chaveDoRecorte(t)}`] : undefined);

  // O recorte do quadro da prévia: espera o controle deslizante parar.
  useEffect(() => {
    if (!video || !thumb.recorte) return;
    const espera = setTimeout(() => pedirRecorte(video, thumb.t), 250);
    return () => clearTimeout(espera);
  }, [video, thumb.t, thumb.recorte, pedirRecorte]);

  // E o de cada ideia, para os cartões.
  useEffect(() => {
    if (!video) return;
    for (const ideia of ideias) if (ideia.recorte) pedirRecorte(video, ideia.t);
  }, [video, ideias, pedirRecorte]);

  useEffect(() => {
    api.estado()
      .then((e) => {
        setEstado(e);
        setEdicao(e.padroes.edicao);
        setSaida(e.padroes.saida);
        setIa(e.ia);
        setPexels(e.pexels);
        setGeracao(e.geracao);
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
    setIdeias([]);
    setErroIa('');
    setEscolhida(-1);
    api.enviar(arquivo, setEnvio)
      .then((v) => {
        setVideo(v);
        setThumb((t) => ({...t, t: Math.min(v.duracao / 3, Math.max(0, v.duracao - 0.2)), rosto: null,
          rostoT: null, alvo: null, seta: false}));
        api.quadroAutomatico(v.id).then((r) => setThumb((t) => ({...t, t: r.t}))).catch(() => undefined);
      })
      .catch((e: Error) => setErroEnvio(e.message))
      .finally(() => setEnvio(null));
  }, []);

  const gerarThumbs = useCallback(async (tarefaId: string, v: VideoInfo, config: ThumbConfig) => {
    setGerandoThumbs(true);
    const feitas: {nome: string; url: string; jpgBytes: number}[] = [];
    try {
      const recorte = config.recorte ? await api.recorteInfo(v.id, config.t).catch(() => null) : null;
      for (const tamanho of config.tamanhos) {
        const blob = await gerarPng(propsDaThumb(config, v, tamanho, icones, recorte));
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

  /** As ideias de fundo "banco" já chegam com a primeira foto do Pexels (só a busca sai
   *  do computador); uma que falhar fica com a cor, e o cartão diz o porquê. */
  const fotosDoBanco = useCallback(async (lista: Ideia[]): Promise<Ideia[]> => {
    const orientacao = PROPORCAO[thumbAtual.current.tamanhos[0]] === '9:16' ? 'retrato'
      : PROPORCAO[thumbAtual.current.tamanhos[0]] === '1:1' ? 'quadrado' : 'paisagem';
    return Promise.all(lista.map(async (ideia) => {
      if (ideia.fundo !== 'banco' || !ideia.busca) return ideia;
      try {
        const {fotos} = await api.buscarPexels(ideia.busca, orientacao);
        return fotos.length ? {...ideia, imagem: await api.usarPexels(fotos[0].id)} : ideia;
      } catch {
        return ideia;
      }
    }));
  }, []);

  const pedirIdeias = useCallback(async (tarefaId: string, evitar: string[]): Promise<Ideia[]> => {
    setPensando(true);
    setErroIa('');
    try {
      const r = await api.ideias(tarefaId, evitar);
      const variantes = pexelsAtual.current.configurada ? await fotosDoBanco(r.variantes) : r.variantes;
      setIdeias(variantes);
      setEscolhida(-1);
      return variantes;
    } catch (e) {
      setErroIa((e as Error).message);
      return [];
    } finally {
      setPensando(false);
    }
  }, [fotosDoBanco]);

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
    // Com a IA ligada, a primeira ideia vira a thumbnail; se ela falhar, fica a sugestão local.
    const {ia: estadoIa, usarIa: usar} = iaAtual.current;
    if (config.ativo && usar && estadoIa?.configurada) {
      const novas = await pedirIdeias(t.id, []);
      if (novas.length) {
        config = aplicarIdeia(config, novas[0]);
        setThumb(config);
        setEscolhida(0);
      }
    }
    if (config.ativo) await gerarThumbs(t.id, v, config);
  }, [gerarThumbs, pedirIdeias]);

  const editar = useCallback(async () => {
    if (!video || !edicao || !saida) return;
    setErroEdicao('');
    setThumbs([]);
    setIdeias([]);
    setErroIa('');
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

  const painelIa = ia ? {
    ia, usar: usarIa, setUsar: setUsarIa,
    aoSalvarChave: async (chave: string) => setIa(await api.salvarChave(chave)),
    aoApagarChave: async () => setIa(await api.apagarChave()),
    pronto: tarefa?.estado === 'pronto', pensando, erro: erroIa, ideias, escolhida,
    aoEscolher: (i: number) => {
      setThumb((t) => aplicarIdeia(t, ideias[i]));
      setEscolhida(i);
    },
    aoPedirOutras: () => {
      if (tarefa?.estado === 'pronto') void pedirIdeias(tarefa.id, ideias.map((i) => i.chamada));
    },
    propsDaIdeia: (ideia: Ideia) => {
      if (!video || !fonteOk) return null;
      const config = aplicarIdeia(thumb, ideia);
      const recorte = recorteDe(video, ideia.t);
      // Enquanto o recorte da ideia não chega, o cartão espera. Desenhar o quadro inteiro e
      // trocar pela pessoa recortada um instante depois parecia defeito.
      if (config.recorte && !recorte) return null;
      return propsDaThumb(config, video, '1280x720', icones, recorte ?? null);
    },
    gerando,
    pexelsConfigurado: pexels.configurada,
    aoGerarFundo: (i: number) => {
      const ideia = ideias[i];
      setGerando(i);
      setErroIa('');
      api.gerarFundo(ideia.cena, PROPORCAO[thumb.tamanhos[0]] ?? '16:9', thumb.lado)
        .then((imagem) => {
          setGeracao((g) => ({...g, restantes: imagem.restantes}));
          const nova = {...ideia, imagem};
          setIdeias((lista) => lista.map((x, k) => (k === i ? nova : x)));
          if (escolhida === i) setThumb((t) => aplicarIdeia(t, nova));
        })
        .catch((e: Error) => setErroIa(e.message))
        .finally(() => setGerando(null));
    },
  } : null;

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
              <PassoEdicoes edicao={edicao} mudar={(p) => setEdicao({...edicao, ...p})} video={video}
                recorte={estado.recorte} />
              <PassoLegenda estado={estado} edicao={edicao} saida={saida}
                mudar={(p) => setEdicao({...edicao, ...p})} mudarSaida={(p) => setSaida({...saida, ...p})} />
              <PassoSaida estado={estado} saida={saida} video={video} mudar={(p) => setSaida({...saida, ...p})} />
              <ThumbPasso video={video} config={thumb} mudar={(p) => setThumb((t) => ({...t, ...p}))}
                icones={icones} fonteOk={fonteOk} recorte={recorteDe(video, thumb.t)}
                tamanhoDoRecorte={estado.recorte.tamanho} painelIa={painelIa}
                pexels={pexels} setPexels={setPexels} geracao={geracao} setGeracao={setGeracao} />
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
