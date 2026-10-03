# Terceiros

O código do editor-de-video é MIT (veja o [LICENSE](LICENSE)). Ele também usa
projetos de outras pessoas: alguns vão junto neste repositório, e outros são baixados
na instalação. A lista completa está aqui, com a licença de cada um.

## Vai junto neste repositório e no pacote

| O quê | Onde | Licença |
|---|---|---|
| Fonte **DejaVu Sans Bold** | `editor/recursos/DejaVuSans-Bold.ttf` | Bitstream Vera e domínio público: [`licencas/DejaVu-Fonts.txt`](licencas/DejaVu-Fonts.txt) |
| 122 ícones do **Tabler Icons** 3.48.0 (e os da tabela do README) | `editor/recursos/icones.json` e `docs/img/funcoes/` | MIT: [`licencas/Tabler-Icons-MIT.txt`](licencas/Tabler-Icons-MIT.txt) |
| **React**, React DOM e scheduler | dentro da página montada (`editor/interface/estatico/`) | MIT: [`licencas/React-MIT.txt`](licencas/React-MIT.txt) |
| **driver.js** 1.9, o tour | dentro da página montada | MIT: [`licencas/driver.js-MIT.txt`](licencas/driver.js-MIT.txt) |
| **Remotion** 4 e `@remotion/player`, a prévia da thumbnail | dentro da página montada | Remotion License: [`licencas/Remotion-License.md`](licencas/Remotion-License.md) |

### Sobre a licença do Remotion

O Remotion **não é MIT**. A licença dele é grátis para:

- pessoas físicas;
- empresas com até 3 funcionários;
- organizações sem fins lucrativos;
- quem ainda está avaliando, sem uso comercial.

Empresas maiores precisam de uma [Company License](https://www.remotion.pro/license).
Como o Remotion vai dentro da página do editor, isso vale para quem usa o editor numa
empresa desse tamanho.

O editor usa só o Player do Remotion, que mostra a prévia ao vivo da thumbnail. O PNG
é desenhado pelo próprio editor, no navegador, sem os servidores de render do
Remotion, e a página não faz nenhuma chamada para fora do seu computador.

## Baixado na instalação (não vem neste repositório)

| Pacote | Para quê | Licença |
|---|---|---|
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) e CTranslate2 | transcrever a fala | MIT |
| Modelos [Whisper](https://github.com/openai/whisper), convertidos pela [Systran](https://huggingface.co/Systran) | o modelo baixado no primeiro uso | MIT |
| [PyAV](https://github.com/PyAV-Org/PyAV) | ler e gravar vídeo | BSD-3-Clause (veja abaixo) |
| NumPy | as contas do áudio e dos quadros | BSD-3-Clause, entre outras |
| Pillow | desenhar legenda, adesivos e ícones | MIT-CMU |
| [rough](https://pypi.org/project/rough/) | o traço tremido dos ícones | MIT |
| FastAPI, Starlette e Uvicorn | o servidor local da interface | MIT e BSD-3-Clause |
| python-multipart | receber o vídeo enviado pela página | Apache-2.0 |
| platformdirs | achar as pastas de cada sistema | MIT |

**PyAV e FFmpeg.** As rodas do PyAV no PyPI trazem o FFmpeg compilado com o x264 e o
x265, que são GPL. É isso que deixa o editor gravar H.264 e H.265 sem instalar nada no
sistema. Essas bibliotecas são baixadas do PyPI na instalação, e este repositório não
as redistribui.

## As imagens do README

Os quadros, o "antes e depois" e o banner saem de
["Man doing podcast"](https://www.pexels.com/video/man-doing-podcast-6892735/), de
**cottonbro studio**, publicado no Pexels (licença do Pexels: uso livre, sem
atribuição obrigatória). O vídeo foi recortado em 9:16, recebeu uma narração de teste
feita por voz sintética, e depois foi editado pelo próprio editor
([`docs/gerar_imagens.py`](docs/gerar_imagens.py)).
