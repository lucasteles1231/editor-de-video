/**
 * A aba Fundo: o que vai atrás da pessoa recortada — um quadro do vídeo, uma imagem (a
 * que a pessoa envia, uma foto do Pexels ou uma gerada pelo Gemini) ou a cor — e a luz do
 * fundo: desfoque, escurecer, vinheta e um tom da cor de destaque.
 */
import React, {useState} from 'react';
import {api} from '../../api';
import {duracao} from '../../formatar';
import type {EstadoChave, FotoPexels, ImagemFundo, ThumbConfig, VideoInfo} from '../../tipos';
import {Interruptor} from '../Interruptor';

type Fonte = 'video' | 'imagem' | 'pexels' | 'gerar' | 'cor';
const FONTES: [Fonte, string][] = [['video', 'Vídeo'], ['imagem', 'Imagem'], ['pexels', 'Pexels'],
  ['gerar', 'Gerar com IA'], ['cor', 'Cor']];

export const PROPORCAO: Record<string, string> = {'1280x720': '16:9', '1080x1920': '9:16', '1080x1080': '1:1'};

type Props = {
  config: ThumbConfig;
  mudar: (p: Partial<ThumbConfig>) => void;
  /** O vídeo de onde sai a fonte "Vídeo" (na montagem, o vídeo de fundo). */
  video: VideoInfo | null;
  montagem: boolean;
  pexels: EstadoChave;
  setPexels: (e: EstadoChave) => void;
  geracao: {restantes: number; teto: number};
  setGeracao: (g: {restantes: number; teto: number}) => void;
  iaConfigurada: boolean;
};

