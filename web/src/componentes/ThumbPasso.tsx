/**
 * 5. Thumbnail: uma capa separada, desenhada pela composição do Remotion e mostrada ao
 * vivo no Player enquanto se mexe nas opções. Com uma chave do Gemini, a IA sugere três
 * ideias de acordo com o que foi dito; cada ideia é só uma ficha para os mesmos controles.
 *
 * Os controles ficam em abas — Texto, Fundo, Pessoa, Mão e Detalhes —, e a pessoa e a mão
 * também se arrastam na própria prévia.
 */
import {Player} from '@remotion/player';
import React, {useEffect, useMemo, useState} from 'react';
import {api} from '../api';
import {bytes} from '../formatar';
import {PLATAFORMAS, deTamanho, faixaSegura, juntar, recortesDe} from '../plataformas';
import {PALETA, TAMANHOS, Thumb, ThumbComposicao, type ThumbProps} from '../thumb/Thumb';
import type {Camadas, Cor, EstadoChave, Modelo, RecorteInfo, ThumbConfig, VideoInfo} from '../tipos';
import {Interruptor} from './Interruptor';
import {PainelIa} from './PainelIa';
import {AbaFundo} from './thumb/AbaFundo';
import {AbaMao} from './thumb/AbaMao';
import {AbaPessoa} from './thumb/AbaPessoa';
import {Arrastar} from './thumb/Arrastar';

const MODELOS: [Modelo, string][] = [['classico', 'Clássico'], ['numero', 'Número'],
  ['pergunta', 'Pergunta'], ['alerta', 'Alerta']];
const CORES = Object.keys(PALETA) as Cor[];
type Aba = 'texto' | 'fundo' | 'pessoa' | 'mao' | 'detalhes';
const ABAS: [Aba, string][] = [['texto', 'Texto'], ['fundo', 'Fundo'], ['pessoa', 'Pessoa'], ['mao', 'Mão'],
  ['detalhes', 'Detalhes']];

export const FONTES = {titulo: '/fontes/Anton-Regular.ttf', texto: '/fontes/DejaVuSans-Bold.ttf'};

/** O recorte de um instante: ``undefined`` ainda não pedido, ``null`` carregando ou sem jeito. */
export type Recortes = Record<string, RecorteInfo | null>;
export const chaveDoRecorte = (t: number) => t.toFixed(2);

/** O rosto e o alvo que a IA viu só valem no quadro em que ela viu. */
export const daIa = (config: ThumbConfig) => config.rostoT !== null && Math.abs(config.rostoT - config.t) < 0.05;

