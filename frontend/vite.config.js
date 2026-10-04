import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // O App.jsx chama a API em /api (caminho relativo), e não numa URL
    // absoluta. Em desenvolvimento quem resolve isso é este proxy; em
    // produção quem resolve é o vhost, que faz proxy de /api para o backend.
    // Sem isso o dev server responderia 404 nas chamadas da API.
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
