import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // O App.jsx chama a API em /api (caminho relativo), e não numa URL
  // absoluta. Em desenvolvimento quem resolve isso é este proxy; em
  // produção quem resolve é o vhost, que faz proxy de /api para o backend.
  // Sem isso o dev server responderia 404 nas chamadas da API.
  //
  // A porta 8002 é a mesma do compose: o host 8000 já é do aletheia_backend na
  // VPS de produção. VITE_API_TARGET sobrescreve para outro ambiente.
  const env = loadEnv(mode, process.cwd(), '')
  const alvo = env.VITE_API_TARGET || 'http://localhost:8002'

  return {
    plugins: [react()],
    server: {
      proxy: {
        '/api': {
          target: alvo,
          changeOrigin: true,
        },
      },
    },
  }
})