export function propsDaThumb(config: ThumbConfig, video: VideoInfo, tamanho: string,
                             icones: Record<string, string[]>, recorte: RecorteInfo | null,
                             camadas: Camadas | null = null): ThumbProps {
  const {largura, altura} = TAMANHOS[tamanho];
  // Na montagem com personagem, ele é a pessoa recortada: um desenho com transparência.
  const personagem = camadas?.personagem ?? null;
  const usarRecorte = personagem ? Boolean(personagem.recorte?.ok) : Boolean(config.recorte && recorte?.ok);
  const vistoPelaIa = daIa(config);
  const aspecto = personagem ? personagem.info.largura / personagem.info.altura : video.largura / video.altura;
  const quadro = api.quadroUrl(video.id, config.t, 1920);
  // O fundo: o próprio quadro, outro quadro do vídeo, a imagem escolhida ou a cor.
  let fundo = config.fundo;
  let fundoImagem = '';
  let fundoAspecto = aspecto;
  let doProprio = false;
  if (fundo === 'video' && (personagem || camadas?.fundo)) {
    // Na montagem, o "Vídeo" é sempre o vídeo de fundo: no mesmo momento da pessoa, ou
    // no escolhido.
    const fonte = camadas?.fundo ?? video;
    const t = config.fundoT ?? Math.min(config.t, Math.max(0, fonte.duracao - 0.1));
    fundoImagem = api.quadroUrl(fonte.id, t, 1920);
    fundoAspecto = fonte.largura / fonte.altura;
  } else if (fundo === 'video') {
    doProprio = config.fundoT === null || Math.abs(config.fundoT - config.t) < 0.05;
    fundoImagem = doProprio ? quadro : api.quadroUrl(video.id, config.fundoT ?? config.t, 1920);
  } else if (fundo === 'imagem' && config.imagem) {
    fundoImagem = api.imagemUrl(config.imagem);
    fundoAspecto = config.imagem.largura / config.imagem.altura;
  } else if (fundo === 'imagem') {
    fundo = 'cor';
  }
  return {
    largura, altura, quadro, aspecto,
    recorte: !usarRecorte ? '' : personagem ? api.personagemQuadroUrl(personagem.info.id, personagem.tirarFundo)
      : api.recorteUrl(video.id, config.t, Math.min(video.largura, 1440)),
    pessoa: !usarRecorte ? null : (personagem ? personagem.recorte?.pessoa : recorte?.pessoa) ?? null,
    // Com a pessoa recortada, o rosto vem da silhueta medida no próprio quadro. A caixa do
    // Gemini fica para o quadro inteiro: num teste real, ela veio com a pessoa toda dentro
    // em vez do rosto, e a pessoa encolheu até virar um bonequinho no canto.
    rosto: personagem ? personagem.recorte?.rosto ?? null
      : usarRecorte ? recorte?.rosto ?? null : (vistoPelaIa ? config.rosto : null) ?? recorte?.rosto ?? null,
    fundo, fundoImagem, fundoAspecto, fundoDoProprioQuadro: doProprio,
    foco: fundo === 'video' && !doProprio ? config.foco : null,
    desfoque: config.desfoque, escurecer: config.escurecer, vinheta: config.vinheta, tom: config.tom,
    lado: config.lado, pessoaDx: config.pessoaDx, pessoaDy: config.pessoaDy, pessoaEscala: config.pessoaEscala,
    espelhar: config.espelhar, contorno: config.contorno, luz: config.luz, realce: config.realce,
    mao: config.mao !== 'nenhuma' ? api.maoUrl(config.maoEstilo, config.maoTom) : '',
    maoAlvo: config.mao === 'alvo' && vistoPelaIa && config.alvo ? 'alvo' : 'titulo',
    maoX: config.maoX, maoY: config.maoY, maoEscala: config.maoEscala,
    texto: config.texto || 'Escreva a chamada',
    destaque: config.destaque,
    modelo: config.modelo,
    cor: config.cor,
    selo: config.selo,
    numero: config.numero,
    icone: config.icone ? (icones[config.icone] ?? []) : [],
    iconeAlerta: icones.alerta ?? [],
    seta: config.seta && vistoPelaIa && Boolean(config.alvo),
    alvo: vistoPelaIa ? config.alvo : null,
    fonteTitulo: FONTES.titulo,
    fonteTexto: FONTES.texto,
    seguro: faixaSegura(config.plataformas, tamanho),
  };
}

/** "Shorts, TikTok e Reels": as plataformas marcadas que pedem este tamanho. */
const paraQuem = (config: ThumbConfig, tamanho: string) =>
  juntar(deTamanho(config.plataformas, tamanho).map((p) => PLATAFORMAS[p].curto));

type Props = {
  video: VideoInfo | null;
  config: ThumbConfig;
  mudar: (p: Partial<ThumbConfig>) => void;
  icones: Record<string, string[]>;
  fonteOk: boolean;
  recorte: RecorteInfo | null | undefined;
  /** Na montagem: o vídeo de fundo e o personagem (``null`` no vídeo único). */
  camadas: Camadas | null;
  tamanhoDoRecorte: string;
  painelIa: React.ComponentProps<typeof PainelIa> | null;
  pexels: EstadoChave;
  setPexels: (e: EstadoChave) => void;
  geracao: {restantes: number; teto: number};
  setGeracao: (g: {restantes: number; teto: number}) => void;
  /** O botão "Baixar": desenha, salva na pasta e baixa o JPG deste tamanho. */
  aoBaixar: (tamanho: string) => void;
  baixando: string | null;
  baixadas: Record<string, {png: string; jpg: string; jpgBytes: number}>;
  erro: string;
};

