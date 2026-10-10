/**
 * "Minha voz": a pessoa lê um texto uma vez (pelo microfone, num teleprompter que mostra um
 * parágrafo de cada vez, ou enviando a gravação inteira), e o editor narra qualquer roteiro com a
 * voz dela. O motor (o Qwen3-TTS) é instalado à parte, pelo botão daqui.
 *
 * A narração pronta vira um áudio separado: dali em diante, a montagem é a de sempre.
 */
import React, {useEffect, useRef, useState} from 'react';
import {api} from '../api';
import {duracao, numero} from '../formatar';
import type {AudioInfo, GravacaoDaVoz, MotorDeVoz, Narracao, ParagrafoDaLeitura, VozSalva} from '../tipos';

/** De quanto em quanto tempo a página pergunta pela instalação e pela narração. */
const ESPERA_MS = 800;
/** Palavras por segundo de uma narração de vídeo, para a estimativa. */
const PALAVRAS_POR_SEGUNDO = 2.6;

/** O formato que o navegador grava: Opus em WebM (Chrome, Firefox) ou AAC em MP4 (Safari). */
function formatoDeGravacao(): {mime: string; extensao: string} {
  const opcoes: [string, string][] = [['audio/webm;codecs=opus', '.webm'], ['audio/webm', '.webm'],
    ['audio/mp4', '.m4a'], ['audio/ogg;codecs=opus', '.ogg']];
  for (const [mime, extensao] of opcoes) {
    if (typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(mime)) return {mime, extensao};
  }
  return {mime: '', extensao: '.webm'};
}

const comoTexto = (lista: Record<string, string>) => Object.entries(lista).map(([a, b]) => `${a} = ${b}`).join('\n');
const mensagem = (e: unknown) => (e as Error).message;

const NOME_DO_ESTADO = {pendente: 'falta gravar', ok: 'aprovado', refazer: 'regravar'};

// ── a instalação ──────────────────────────────────────────────────────────

const InstalarMotor: React.FC<{motor: MotorDeVoz; aoMudar: (m: MotorDeVoz) => void}> = ({motor, aoMudar}) => {
  const [erro, setErro] = useState('');
  useEffect(() => {
    if (!motor.instalando) return undefined;
    const t = setInterval(() => api.motorDeVoz().then(aoMudar).catch(() => undefined), ESPERA_MS);
    return () => clearInterval(t);
  }, [motor.instalando, aoMudar]);
  const instalar = () => {
    setErro('');
    api.instalarVoz().then(aoMudar).catch((e) => setErro(mensagem(e)));
  };
  return (
    <div className="minha-voz" aria-label="instalar a voz sintetizada">
      <strong>Primeiro, instale a voz sintetizada</strong>
      <small>
        Ela não vem com o editor: o motor (o Qwen3-TTS, de código aberto) fica num ambiente à parte,
        com {motor.espaco}. Leva {motor.tempo}, uma vez só. Tudo roda no seu computador, e desinstalar apaga a pasta
        inteira. Funciona melhor num Mac com chip Apple ou com uma placa NVIDIA.
      </small>
      {motor.instalando ? (
        <>
          <div className="barra" role="progressbar" aria-valuenow={Math.round(motor.fracao * 100)}
            aria-valuemin={0} aria-valuemax={100}><div style={{width: `${Math.max(3, motor.fracao * 100)}%`}} /></div>
          <small className="andamento" aria-live="polite">{motor.etapa || 'Começando…'}</small>
          {motor.ultima ? <small className="ultima-linha">{motor.ultima}</small> : null}
          <div className="linha-de-opcoes">
            <button type="button" className="botao pequeno" onClick={() => api.cancelarInstalacao().then(aoMudar)}>
              Cancelar
            </button>
          </div>
        </>
      ) : (
        <div className="linha-de-opcoes">
          <button type="button" className="botao pequeno usar" onClick={instalar}>Instalar a voz sintetizada</button>
        </div>
      )}
      {motor.erro || erro ? <div className="aviso erro">{motor.erro || erro}</div> : null}
    </div>
  );
};

