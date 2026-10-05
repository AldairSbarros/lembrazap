import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import Admin from './Admin.jsx'
import './App.css' // <--- Confere se esta linha existe!

// O painel do proprietário é um bundle separado, montado no mesmo `index.html` e
// escolhido pela URL (`/admin`). Não é multi-page de verdade: evita uma segunda
// entrada no build do Vite e uma segunda regra no nginx, que já faz fallback de
// SPA para qualquer caminho. `/admin` nunca é uma tela do painel do assinante, e o
// token vive em outra chave do localStorage, então abrir uma não autentica a outra.
const ehAdmin = window.location.pathname.startsWith('/admin')

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    {ehAdmin ? <Admin /> : <App />}
  </React.StrictMode>,
)