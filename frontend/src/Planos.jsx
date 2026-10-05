import { useEffect, useState } from 'react';
import {
  Check, CreditCard, Loader2, Mail, ShieldCheck, Sparkles, X,
} from 'lucide-react';

/**
 * Tela de planos com o botão "Assinar".
 *
 * O caminho é: card do plano -> toast pedindo o e-mail -> redireciona para a
 * Stripe. A pessoa não cria conta antes de pagar. O backend cria a conta em
 * estado `pendente` e devolve a URL do checkout; o acesso só é liberado pelo
 * webhook, depois que o pagamento é confirmado.
 */

const reais = (centavos) =>
  (centavos / 100).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });

export default function Planos({ aoVoltar }) {
  const [planos, setPlanos] = useState([]);
  const [carregando, setCarregando] = useState(true);
  const [indisponivel, setIndisponivel] = useState('');
  const [escolhido, setEscolhido] = useState(null);
  const [email, setEmail] = useState('');
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState('');

  useEffect(() => {
    let vivo = true;
    (async () => {
      try {
        const res = await fetch('/api/assinatura/planos');
        const dados = await res.json();
        if (!vivo) return;
        setPlanos(dados.planos || []);
      } catch {
        if (vivo) setErro('Não foi possível carregar os planos.');
      } finally {
        if (vivo) setCarregando(false);
      }
    })();
    return () => { vivo = false; };
  }, []);

  /**
   * Ao voltar da Stripe o pagamento vem confirmado por query string. Limpamos a
   * URL com `replaceState` porque o token de acesso veio nela — deixá-lo na barra
   * de endereços o expõe a quem pegar o celular emprestado e ao histórico.
   */
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('token')) {
      window.history.replaceState({}, document.title, window.location.pathname);
    }
  }, []);

  const assinar = async (evento) => {
    evento.preventDefault();
    if (enviando) return;
    setEnviando(true);
    setErro('');

    try {
      const res = await fetch('/api/assinatura/assinar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, plano: escolhido.chave }),
      });
      const dados = await res.json();

      if (!res.ok) {
        setErro(dados.detail || 'Não foi possível abrir o pagamento.');
        return;
      }
      // `location.assign` e não um <a>: sair da página é o ponto, e o Stripe
      // recusa checkout dentro de iframe, que é o que abrir em aba nova faz.
      window.location.assign(dados.url);
    } catch {
      setErro('Falha de conexão. Verifique a internet e tente de novo.');
    } finally {
      setEnviando(false);
    }
  };

  const fechar = () => {
    setEscolhido(null);
    setErro('');
    setEmail('');
  };

  return (
    <div className="lz-planos">
      <div className="lz-planos-topo">
        <div>
          <h1 className="lz-planos-titulo">Planos</h1>
          <p className="lz-planos-sub">
            Cobra por mês, cancela quando quiser. Sem fidelidade.
          </p>
        </div>
        {aoVoltar && (
          <button type="button" onClick={aoVoltar} className="lz-btn lz-btn-fantasma">
            Voltar
          </button>
        )}
      </div>

      {carregando && (
        <div className="lz-planos-carregando">
          <Loader2 size={28} className="spin" /> Carregando planos...
        </div>
      )}

      {indisponivel && !carregando && (
        <div className="lz-error">{indisponivel}</div>
      )}

      {!carregando && !indisponivel && (
        <div className="lz-planos-grade">
          {planos.map((plano) => (
            <div
              key={plano.chave}
              className={`lz-card-plano${plano.destaque ? ' lz-card-destaque' : ''}`}
            >
              {plano.destaque && (
                <div className="lz-faixa">
                  <Sparkles size={14} /> Mais escolhido
                </div>
              )}

              <h2 className="lz-plano-nome">{plano.nome}</h2>
              <p className="lz-plano-desc">{plano.descricao}</p>

              <div className="lz-plano-preco">
                <strong>{reais(plano.preco_centavos)}</strong>
                <span>/mês</span>
              </div>

              <ul className="lz-plano-lista">
                <li><Check size={16} /> Até {plano.limite_clientes.toLocaleString('pt-BR')} clientes</li>
                <li><Check size={16} /> {plano.limite_mensagens_mes.toLocaleString('pt-BR')} mensagens por mês</li>
                {(plano.recursos || []).map((recurso) => (
                  <li key={recurso}><Check size={16} /> {recurso}</li>
                ))}
              </ul>

              <button
                type="button"
                className={`lz-btn${plano.destaque ? ' lz-btn-destaque' : ''}`}
                onClick={() => { setEscolhido(plano); setErro(''); }}
              >
                <CreditCard size={17} /> Assinar {plano.nome}
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="lz-planos-rodape">
        <ShieldCheck size={16} /> Pagamento seguro processado pelo Stripe.
      </div>

      {escolhido && (
        <div className="lz-toast-fundo" onClick={fechar} role="presentation">
          <div
            className="lz-toast"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-labelledby="lz-toast-titulo"
          >
            <button
              type="button"
              className="lz-toast-fechar"
              onClick={fechar}
              aria-label="Fechar"
            >
              <X size={18} />
            </button>

            <div className="lz-toast-icone">
              <Mail size={22} />
            </div>

            <h3 id="lz-toast-titulo" className="lz-toast-titulo">
              Assinar {escolhido.nome}
            </h3>
            <p className="lz-toast-texto">
              {reais(escolhido.preco_centavos)} por mês. A cobrança vai para este e-mail.
            </p>

            {erro && <div className="lz-error">{erro}</div>}

            <form onSubmit={assinar}>
              <label className="lz-label" htmlFor="lz-email">Seu e-mail</label>
              <input
                id="lz-email"
                type="email"
                required
                autoFocus
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="voce@seudominio.com.br"
                className="lz-input"
              />
              <button type="submit" className="lz-btn" disabled={enviando}>
                {enviando ? (
                  <>
                    <Loader2 size={17} className="spin" /> Abrindo pagamento...
                  </>
                ) : (
                  <>
                    Ir para o pagamento <CreditCard size={17} />
                  </>
                )}
              </button>
            </form>

            <p className="lz-toast-nota">
              Você entra direto no painel depois que o pagamento for confirmado.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}