// ── a gravação da leitura ─────────────────────────────────────────────────

const Resultado: React.FC<{p: ParagrafoDaLeitura; url: string}> = ({p, url}) => (
  <div className={`resultado-da-leitura ${p.estado}`} role="status" aria-label={`resultado do parágrafo ${p.indice + 1}`}>
    <strong>{p.estado === 'ok' ? `Parágrafo ${p.indice + 1} aprovado` : `Regrave o parágrafo ${p.indice + 1}`}</strong>
    {p.motivos.map((m) => <small key={m}>{m}</small>)}
    {p.estado === 'refazer' && p.faltaram.length ? <small>Não ouvi: {p.faltaram.slice(0, 8).join(', ')}.</small> : null}
    {p.medidas && p.medidas.segundos > 0 ? (
      <small className="medidas">
        {duracao(p.medidas.segundos)} · volume {numero(p.medidas.lufs, 1)} LUFS · fala {numero(p.medidas.snr_db)} dB acima
        do ruído · {numero(p.cobertura * 100)}% das palavras
      </small>
    ) : null}
    {p.medidas && p.medidas.segundos > 0 ? <audio controls preload="none" src={url} aria-label="ouvir a gravação" /> : null}
  </div>
);

const GravarVoz: React.FC<{aoSalvar: (v: VozSalva) => void; aoFechar: () => void; podeFechar: boolean}> = (p) => {
  const [nome, setNome] = useState('');
  const [g, setG] = useState<GravacaoDaVoz | null>(null);
  const [atual, setAtual] = useState(0);
  const [meio, setMeio] = useState<'microfone' | 'arquivo'>('microfone');
  const [gravando, setGravando] = useState(false);
  const [conferindo, setConferindo] = useState('');
  const [erro, setErro] = useState('');
  const [versoes, setVersoes] = useState<Record<number, number>>({});
  const [salvando, setSalvando] = useState(false);
  const microfone = useRef<MediaStream | null>(null);
  const gravador = useRef<MediaRecorder | null>(null);
  const medidor = useRef<{ctx: AudioContext; quadro: number} | null>(null);
  const nivel = useRef<HTMLDivElement>(null);

  const soltarMicrofone = () => {
    if (medidor.current) {
      cancelAnimationFrame(medidor.current.quadro);
      void medidor.current.ctx.close();
      medidor.current = null;
    }
    microfone.current?.getTracks().forEach((t) => t.stop());
    microfone.current = null;
  };
  useEffect(() => soltarMicrofone, []);

  const comecar = async () => {
    setErro('');
    try {
      setG(await api.novaGravacao(nome));
      setAtual(0);
    } catch (e) {
      setErro(mensagem(e));
    }
  };

  /** A gravação com a nota nova: aprovado, vai para o próximo que falta. */
  const atualizar = (nova: GravacaoDaVoz, indice: number | null) => {
    setG(nova);
    if (indice === null) {
      setVersoes((v) => Object.fromEntries(nova.paragrafos.map((x) => [x.indice, (v[x.indice] ?? 0) + 1])));
      const primeiro = nova.paragrafos.findIndex((x) => x.estado !== 'ok');
      setAtual(primeiro >= 0 ? primeiro : 0);
      return;
    }
    setVersoes((v) => ({...v, [indice]: (v[indice] ?? 0) + 1}));
    if (nova.paragrafos[indice].estado === 'ok') {
      const depois = nova.paragrafos.findIndex((x) => x.indice > indice && x.estado !== 'ok');
      const qualquer = nova.paragrafos.findIndex((x) => x.estado !== 'ok');
      setAtual(depois >= 0 ? depois : qualquer >= 0 ? qualquer : indice);
    }
  };

  const abrirMicrofone = async (): Promise<MediaStream> => {
    if (microfone.current) return microfone.current;
    // Sem os "melhoramentos" do navegador: o redutor de ruído deixa a voz metálica, e o
    // modelo copiaria o metal.
    const s = await navigator.mediaDevices.getUserMedia({
      audio: {echoCancellation: false, noiseSuppression: false, autoGainControl: false, channelCount: 1},
    });
    microfone.current = s;
    const ctx = new AudioContext();
    const analisador = ctx.createAnalyser();
    analisador.fftSize = 1024;
    ctx.createMediaStreamSource(s).connect(analisador);
    const amostras = new Float32Array(analisador.fftSize);
    const passo = () => {
      analisador.getFloatTimeDomainData(amostras);
      let soma = 0;
      for (const v of amostras) soma += v * v;
      const db = 20 * Math.log10(Math.sqrt(soma / amostras.length) + 1e-9);
      if (nivel.current) nivel.current.style.width = `${Math.min(100, Math.max(0, (db + 60) * 1.8))}%`;
      if (medidor.current) medidor.current.quadro = requestAnimationFrame(passo);
    };
    medidor.current = {ctx, quadro: requestAnimationFrame(passo)};
    return s;
  };

  const enviarGravacao = async (gid: string, indice: number, audio: Blob, extensao: string) => {
    setConferindo(`Conferindo o parágrafo ${indice + 1}… (o Whisper ouve a gravação)`);
    try {
      atualizar(await api.gravarParagrafo(gid, indice, audio, `paragrafo-${indice + 1}${extensao}`), indice);
    } catch (e) {
      setErro(mensagem(e));
    } finally {
      setConferindo('');
    }
  };

  const gravar = async () => {
    if (!g) return;
    setErro('');
    const indice = atual;
    try {
      const s = await abrirMicrofone();
      const {mime, extensao} = formatoDeGravacao();
      const r = new MediaRecorder(s, mime ? {mimeType: mime} : undefined);
      const partes: Blob[] = [];
      r.ondataavailable = (e) => {
        if (e.data.size) partes.push(e.data);
      };
      r.onstop = () => void enviarGravacao(g.id, indice, new Blob(partes, {type: r.mimeType || mime}), extensao);
      r.start();
      gravador.current = r;
      setGravando(true);
    } catch (e) {
      setErro(`Não deu para usar o microfone (${mensagem(e)}). Permita o microfone para esta página, no ícone da `
        + 'barra de endereço, ou grave fora e envie o arquivo.');
    }
  };

  const parar = () => {
    gravador.current?.stop();
    gravador.current = null;
    setGravando(false);
  };

  const enviarLeitura = async (arquivo: File) => {
    if (!g) return;
    setErro('');
    setConferindo('Conferindo a leitura inteira… (o Whisper ouve tudo: uns 20 a 40 s)');
    try {
      atualizar(await api.enviarLeitura(g.id, arquivo, () => undefined), null);
    } catch (e) {
      setErro(mensagem(e));
    } finally {
      setConferindo('');
    }
  };

  const salvar = async () => {
    if (!g) return;
    setSalvando(true);
    setErro('');
    try {
      soltarMicrofone();
      p.aoSalvar(await api.salvarVoz(g.id));
    } catch (e) {
      setErro(mensagem(e));
    } finally {
      setSalvando(false);
    }
  };

  if (!g) {
    return (
      <div className="minha-voz" aria-label="gravar a sua voz">
        <strong>Grave a sua voz</strong>
        <small>
          Você lê um texto de uns 2 minutos, um parágrafo de cada vez, num lugar silencioso. O primeiro parágrafo é a
          autorização, com o seu nome. Use só a sua própria voz: clonar a voz de outra pessoa sem a permissão dela é
          ilegal.
        </small>
        <label className="campo">
          <span>Seu nome (vai na autorização)</span>
          <input type="text" value={nome} maxLength={40} autoComplete="name"
            onChange={(e) => setNome(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && nome.trim() && void comecar()} />
        </label>
        <div className="linha-de-opcoes">
          <button type="button" className="botao pequeno usar" disabled={!nome.trim()} onClick={() => void comecar()}>
            Começar a leitura
          </button>
          {p.podeFechar ? <button type="button" className="botao pequeno" onClick={p.aoFechar}>Voltar</button> : null}
        </div>
        {erro ? <div className="aviso erro">{erro}</div> : null}
      </div>
    );
  }

  const paragrafo = g.paragrafos[atual];
  const aprovados = g.paragrafos.filter((x) => x.estado === 'ok').length;
  return (
    <div className="minha-voz" aria-label="gravar a sua voz">
      <strong>A leitura de {g.nome}</strong>
      <div className="linha-de-opcoes" role="group" aria-label="como gravar">
        <button type="button" className="pilula" aria-pressed={meio === 'microfone'} disabled={gravando}
          onClick={() => setMeio('microfone')}>Pelo microfone</button>
        <button type="button" className="pilula" aria-pressed={meio === 'arquivo'} disabled={gravando}
          onClick={() => setMeio('arquivo')}>Enviar a gravação</button>
      </div>
      <ol className="paragrafos-da-leitura" aria-label="os parágrafos da leitura">
        {g.paragrafos.map((x) => (
          <li key={x.indice}>
            <button type="button" className={`paragrafo ${x.estado}`} aria-current={x.indice === atual}
              disabled={gravando} aria-label={`parágrafo ${x.indice + 1}: ${NOME_DO_ESTADO[x.estado]}`}
              onClick={() => setAtual(x.indice)}>{x.indice + 1}</button>
          </li>
        ))}
      </ol>
      <small>{aprovados} de {g.paragrafos.length} parágrafos aprovados.</small>
      {meio === 'microfone' ? (
        <>
          <p className="teleprompter" aria-label={`o parágrafo ${atual + 1}`}>{paragrafo.texto}</p>
          <div className="linha-de-opcoes gravar">
            {gravando ? (
              <button type="button" className="botao pequeno rosa" onClick={parar}>Parar</button>
            ) : (
              <button type="button" className="botao pequeno" disabled={Boolean(conferindo)} onClick={() => void gravar()}>
                {paragrafo.estado === 'pendente' ? `Gravar o parágrafo ${atual + 1}` : `Regravar o parágrafo ${atual + 1}`}
              </button>
            )}
            <div className={`nivel${gravando ? ' gravando' : ''}`} aria-hidden="true"><div ref={nivel} /></div>
          </div>
          <small>
            Aperte, leia o parágrafo inteiro no seu jeito normal de falar (como num vídeo) e pare quando terminar. A
            barra mostra o microfone ouvindo: ela deve mexer com a sua voz e ficar quase parada no silêncio.
          </small>
        </>
      ) : (
        <>
          <small>
            Grave o texto inteiro de uma vez (no celular, por exemplo), com uma pausa entre os parágrafos, e envie o
            arquivo. Depois dá para regravar só um parágrafo pelo microfone.
          </small>
          <div className="leitura-inteira" aria-label="o texto inteiro">
            {g.paragrafos.map((x) => <p key={x.indice}>{x.texto}</p>)}
          </div>
          <label className={`botao pequeno${conferindo ? ' desligado' : ''}`}>
            Enviar a gravação (MP3, M4A, WAV)
            <input type="file" accept="audio/*,.m4a,.mp3,.wav" hidden disabled={Boolean(conferindo)}
              aria-label="a gravação da leitura inteira"
              onChange={(e) => e.target.files?.[0] && void enviarLeitura(e.target.files[0])} />
          </label>
        </>
      )}
      {conferindo ? <small className="andamento" aria-live="polite">{conferindo}</small> : null}
      {paragrafo.estado !== 'pendente' ? (
        <Resultado p={paragrafo} url={api.paragrafoUrl(g.id, atual, versoes[atual] ?? 0)} />
      ) : null}
      {erro ? <div className="aviso erro">{erro}</div> : null}
      <div className="linha-de-opcoes">
        <button type="button" className="botao pequeno usar" disabled={!g.pronta || salvando || gravando}
          onClick={() => void salvar()}>{salvando ? 'Salvando…' : 'Salvar a minha voz'}</button>
        {p.podeFechar ? <button type="button" className="botao pequeno" onClick={p.aoFechar}>Cancelar</button> : null}
      </div>
    </div>
  );
};

// ── o roteiro narrado ─────────────────────────────────────────────────────

export const MinhaVoz: React.FC<{narracao: AudioInfo | null; aoNarrar: (a: AudioInfo | null) => void}> = (
  {narracao, aoNarrar},
) => {
  const [motor, setMotor] = useState<MotorDeVoz | null>(null);
  const [vozes, setVozes] = useState<VozSalva[]>([]);
  const [escolhida, setEscolhida] = useState('');
  const [criando, setCriando] = useState(false);
  const [roteiro, setRoteiro] = useState('');
  const [pronuncia, setPronuncia] = useState('');
  const [rodando, setRodando] = useState<Narracao | null>(null);
  const [narrado, setNarrado] = useState('');
  const [erro, setErro] = useState('');

  const escolher = (v: VozSalva) => {
    setEscolhida(v.apelido);
    setPronuncia(comoTexto(v.pronuncia));
  };

  useEffect(() => {
    api.vozes()
      .then((e) => {
        setMotor(e.motor);
        setVozes(e.vozes);
        if (e.vozes[0]) escolher(e.vozes[0]);
      })
      .catch((e) => setErro(mensagem(e)));
  }, []);

  const emAndamento = rodando?.rodando ? rodando.id : '';
  useEffect(() => {
    if (!emAndamento) return undefined;
    const t = setInterval(() => {
      api.narracao(emAndamento).then((n) => {
        setRodando(n);
        if (n.rodando) return;
        if (n.audio) aoNarrar(n.audio);
        if (n.erro) setErro(n.erro);
      }).catch(() => undefined);
    }, ESPERA_MS);
    return () => clearInterval(t);
  }, [emAndamento, aoNarrar]);

  if (!motor) return erro ? <div className="aviso erro">{erro}</div> : <small>Carregando as vozes…</small>;
  if (!motor.instalado) return <InstalarMotor motor={motor} aoMudar={setMotor} />;
  if (criando || !vozes.length) {
    return (
      <GravarVoz podeFechar={vozes.length > 0} aoFechar={() => setCriando(false)} aoSalvar={(v) => {
        setVozes((vs) => [...vs.filter((x) => x.apelido !== v.apelido), v]);
        escolher(v);
        setCriando(false);
      }} />
    );
  }

  const voz = vozes.find((v) => v.apelido === escolhida) ?? vozes[0];
  const chave = `${voz.apelido}\n${pronuncia}\n${roteiro}`;
  const palavras = roteiro.trim() ? roteiro.trim().split(/\s+/).length : 0;
  const regras = pronuncia.split('\n').filter((l) => /\S\s*(=|→|->|:)\s*\S/.test(l)).length;

  const narrar = async () => {
    setErro('');
    try {
      if (pronuncia !== comoTexto(voz.pronuncia)) {
        const nova = await api.salvarPronuncia(voz.apelido, pronuncia);
        setVozes((vs) => vs.map((x) => (x.apelido === nova.apelido ? nova : x)));
      }
      setNarrado(chave);
      setRodando(await api.narrar(voz.apelido, roteiro, pronuncia));
    } catch (e) {
      setErro(mensagem(e));
    }
  };

  const desinstalar = async () => {
    if (!window.confirm('Desinstalar a voz sintetizada? O motor e o modelo (uns 3,5 GB) saem do computador; as '
      + 'vozes gravadas ficam, para quando você instalar de novo.')) return;
    try {
      setMotor(await api.desinstalarVoz());
    } catch (e) {
      setErro(mensagem(e));
    }
  };

  const apagar = async () => {
    if (!window.confirm(`Apagar a voz de ${voz.nome}? A gravação e a referência saem do computador.`)) return;
    try {
      const r = await api.apagarVoz(voz.apelido);
      setVozes(r.vozes);
      if (r.vozes[0]) escolher(r.vozes[0]);
    } catch (e) {
      setErro(mensagem(e));
    }
  };

  return (
    <div className="minha-voz" aria-label="minha voz">
      <div className="campo">
        <span>A voz</span>
        <div className="linha-de-opcoes" role="group" aria-label="as vozes salvas">
          {vozes.map((v) => (
            <button key={v.apelido} type="button" className="pilula" aria-pressed={v.apelido === voz.apelido}
              onClick={() => escolher(v)}>{v.nome}</button>
          ))}
          <button type="button" className="pilula" onClick={() => setCriando(true)}>Gravar outra voz</button>
        </div>
        <div className="linha-de-opcoes voz-escolhida">
          <audio controls preload="none" src={api.referenciaUrl(voz.apelido)} aria-label="ouvir a referência da voz" />
          <button type="button" className="botao pequeno" onClick={() => void apagar()}>Apagar esta voz</button>
        </div>
        <small>A referência: {duracao(voz.segundos)} da sua leitura, os trechos mais limpos. Gravada em {voz.criada}.</small>
      </div>
      <label className="campo">
        <span>O roteiro</span>
        <textarea rows={7} value={roteiro} onChange={(e) => setRoteiro(e.target.value)} aria-label="o roteiro a narrar"
          placeholder="Cole aqui o texto do vídeo. Uma linha em branco separa os parágrafos." />
        <small>
          {palavras} palavras · uns {duracao(palavras / PALAVRAS_POR_SEGUNDO)} de fala.{' '}
          <label className="link">
            Abrir um .txt
            <input type="file" accept=".txt,text/plain" hidden aria-label="abrir o roteiro de um arquivo"
              onChange={(e) => e.target.files?.[0]?.text().then(setRoteiro)} />
          </label>
        </small>
      </label>
      <details className="campo pronuncia">
        <summary>Pronúncia{regras ? ` (${regras})` : ''}</summary>
        <textarea rows={3} value={pronuncia} onChange={(e) => setPronuncia(e.target.value)} aria-label="a lista de pronúncia"
          placeholder={'PEGI = pégui\nGTA = gê tê á'} />
        <small>
          Como o motor deve ler uma palavra: siglas e nomes estrangeiros. Vale só para a voz (a legenda continua com a
          grafia do roteiro) e fica salva com ela.
        </small>
      </details>
      <div className="linha-de-opcoes">
        <button type="button" className="botao pequeno usar" disabled={!roteiro.trim() || Boolean(emAndamento)}
          onClick={() => void narrar()}>{narracao ? 'Narrar de novo' : 'Narrar o roteiro'}</button>
        {emAndamento ? (
          <button type="button" className="botao pequeno" onClick={() => void api.cancelarNarracao(emAndamento)}>
            Cancelar
          </button>
        ) : null}
      </div>
      {rodando?.rodando ? (
        <>
          <div className="barra" role="progressbar" aria-valuemin={0} aria-valuemax={rodando.total}
            aria-valuenow={rodando.feitas}>
            <div style={{width: `${Math.max(3, (rodando.feitas / Math.max(1, rodando.total)) * 100)}%`}} />
          </div>
          <small className="andamento" aria-live="polite">
            {rodando.total ? `Narrando ${rodando.feitas} de ${rodando.total} trechos…` : 'Carregando o motor…'}
          </small>
        </>
      ) : null}
      {narracao ? (
        <div className="narracao-pronta">
          <audio controls src={api.audioUrl(narracao.id)} aria-label="ouvir a narração" />
          <small>
            {duracao(narracao.duracao)} de narração
            {narrado && narrado !== chave ? '. O texto mudou: narre de novo para valer.' : ', pronta para editar.'}
          </small>
        </div>
      ) : null}
      {erro ? <div className="aviso erro">{erro}</div> : null}
      <small className="custo">
        Num Mac com chip Apple, narrar leva de 1,5 a 2 vezes a duração da fala, mais uns segundos para o motor carregar
        {motor.aparelho === 'cpu' ? '; aqui ele usa o processador, que é bem mais lento' : ''}. Os trechos já narrados
        ficam guardados.{' '}
        <button type="button" className="link" onClick={() => void desinstalar()}>Desinstalar a voz sintetizada</button>
      </small>
    </div>
  );
};
