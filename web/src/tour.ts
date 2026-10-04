/**
 * O tour guiado: sete passos, um por área da página. Abre sozinho na primeira visita
 * e o botão "Tour" do topo refaz.
 *
 * O balão abre ao lado do cartão (à direita na coluna das opções, à esquerda no
 * painel): por cima, ele cobria justamente as opções que estava explicando.
 */
import {driver} from 'driver.js';
import 'driver.js/dist/driver.css';

const VISTO = 'editor-tour-visto';

export function comecarTour(): void {
  const tour = driver({
    showProgress: true,
    progressText: '{{current}} de {{total}}',
    nextBtnText: 'Próximo',
    prevBtnText: 'Voltar',
    doneBtnText: 'Começar a editar',
    popoverClass: 'tour-editor',
    smoothScroll: true,
    allowClose: true,
    steps: [
      {
        element: '#passo-envio',
        popover: {
          side: 'right',
          align: 'start',
          title: '1. Envie o vídeo',
          description: 'Arraste um vídeo falado (vertical ou horizontal). Ou monte em camadas: um fundo sem pessoa e, por cima, o vídeo da pessoa ou um personagem animado. Tudo é copiado para uma pasta do seu computador — nada vai para a internet.',
        },
      },
      {
        element: '#passo-edicoes',
        popover: {
          side: 'right',
          align: 'start',
          title: '2. Escolha as edições',
          description: 'Cortes de silêncio, zoom de ênfase, palavras que saltam da legenda, ícones e efeitos sonoros. Ligue só o que quiser.',
        },
      },
      {
        element: '#passo-legenda',
        popover: {
          side: 'right',
          align: 'start',
          title: '3. Legenda',
          description: 'O idioma da fala e o tamanho do Whisper, que transcreve no seu computador. Dá para levar a legenda à parte em .srt e .vtt.',
        },
      },
      {
        element: '#passo-saida',
        popover: {
          side: 'right',
          align: 'start',
          title: '4. Saída',
          description: 'Formato (MP4, MOV, WebM, MKV, GIF), codec, resolução, quadros por segundo e qualidade. Só aparece o que este computador grava.',
        },
      },
      {
        element: '#passo-thumb',
        popover: {
          side: 'right',
          align: 'start',
          title: '5. Thumbnail',
          description: 'Uma capa separada, com a pessoa recortada, a chamada e a palavra em destaque. Com uma chave do Gemini (opcional), a IA sugere 3 ideias de acordo com o que você falou. A prévia é ao vivo.',
        },
      },
      {
        element: '#botao-editar',
        popover: {
          side: 'left',
          align: 'start',
          title: '6. Editar',
          description: 'Começa a edição. A barra mostra cada etapa e quanto falta. Marque "só os primeiros 15 s" para testar o estilo rapidinho.',
        },
      },
      {
        element: '#passo-resultado',
        popover: {
          side: 'left',
          align: 'start',
          title: '7. Resultado',
          description: 'Assista, baixe o vídeo, as legendas e as thumbnails, ou abra a pasta onde tudo foi salvo.',
        },
      },
    ],
    onDestroyed: () => {
      try {
        localStorage.setItem(VISTO, '1');
      } catch {
        /* sem armazenamento: o tour só volta pelo botão */
      }
    },
  });
  tour.drive();
}

export function tourJaVisto(): boolean {
  try {
    return localStorage.getItem(VISTO) === '1';
  } catch {
    return true;
  }
}
