import react from '@vitejs/plugin-react';
import {defineConfig, type ProxyOptions} from 'vite';

// A página montada vai para dentro do pacote Python, que a serve.
// Em desenvolvimento, o Vite repassa a API para o servidor em 8765:
//   editar --porta 8765 --sem-navegador   (em outro terminal)
// e a página abre em http://localhost:5173/?t=<o token que o editar mostrou>.
//
// O servidor só aceita pedidos com Host e Origin dele mesmo, então o repasse se
// apresenta como ele; quem protege continua sendo o token.
const API = 'http://127.0.0.1:8765';
const repassar: ProxyOptions = {target: API, changeOrigin: true, headers: {origin: API}};

export default defineConfig({
  plugins: [react()],
  base: '/',
  build: {
    outDir: '../editor/interface/estatico',
    emptyOutDir: true,
    chunkSizeWarningLimit: 1500,
  },
  server: {
    proxy: {
      '/api': repassar,
      '/fontes': repassar,
      '/maos': repassar,
    },
  },
});
