/**
 * De onde vem o áudio da montagem: do vídeo de fundo, do vídeo da pessoa, de um áudio
 * separado (um ou vários) ou da "Minha voz" (a voz salva narrando um roteiro). Com o
 * personagem, que não tem som, só do fundo, do separado ou da voz; com a biblioteca de
 * cenas (o som dos clipes não é a fala), só da pessoa, do separado ou da voz.
 *
 * A escolha de quem edita vale enquanto ela fizer sentido. Sem escolha (ou com uma que
 * não serve mais, como "a pessoa" depois de trocar para o personagem), vale a primeira
 * que tem som: a pessoa, o fundo, o áudio separado. Sem som em lugar nenhum, o fundo: o
 * vídeo sai mudo, sem cortes e sem legenda. A "Minha voz" só vale escolhida.
 */
import type {AudioInfo, Fala, MontagemConfig, VideoInfo} from './tipos';

/** Se um vídeo enviado não tem som (o que ainda não foi enviado pode ter). */
export const semSom = (v: VideoInfo | null) => Boolean(v && !v.tem_audio);

export function opcoesDeFala(m: MontagemConfig): Fala[] {
  const fundo: Fala[] = m.fonteDoFundo === 'cenas' ? [] : ['fundo'];
  return m.porCima === 'pessoa' ? [...fundo, 'pessoa', 'audio', 'voz'] : [...fundo, 'audio', 'voz'];
}

export function falaEfetiva(m: MontagemConfig, fundo: VideoInfo | null, pessoa: VideoInfo | null,
                            audios: AudioInfo[]): Fala {
  const pode = (f: Fala) => opcoesDeFala(m).includes(f)
    && (f === 'fundo' ? !semSom(fundo) : f === 'pessoa' ? !semSom(pessoa) : true);
  if (m.fala && pode(m.fala)) return m.fala;
  if (m.porCima === 'pessoa' && pessoa?.tem_audio) return 'pessoa';
  if (m.fonteDoFundo !== 'cenas' && fundo?.tem_audio) return 'fundo';
  if (audios.length || m.fonteDoFundo === 'cenas') return 'audio';
  return 'fundo';
}

/** Os áudios na ordem em que tocam: a do nome, com os números em ordem ("Parte 2" antes
 *  de "Parte 10"). */
export const emOrdem = (lista: AudioInfo[]) =>
  [...lista].sort((a, b) => a.nome.localeCompare(b.nome, 'pt-BR', {numeric: true, sensitivity: 'base'}));