export const ThumbPasso: React.FC<Props> = (p) => {
  const {video, config, mudar, icones, fonteOk, recorte} = p;
  const [aba, setAba] = useState<Aba>('texto');
  const [busca, setBusca] = useState('');
  const [tamanhoDaPrevia, setTamanhoDaPrevia] = useState('1280x720');
  const palavras = config.texto.trim().split(/\s+/).filter(Boolean);
  const nomes = useMemo(() => Object.keys(icones).filter((n) => n.includes(busca.toLowerCase())),
    [icones, busca]);
  const previa = config.tamanhos.includes(tamanhoDaPrevia) ? tamanhoDaPrevia : (config.tamanhos[0] ?? '1280x720');
  const {camadas} = p;
  const props = useMemo(() => (video && fonteOk
    ? propsDaThumb(config, video, previa, icones, recorte ?? null, camadas) : null),
  [video, fonteOk, config, previa, icones, recorte, camadas]);
  const temAlvo = daIa(config) && Boolean(config.alvo);

  const [verRecortes, setVerRecortes] = useState(true);
  const recortes = recortesDe(config.plataformas, previa);
  // No perfil do TikTok e do Instagram, a capa em pé aparece cortada em 3:4.
  const doPerfil = recortes.find((r) => Math.abs(r.y1 - r.y0 - 0.75) < 0.01) ?? null;

  useEffect(() => {
    if (!config.tamanhos.includes(tamanhoDaPrevia) && config.tamanhos[0]) setTamanhoDaPrevia(config.tamanhos[0]);
  }, [config.tamanhos, tamanhoDaPrevia]);

  const irParaAsPlataformas = () => {
    const calmo = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    document.getElementById('plataformas')?.scrollIntoView({behavior: calmo ? 'auto' : 'smooth', block: 'center'});
  };

  const situacaoDoRecorte = camadas?.personagem ? ''
    : !config.recorte || !video ? ''
      : recorte === undefined || recorte === null ? `Recortando… (na primeira vez o editor baixa o modelo, ${p.tamanhoDoRecorte})`
        : recorte.ok ? '' : 'Não achei uma pessoa neste quadro: a thumbnail usa o quadro inteiro.';

  return (
    <section className="passo" id="passo-thumb">
      <header>
        <span className="numero" aria-hidden="true">5</span>
        <div>
          <h2>Thumbnail</h2>
          <p>Uma capa à parte, no formato de cada plataforma. A prévia muda enquanto você escolhe.</p>
        </div>
      </header>
      <p className="para-onde">
        Para {juntar(config.tamanhos.map((t) => paraQuem(config, t)))}.{' '}
        <button type="button" className="link" onClick={irParaAsPlataformas}>Trocar as plataformas</button>
      </p>
      <Interruptor ligado={config.ativo} aoMudar={(v) => mudar({ativo: v})} titulo="Gerar thumbnail"
        descricao="Sai sozinha quando a edição termina, em PNG e em JPG de até 2 MB, na mesma pasta do vídeo." />
      <div className={config.ativo ? '' : 'desligado'} aria-disabled={!config.ativo}>
        {p.painelIa ? <PainelIa {...p.painelIa} /> : null}
        <div className="thumb-area">
          <div>
            {props ? (
              <div className="previa-thumb">
                <Player component={ThumbComposicao} inputProps={props}
                  durationInFrames={1} fps={30}
                  compositionWidth={TAMANHOS[previa].largura} compositionHeight={TAMANHOS[previa].altura}
                  style={{width: '100%', aspectRatio: `${TAMANHOS[previa].largura} / ${TAMANHOS[previa].altura}`,
                    maxHeight: 520}}
                  acknowledgeRemotionLicense />
                <Arrastar props={props} config={config} mudar={mudar} />
                {verRecortes ? (
                  <div className="recortes" aria-hidden="true"
                    style={{aspectRatio: `${TAMANHOS[previa].largura} / ${TAMANHOS[previa].altura}`}}>
                    {recortes.map((r) => (
                      <div key={r.nome} className="recorte" style={{top: `${r.y0 * 100}%`, height: `${(r.y1 - r.y0) * 100}%`}}>
                        <span>{r.nome}</span>
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : (
              <div className="vazio">Envie um vídeo para ver a prévia da thumbnail.</div>
            )}
            {config.tamanhos.length > 1 ? (
              <div className="linha-de-opcoes" style={{marginTop: 8}} role="group" aria-label="prévia de">
                <small style={{alignSelf: 'center'}}>Prévia de:</small>
                {config.tamanhos.map((t) => (
                  <button key={t} type="button" className="pilula" aria-pressed={previa === t}
                    onClick={() => setTamanhoDaPrevia(t)}>{paraQuem(config, t)}</button>
                ))}
              </div>
            ) : null}
            {recortes.length && props ? (
              <label className="ver-recortes">
                <input type="checkbox" checked={verRecortes} onChange={(e) => setVerRecortes(e.target.checked)} />
                Mostrar onde a plataforma corta a capa (as linhas não saem na imagem)
              </label>
            ) : null}
            {props ? (
              <div className="no-feed">
                {doPerfil ? (
                  <div className="miniatura-feed" style={{aspectRatio: '3 / 4'}}>
                    <div style={{transform: `translateY(-${doPerfil.y0 * 100}%)`}}>
                      <Thumb {...props} />
                    </div>
                  </div>
                ) : (
                  <div className="miniatura-feed" style={{aspectRatio: `${props.largura} / ${props.altura}`}}>
                    <Thumb {...props} />
                  </div>
                )}
                <small>{doPerfil
                  ? 'Assim ela aparece no perfil, cortada em 3:4: a chamada e o rosto precisam caber aqui.'
                  : 'Assim ela aparece no feed, com 120 px de largura: a chamada precisa ler daqui.'}</small>
              </div>
            ) : null}
            {props ? (
              <div className="baixar-thumb">
                {config.tamanhos.map((t) => {
                  const feita = p.baixadas[t];
                  return (
                    <div key={t} className="baixar-um">
                      <button type="button" className="botao" disabled={p.baixando !== null}
                        onClick={() => p.aoBaixar(t)}>
                        {p.baixando === t ? 'Preparando…' : `Baixar para ${paraQuem(config, t)} (${t.replace('x', '×')})`}
                      </button>
                      {feita ? (
                        <small>
                          Baixada: <a href={api.thumbnailUrl(feita.jpg)}>{feita.jpg}</a> ({bytes(feita.jpgBytes)}) ·{' '}
                          <a href={api.thumbnailUrl(feita.png)}>PNG</a> ·{' '}
                          <button type="button" className="link" onClick={() => api.abrirPasta()}>Abrir a pasta</button>
                        </small>
                      ) : null}
                    </div>
                  );
                })}
                {p.erro ? <div className="aviso erro">{p.erro}</div> : null}
              </div>
            ) : null}
          </div>
          <div>
            <div className="abas" role="tablist" aria-label="opções da thumbnail">
              {ABAS.map(([a, nome]) => (
                <button key={a} type="button" role="tab" aria-selected={aba === a} id={`aba-${a}`}
                  onClick={() => setAba(a)}>{nome}</button>
              ))}
            </div>
            <div role="tabpanel" aria-labelledby={`aba-${aba}`}>
              {aba === 'texto' ? (
                <div className="aba">
                  <label className="campo">
                    <span>Chamada</span>
                    <input type="text" value={config.texto} maxLength={60}
                      placeholder="Vem do que você falou, depois de editar"
                      onChange={(e) => mudar({texto: e.target.value, destaque: -1})} />
                    <small>De 2 a 5 palavras leem melhor. Toque numa para ela virar o adesivo:</small>
                    {palavras.length ? (
                      <div className="palavras">
                        {palavras.map((w, i) => (
                          <button key={`${i}-${w}`} type="button" aria-pressed={config.destaque === i}
                            onClick={() => mudar({destaque: config.destaque === i ? -1 : i})}>{w}</button>
                        ))}
                      </div>
                    ) : null}
                  </label>
                  <div className="campo">
                    <span>Modelo</span>
                    <div className="linha-de-opcoes" role="group" aria-label="modelo">
                      {MODELOS.map(([m, nome]) => (
                        <button key={m} type="button" className="pilula" aria-pressed={config.modelo === m}
                          onClick={() => mudar({modelo: m})}>{nome}</button>
                      ))}
                    </div>
                  </div>
                  {config.modelo === 'numero' ? (
                    <label className="campo">
                      <span>O número</span>
                      <input type="text" value={config.numero} maxLength={6} placeholder="3, R$10, 90%…"
                        onChange={(e) => mudar({numero: e.target.value})} />
                    </label>
                  ) : null}
                  <label className="campo">
                    <span>{config.modelo === 'alerta' ? 'Texto da faixa' : 'Selo (opcional)'}</span>
                    <input type="text" value={config.selo} maxLength={12}
                      placeholder={config.modelo === 'alerta' ? 'ATENÇÃO, CUIDADO…' : 'NOVO, TESTEI, GRÁTIS…'}
                      onChange={(e) => mudar({selo: e.target.value})} />
                  </label>
                </div>
              ) : null}
              {aba === 'fundo' ? (
                <AbaFundo config={config} mudar={mudar} video={camadas?.fundo ?? video}
                  montagem={camadas !== null} pexels={p.pexels} setPexels={p.setPexels}
                  geracao={p.geracao} setGeracao={p.setGeracao}
                  iaConfigurada={Boolean(p.painelIa?.ia.configurada)} />
              ) : null}
              {aba === 'pessoa' ? (
                <AbaPessoa config={config} mudar={mudar} video={video} situacaoDoRecorte={situacaoDoRecorte}
                  temAlvo={temAlvo} personagem={Boolean(camadas?.personagem)} />
              ) : null}
              {aba === 'mao' ? <AbaMao config={config} mudar={mudar} temAlvo={temAlvo} /> : null}
              {aba === 'detalhes' ? (
                <div className="aba">
                  <div className="campo">
                    <span>Cor de destaque</span>
                    <div className="cores" role="group" aria-label="cor de destaque">
                      {CORES.map((c) => (
                        <button key={c} type="button" aria-pressed={config.cor === c} aria-label={c} title={c}
                          style={{background: PALETA[c]}} onClick={() => mudar({cor: c})} />
                      ))}
                    </div>
                  </div>
                  <div className="campo">
                    <span>Ícone {config.icone ? `· ${config.icone}` : '(opcional)'}</span>
                    <input type="text" placeholder="buscar: dinheiro, celular, foguete…" value={busca}
                      onChange={(e) => setBusca(e.target.value)} />
                    <div className="icones-lista">
                      <button type="button" aria-pressed={!config.icone} title="sem ícone"
                        onClick={() => mudar({icone: ''})}>—</button>
                      {nomes.map((n) => (
                        <button key={n} type="button" aria-pressed={config.icone === n} title={n}
                          onClick={() => mudar({icone: n})}>
                          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                            strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                            {icones[n].map((d, i) => <path key={i} d={d} />)}
                          </svg>
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              ) : null}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
};