export const AbaFundo: React.FC<Props> = ({config, mudar, video, montagem, pexels, setPexels, geracao, setGeracao,
  iaConfigurada}) => {
  const origem = config.imagem?.origem;
  const inicial: Fonte = config.fundo === 'video' ? 'video' : config.fundo === 'cor' ? 'cor'
    : origem === 'pexels' ? 'pexels' : origem === 'gerada' ? 'gerar' : 'imagem';
  const [fonte, setFonte] = useState<Fonte>(inicial);
  const [erro, setErro] = useState('');
  const [ocupado, setOcupado] = useState(false);
  const [chave, setChave] = useState('');
  const [busca, setBusca] = useState(config.busca);
  const [fotos, setFotos] = useState<FotoPexels[]>([]);
  const [cena, setCena] = useState(config.cena);

  const usarImagem = (imagem: ImagemFundo) => mudar({fundo: 'imagem', imagem, desfoque: Math.min(config.desfoque, 0.1)});
  const escolherFonte = (f: Fonte) => {
    setFonte(f);
    setErro('');
    if (f === 'video') mudar({fundo: 'video'});
    if (f === 'cor') mudar({fundo: 'cor'});
    if ((f === 'imagem' || f === 'pexels' || f === 'gerar') && config.imagem) mudar({fundo: 'imagem'});
  };
  const tentar = async (acao: () => Promise<void>) => {
    setOcupado(true);
    setErro('');
    try {
      await acao();
    } catch (e) {
      setErro((e as Error).message);
    } finally {
      setOcupado(false);
    }
  };

  const enviar = (arquivo: File | undefined) => {
    if (arquivo) void tentar(async () => usarImagem(await api.enviarImagem(arquivo)));
  };
  const proporcao = PROPORCAO[config.tamanhos[0]] ?? '16:9';
  const orientacao = proporcao === '9:16' ? 'retrato' : proporcao === '1:1' ? 'quadrado' : 'paisagem';

  return (
    <div className="aba">
      {!config.recorte ? (
        <div className="aviso">O fundo só aparece com a pessoa recortada: ligue o recorte na aba Pessoa.</div>
      ) : null}
      <div className="linha-de-opcoes" role="group" aria-label="de onde vem o fundo">
        {FONTES.map(([f, nome]) => (
          <button key={f} type="button" className="pilula" aria-pressed={fonte === f}
            onClick={() => escolherFonte(f)}>{nome}</button>
        ))}
      </div>

      {fonte === 'video' ? (
        <div className="campo">
          <Interruptor ligado={config.fundoT === null}
            titulo={montagem ? 'O mesmo momento do vídeo de fundo' : 'O mesmo quadro da pessoa'}
            descricao={montagem ? 'Desligado, escolha outro momento do vídeo de fundo.'
              : 'Desligado, o fundo vem de outro momento do vídeo (uma tela, um produto, uma cena).'}
            aoMudar={(v) => mudar({fundoT: v ? null : Math.min(config.t, Math.max(0, (video?.duracao ?? 1) - 0.1)),
              foco: null})} />
          {config.fundoT !== null && video ? (
            <label className="campo">
              <span>Quadro do fundo: {duracao(config.fundoT)}</span>
              <input type="range" min={0} max={Math.max(0.1, video.duracao - 0.1)} step={0.1} value={config.fundoT}
                onChange={(e) => mudar({fundoT: Number(e.target.value), foco: null})} />
            </label>
          ) : null}
        </div>
      ) : null}

      {fonte === 'imagem' ? (
        <label className="soltar-imagem" onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            enviar(e.dataTransfer.files[0]);
          }}>
          <input type="file" accept="image/png,image/jpeg,image/webp" onChange={(e) => enviar(e.target.files?.[0])} />
          <strong>{ocupado ? 'Enviando…' : 'Arraste uma imagem aqui'}</strong>
          <small>ou clique para escolher · JPG, PNG ou WebP, até 20 MB · fica só no seu computador</small>
        </label>
      ) : null}

      {fonte === 'pexels' ? (
        pexels.configurada ? (
          <div className="campo">
            <form className="chave-ia" onSubmit={(e) => {
              e.preventDefault();
              void tentar(async () => setFotos((await api.buscarPexels(busca, orientacao)).fotos));
            }}>
              <input type="search" value={busca} placeholder="o que buscar: praia, estúdio, dinheiro…"
                aria-label="buscar no Pexels" onChange={(e) => setBusca(e.target.value)} />
              <button type="submit" className="botao pequeno" disabled={!busca.trim() || ocupado}>
                {ocupado ? 'Buscando…' : 'Buscar'}
              </button>
            </form>
            {fotos.length ? (
              <div className="fotos-pexels">
                {fotos.map((f) => (
                  <button key={f.id} type="button" title={f.alt || `Foto de ${f.autor}`}
                    onClick={() => void tentar(async () => usarImagem(await api.usarPexels(f.id)))}>
                    <img src={api.previaPexels(f.id)} alt={f.alt || `Foto de ${f.autor}`} loading="lazy" />
                    <span>{f.autor}</span>
                  </button>
                ))}
              </div>
            ) : null}
            <small>
              Fotos do <a href="https://www.pexels.com" target="_blank" rel="noreferrer">Pexels</a>, de uso livre.
              Só a busca sai do seu computador. Chave {pexels.final}{' '}
              {pexels.origem === 'arquivo' ? (
                <button type="button" className="link" onClick={() => void api.apagarChavePexels().then(setPexels)}>
                  (remover)
                </button>
              ) : null}
            </small>
          </div>
        ) : (
          <form className="campo" onSubmit={(e) => {
            e.preventDefault();
            void tentar(async () => {
              setPexels(await api.salvarChavePexels(chave.trim()));
              setChave('');
            });
          }}>
            <small>Para buscar fotos, cole uma chave grátis do Pexels (leva um minuto para criar).</small>
            <div className="chave-ia">
              <input type="password" autoComplete="off" spellCheck={false} value={chave}
                placeholder="Cole aqui a sua chave do Pexels" aria-label="chave do Pexels"
                onChange={(e) => setChave(e.target.value)} />
              <button type="submit" className="botao pequeno" disabled={!chave.trim() || ocupado}>
                {ocupado ? 'Conferindo…' : 'Salvar chave'}
              </button>
            </div>
            <a href="https://www.pexels.com/api/" target="_blank" rel="noreferrer">Pegar uma chave grátis do Pexels</a>
          </form>
        )
      ) : null}

      {fonte === 'gerar' ? (
        iaConfigurada ? (
          <form className="campo" onSubmit={(e) => {
            e.preventDefault();
            void tentar(async () => {
              const r = await api.gerarFundo(cena, proporcao, config.lado);
              setGeracao({...geracao, restantes: r.restantes});
              usarImagem(r);
            });
          }}>
            <textarea rows={3} maxLength={300} value={cena} aria-label="descrição do fundo"
              placeholder="Descreva o fundo: um estúdio com luzes neon, uma cozinha ensolarada…"
              onChange={(e) => setCena(e.target.value)} />
            <div className="linha-de-opcoes">
              <button type="submit" className="botao pequeno" disabled={!cena.trim() || ocupado || !geracao.restantes}>
                {ocupado ? 'Gerando…' : 'Gerar fundo (~US$ 0,04)'}
              </button>
              <small>{geracao.restantes} de {geracao.teto} nesta sessão</small>
            </div>
            <small>
              Usa o Gemini com a sua chave e exige faturamento ligado no Google AI Studio. Só a descrição sai do
              computador, e o mesmo pedido não é cobrado duas vezes.
            </small>
          </form>
        ) : (
          <div className="aviso">Para gerar um fundo, cole a chave do Gemini no painel "Thumbnail com IA", acima.</div>
        )
      ) : null}

      {erro ? <div className="aviso erro">{erro}</div> : null}
      {config.fundo === 'imagem' && config.imagem?.credito ? (
        <small className="credito">
          {config.imagem.origem === 'gerada' ? 'Gerada: ' : 'Foto: '}{config.imagem.credito}
        </small>
      ) : null}

      {config.fundo !== 'cor' ? (
        <label className="campo">
          <span>Desfoque: {Math.round(config.desfoque * 100)}%</span>
          <input type="range" min={0} max={1} step={0.05} value={config.desfoque}
            onChange={(e) => mudar({desfoque: Number(e.target.value)})} />
        </label>
      ) : null}
      {config.fundo !== 'cor' ? (
        <label className="campo">
          <span>Escurecer o lado do texto: {Math.round(config.escurecer * 100)}%</span>
          <input type="range" min={0} max={1} step={0.05} value={config.escurecer}
            onChange={(e) => mudar({escurecer: Number(e.target.value)})} />
        </label>
      ) : null}
      <Interruptor ligado={config.vinheta} aoMudar={(v) => mudar({vinheta: v})} titulo="Vinheta"
        descricao="Escurece as bordas e leva o olho para o meio." />
      {config.fundo !== 'cor' ? (
        <Interruptor ligado={config.tom} aoMudar={(v) => mudar({tom: v})} titulo="Tom da cor de destaque"
          descricao="Um véu da cor por cima do fundo, para combinar com o texto." />
      ) : null}
    </div>
  );
};
