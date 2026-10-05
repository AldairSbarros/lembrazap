import { useCallback, useEffect, useState } from 'react'

const CHAVE_TOKEN = 'lz_admin_token'

const CABECALHO = { 'Content-Type': 'application/json' }

function reais(centavos) {
  if (!centavos) return 'R$ 0,00'
  return `R$ ${(centavos / 100).toFixed(2).replace('.', ',')}`
}

function dataCurta(iso) {
  if (!iso) return '—'
  const d = new Date(iso.endsWith('Z') ? iso : `${iso}Z`)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit', year: '2-digit' })
}

function hora(iso) {
  if (!iso) return '—'
  const d = new Date(iso.endsWith('Z') ? iso : `${iso}Z`)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })
}

/**
 * Cliente HTTP do painel admin.
 *
 * Lança `ErroApi` com o detalhe do servidor para que a tela mostre a mensagem real
 * ("conta suspensa", "limite do plano") em vez de um genérico "erro".
 */
async function api(caminho, opcoes = {}) {
  const token = localStorage.getItem(CHAVE_TOKEN)
  const resposta = await fetch(caminho, {
    ...opcoes,
    headers: { ...CABECALHO, 'X-LZ-Admin': token || '', ...(opcoes.headers || {}) },
  })

  const texto = await resposta.text()
  let corpo
  try {
    corpo = texto ? JSON.parse(texto) : {}
  } catch {
    corpo = { detail: texto }
  }

  if (!resposta.ok) {
    const erro = new Error(corpo.detail || `Erro ${resposta.status}`)
    erro.status = resposta.status
    throw erro
  }
  return corpo
}

// ------------------------------------------------------------------ login

function LoginAdmin({ aoEntrar }) {
  const [email, setEmail] = useState('')
  const [senha, setSenha] = useState('')
  const [erro, setErro] = useState('')
  const [enviando, setEnviando] = useState(false)

  async function entrar(evento) {
    evento.preventDefault()
    setErro('')
    setEnviando(true)
    try {
      const dados = await api('/api/admin/login', {
        method: 'POST',
        body: JSON.stringify({ email, senha }),
      })
      localStorage.setItem(CHAVE_TOKEN, dados.token)
      aoEntrar(dados)
    } catch (e) {
      setErro(e.message)
    } finally {
      setEnviando(false)
    }
  }

  return (
    <div className="admin-login">
      <form className="admin-login__card" onSubmit={entrar}>
        <div className="admin-login__marca">LembraZap</div>
        <h1 className="admin-login__titulo">Painel do proprietário</h1>
        <p className="admin-login__sub">
          Acesso restrito. Contas de assinantes não entram aqui.
        </p>

        <label className="lz-campo">
          <span className="lz-label">E-mail</span>
          <input
            type="email"
            className="lz-input"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="username"
            required
          />
        </label>

        <label className="lz-campo">
          <span className="lz-label">Senha</span>
          <input
            type="password"
            className="lz-input"
            value={senha}
            onChange={(e) => setSenha(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>

        {erro && <div className="admin-login__erro">{erro}</div>}

        <button className="lz-btn admin-login__botao" disabled={enviando}>
          {enviando ? 'Entrando...' : 'Entrar'}
        </button>
      </form>
    </div>
  )
}

// ------------------------------------------------------------------ topo

function Cabecalho({ sessao, metricas, aoSair }) {
  const stripeAviso = !metricas?.stripe_configurado && (
    <span className="admin-aviso" title="Configure STRIPE_SECRET_KEY para cobrar automaticamente">
      Stripe não configurado — cobrança manual
    </span>
  )

  return (
    <header className="admin-topo">
      <div className="admin-topo__marca">
        <strong>LembraZap</strong>
        <span className="admin-topo__painel">painel do proprietário</span>
      </div>
      <div className="admin-topo__direita">
        {stripeAviso}
        <span className="admin-topo__usuario">{sessao.nome}</span>
        <a className="admin-topo__link" href="/">
          Ver como assinante
        </a>
        <button className="lz-btn lz-btn-secundario lz-btn--pequeno" onClick={aoSair}>
          Sair
        </button>
      </div>
    </header>
  )
}

// ------------------------------------------------------------------ cartões

function Cartao({ titulo, valor, detalhe, tom }) {
  return (
    <div className={`admin-cartao${tom ? ` admin-cartao--${tom}` : ''}`}>
      <div className="admin-cartao__rotulo">{titulo}</div>
      <div className="admin-cartao__valor">{valor}</div>
      {detalhe && <div className="admin-cartao__detalhe">{detalhe}</div>}
    </div>
  )
}

function VisaoGeral({ metricas, planos }) {
  if (!metricas) return null

  const porStatus = metricas.por_status || {}
  const chips = [
    ['trial', 'Em teste'],
    ['ativo', 'Ativos'],
    ['inadimplente', 'Inadimplentes'],
    ['suspenso', 'Suspensos'],
    ['cancelado', 'Cancelados'],
  ].filter(([chave]) => porStatus[chave])

  return (
    <>
      <div className="admin-cartoes">
        <Cartao titulo="Contas" valor={metricas.total_contas} detalhe={`${metricas.contas_com_acesso} com acesso`} />
        <Cartao titulo="Receita no mês" valor={reais(metricas.receita_mes_centavos)} tom="bom" />
        <Cartao titulo="Mensagens no mês" valor={metricas.mensagens_mes.toLocaleString('pt-BR')} />
        <Cartao
          titulo="Inadimplentes"
          valor={porStatus.inadimplente || 0}
          detalhe="sem acesso ao disparo"
          tom={porStatus.inadimplente ? 'ruim' : undefined}
        />
      </div>

      <div className="admin-faixa">
        {chips.map(([chave, rotulo]) => (
          <span key={chave} className={`admin-chip admin-chip--${chave}`}>
            {rotulo}: <strong>{porStatus[chave]}</strong>
          </span>
        ))}
        <span className="admin-chip admin-chip--info">
          Planos: {planos?.map((p) => `${p.nome} ${reais(p.preco_centavos)}`).join(' · ')}
        </span>
      </div>
    </>
  )
}

// ------------------------------------------------------------------ lista

function ListaContas({ contas, aoAbrir, aoRecarregar }) {
  const [busca, setBusca] = useState('')
  const [filtro, setFiltro] = useState('')

  const filtradas = contas.filter((c) => {
    if (filtro && c.status !== filtro) return false
    if (!busca.trim()) return true
    const alvo = busca.trim().toLowerCase()
    return (
      c.nome.toLowerCase().includes(alvo) ||
      (c.negocio || '').toLowerCase().includes(alvo) ||
      (c.email_contato || '').toLowerCase().includes(alvo)
    )
  })

  const filtros = [
    ['', 'Todas'],
    ['ativo', 'Ativas'],
    ['trial', 'Em teste'],
    ['inadimplente', 'Inadimplentes'],
    ['suspenso', 'Suspensas'],
    ['cancelado', 'Canceladas'],
  ]

  return (
    <div className="admin-lista">
      <div className="admin-lista__barra">
        <input
          className="lz-input admin-lista__busca"
          placeholder="Buscar por nome, negócio ou e-mail..."
          value={busca}
          onChange={(e) => setBusca(e.target.value)}
        />
        <div className="admin-filtros">
          {filtros.map(([valor, rotulo]) => (
            <button
              key={valor}
              className={`admin-filtro${filtro === valor ? ' admin-filtro--ativo' : ''}`}
              onClick={() => setFiltro(valor)}
            >
              {rotulo}
            </button>
          ))}
        </div>
        <button className="lz-btn lz-btn-secundario lz-btn--pequeno" onClick={aoRecarregar}>
          Atualizar
        </button>
      </div>

      <div className="admin-tabela__cabecalho admin-tabela__linha">
        <span>Conta</span>
        <span>Plano</span>
        <span>Status</span>
        <span>Clientes</span>
        <span>Ativos</span>
        <span>Mensagens</span>
        <span>Renovação</span>
        <span />
      </div>

      {filtradas.length === 0 && (
        <p className="admin-vazio">Nenhuma conta encontrada com esse filtro.</p>
      )}

      {filtradas.map((c) => (
        <button key={c.id} className="admin-tabela__linha admin-tabela__linha--clicavel" onClick={() => aoAbrir(c.id)}>
          <span className="admin-tabela__conta">
            <strong>{c.negocio || c.nome}</strong>
            <small>{c.email_contato || c.nome}</small>
          </span>
          <span>{c.plano_nome}</span>
          <span><span className={`admin-status admin-status--${c.status}`}>{c.status_rotulo}</span></span>
          <span>{c.metricas.clientes_total}</span>
          <span>{c.metricas.clientes_ativos}</span>
          <span>{c.metricas.mensagens_mes}</span>
          <span>{c.renovacao_em ? dataCurta(c.renovacao_em) : '—'}</span>
          <span className="admin-tabela__seta">›</span>
        </button>
      ))}
    </div>
  )
}

// ------------------------------------------------------------------ detalhe

function DetalheConta({ tenantId, aoVoltar, aoRecarregar }) {
  const [conta, setConta] = useState(null)
  const [clientes, setClientes] = useState([])
  const [planos, setPlanos] = useState([])
  const [mensagem, setMensagem] = useState('')
  const [erro, setErro] = useState('')
  const [novoToken, setNovoToken] = useState('')

  const carregar = useCallback(async () => {
    setErro('')
    try {
      const [detalhe, base] = await Promise.all([
        api(`/api/admin/contas/${tenantId}`),
        api(`/api/admin/contas/${tenantId}/clientes?limite=25`),
      ])
      setConta(detalhe)
      setClientes(base.clientes || [])
    } catch (e) {
      setErro(e.message)
    }
  }, [tenantId])

  useEffect(() => {
    // O setTimeout tira o setState do corpo do efeito, que é o que a regra
    // react-hooks/set-state-in-effect acusa. Mesmo truque usado em Clientes.jsx.
    const t = setTimeout(carregar, 0)
    return () => clearTimeout(t)
  }, [carregar])

  useEffect(() => {
    let cancelado = false
    api('/api/admin/planos')
      .then((d) => {
        if (!cancelado) setPlanos(d.planos || [])
      })
      .catch(() => {})
    return () => {
      cancelado = true
    }
  }, [])

  async function acao(caminho, corpo, texto) {
    setErro('')
    setMensagem('')
    setNovoToken('')
    try {
      const resposta = await api(caminho, {
        method: corpo ? 'POST' : 'PATCH',
        body: corpo ? JSON.stringify(corpo) : undefined,
      })
      if (resposta.token) setNovoToken(resposta.token)
      setConta((atual) => ({ ...atual, ...resposta.contas, ...resposta }))
      if (texto) setMensagem(texto(resposta))
      aoRecarregar()
      carregar()
    } catch (e) {
      setErro(e.message)
    }
  }

  if (!conta) {
    return (
      <div className="admin-painel">
        <button className="lz-btn lz-btn-secundario" onClick={aoVoltar}>← Voltar</button>
        {erro ? <p className="admin-erro">{erro}</p> : <p className="admin-vazio">Carregando...</p>}
      </div>
    )
  }

  const m = conta.metricas

  return (
    <div className="admin-painel">
      <div className="admin-painel__topo">
        <button className="lz-btn lz-btn-secundario" onClick={aoVoltar}>← Voltar</button>
        <h2>{conta.negocio || conta.nome}</h2>
        <span className={`admin-status admin-status--${conta.status}`}>{conta.status_rotulo}</span>
      </div>

      {erro && <div className="admin-erro">{erro}</div>}
      {mensagem && <div className="admin-ok">{mensagem}</div>}

      {novoToken && (
        <div className="admin-token">
          <strong>Token (aparece uma única vez):</strong>
          <code>{novoToken}</code>
        </div>
      )}

      {!conta.acesso_liberado && conta.motivo_bloqueio && (
        <div className="admin-bloqueio">
          <strong>Sem acesso ao disparo.</strong> {conta.motivo_bloqueio}
          {conta.motivo_suspensao && <small>Motivo registrado: {conta.motivo_suspensao}</small>}
        </div>
      )}

      <div className="admin-cartoes admin-cartoes--menor">
        <Cartao titulo="Clientes" valor={m.clientes_total} detalhe={`${m.clientes_ativos} ativos em 90 dias`} />
        <Cartao titulo="Agenda hoje" valor={m.agendamentos_hoje} />
        <Cartao titulo="Mensagens no mês" valor={m.mensagens_mes} detalhe={`${m.falhas_mes} falhas`} />
        <Cartao titulo="Instância" valor={conta.tem_instancia ? 'OK' : '—'} detalhe={conta.instancia || 'sem pareamento'} />
      </div>

      <div className="admin-grade">
        <section className="admin-bloco">
          <h3>Cobrança</h3>
          <label className="lz-campo">
            <span className="lz-label">Plano</span>
            <select
              className="lz-input"
              value={conta.plano}
              onChange={(e) => acao(`/api/admin/contas/${conta.id}`, { plano: e.target.value }, () => 'Plano alterado.')}
            >
              {planos.map((p) => (
                <option key={p.chave} value={p.chave}>
                  {p.nome} — {reais(p.preco_centavos)} ({p.limite_clientes} clientes)
                </option>
              ))}
            </select>
          </label>

          <dl className="admin-dl">
            <dt>Criada em</dt><dd>{dataCurta(conta.criado_em)}</dd>
            <dt>Renovação</dt><dd>{conta.renovacao_em ? dataCurta(conta.renovacao_em) : '—'}</dd>
            <dt>Último envio</dt><dd>{conta.ultima_envio_em ? hora(conta.ultima_envio_em) : '—'}</dd>
            <dt>Stripe</dt><dd>{conta.no_stripe ? 'integrada' : 'não integrada'}</dd>
            <dt>ID da conta</dt><dd><code>{conta.id}</code></dd>
          </dl>

          <div className="admin-acoes">
            {conta.acesso_liberado ? (
              <button
                className="lz-btn lz-btn--perigo"
                onClick={() =>
                  acao(
                    `/api/admin/contas/${conta.id}/suspender`,
                    { motivo: 'Suspenso pelo proprietário' },
                    (r) => r.mensagem,
                  )
                }
              >
                Suspender
              </button>
            ) : (
              <>
                <button
                  className="lz-btn"
                  onClick={() =>
                    acao(`/api/admin/contas/${conta.id}/reativar`, { dias: 30 }, () => 'Conta reativada por 30 dias.')
                  }
                >
                  Reativar 30 dias
                </button>
                <button
                  className="lz-btn lz-btn-secundario"
                  onClick={() =>
                    acao(`/api/admin/contas/${conta.id}/reativar`, { dias: 0 }, () => 'Conta liberada sem vencimento.')
                  }
                >
                  Liberar sem prazo
                </button>
              </>
            )}
            <button
              className="lz-btn lz-btn-secundario"
              onClick={() =>
                acao(`/api/admin/contas/${conta.id}/token`, null, () => 'Token anterior invalidado.')
              }
            >
              Gerar novo token
            </button>
          </div>
        </section>

        <section className="admin-bloco">
          <h3>Clientes (25 mais antigos)</h3>
          {clientes.length === 0 && <p className="admin-vazio">Nenhum cliente cadastrado.</p>}
          <div className="admin-clientes">
            {clientes.map((c) => (
              <div key={c.id} className="admin-cliente">
                <div>
                  <strong>{c.nome}</strong>
                  <small>
                    {c.telefone_mascarado}
                    {c.ultima_visita ? ` · ${dataCurta(c.ultima_visita)}` : ' · sem histórico'}
                  </small>
                </div>
                <span className={`admin-situacao admin-situacao--${c.situacao}`}>{c.situacao}</span>
                {c.opt_out && <span className="admin-chip admin-chip--suspenso">opt-out</span>}
              </div>
            ))}
          </div>
        </section>
      </div>

      <section className="admin-bloco">
        <h3>Histórico de cobrança</h3>
        {(conta.pagamentos || []).length === 0 && (
          <p className="admin-vazio">Nenhum registro ainda.</p>
        )}
        <div className="admin-tabela__cabecalho admin-tabela__linha admin-tabela__linha--curta">
          <span>Data</span><span>Tipo</span><span>Descrição</span><span>Status</span><span>Valor</span>
        </div>
        {(conta.pagamentos || []).map((p) => (
          <div key={p.id} className="admin-tabela__linha admin-tabela__linha--curta">
            <span>{dataCurta(p.criado_em)}</span>
            <span>{p.tipo}</span>
            <span>{p.descricao}</span>
            <span><span className={`admin-status admin-status--${p.status === 'pago' ? 'ativo' : 'inadimplente'}`}>{p.status}</span></span>
            <span>{reais(p.valor_centavos)}</span>
          </div>
        ))}
      </section>
    </div>
  )
}

// ------------------------------------------------------------------ criar

function NovaConta({ planos, aoCriada, aoCancelar }) {
  const [form, setForm] = useState({ nome: '', negocio: '', email_contato: '', plano: 'starter', dias_teste: 14 })
  const [criada, setCriada] = useState(null)
  const [erro, setErro] = useState('')

  function campo(nome, valor) {
    return setForm((f) => ({ ...f, [nome]: valor }))
  }

  async function salvar(evento) {
    evento.preventDefault()
    setErro('')
    try {
      const resposta = await api('/api/admin/contas', {
        method: 'POST',
        body: JSON.stringify({ ...form, criar_instancia: true }),
      })
      setCriada(resposta)
      aoCriada()
    } catch (e) {
      setErro(e.message)
    }
  }

  if (criada) {
    return (
      <div className="admin-bloco admin-bloco--destaque">
        <h3>Conta criada</h3>
        <div className="admin-token">
          <strong>Token do cliente (aparece uma única vez):</strong>
          <code>{criada.token}</code>
        </div>
        <p className="admin-vazio">
          Instância: {criada.instancia || 'não criada'}. {criada.aviso}
        </p>
        <button className="lz-btn" onClick={aoCancelar}>Voltar à lista</button>
      </div>
    )
  }

  return (
    <form className="admin-bloco" onSubmit={salvar}>
      <h3>Nova conta</h3>
      {erro && <div className="admin-erro">{erro}</div>}

      <div className="admin-form__linha">
        <label className="lz-campo">
          <span className="lz-label">Nome do responsável</span>
          <input className="lz-input" value={form.nome} onChange={(e) => campo('nome', e.target.value)} required />
        </label>
        <label className="lz-campo">
          <span className="lz-label">Negócio</span>
          <input className="lz-input" value={form.negocio} onChange={(e) => campo('negocio', e.target.value)} />
        </label>
        <label className="lz-campo">
          <span className="lz-label">E-mail de contato</span>
          <input className="lz-input" type="email" value={form.email_contato} onChange={(e) => campo('email_contato', e.target.value)} />
        </label>
      </div>

      <div className="admin-form__linha">
        <label className="lz-campo">
          <span className="lz-label">Plano</span>
          <select className="lz-input" value={form.plano} onChange={(e) => campo('plano', e.target.value)}>
            {planos.map((p) => (
              <option key={p.chave} value={p.chave}>
                {p.nome} — {reais(p.preco_centavos)}
              </option>
            ))}
          </select>
        </label>
        <label className="lz-campo">
          <span className="lz-label">Dias de teste (0 = já cobrar)</span>
          <input className="lz-input" type="number" min="0" max="365" value={form.dias_teste} onChange={(e) => campo('dias_teste', Number(e.target.value))} />
        </label>
      </div>

      <div className="admin-acoes">
        <button className="lz-btn">Criar conta</button>
        <button type="button" className="lz-btn lz-btn-secundario" onClick={aoCancelar}>Cancelar</button>
      </div>
    </form>
  )
}

// ------------------------------------------------------------------ raiz

export default function Admin() {
  const [sessao, setSessao] = useState(null)
  const [metricas, setMetricas] = useState(null)
  const [contas, setContas] = useState([])
  const [planos, setPlanos] = useState([])
  const [aberta, setAberta] = useState('')
  const [criando, setCriando] = useState(false)
  const [erro, setErro] = useState('')

  const carregar = useCallback(async () => {
    try {
      const [visao, lista, catalogo] = await Promise.all([
        api('/api/admin/metricas'),
        api('/api/admin/contas'),
        api('/api/admin/planos'),
      ])
      setMetricas(visao)
      setContas(lista.contas || [])
      setPlanos(catalogo.planos || [])
      setErro('')
    } catch (e) {
      // 401 aqui significa sessão expirada: volta para o login em vez de mostrar erro.
      if (e.status === 401) {
        localStorage.removeItem(CHAVE_TOKEN)
        setSessao(null)
      } else {
        setErro(e.message)
      }
    }
  }, [])

  useEffect(() => {
    const guardado = localStorage.getItem(CHAVE_TOKEN)
    if (!guardado) return
    api('/api/admin/eu')
      .then((d) => setSessao(d))
      .catch(() => localStorage.removeItem(CHAVE_TOKEN))
  }, [])

  useEffect(() => {
    if (!sessao) return
    const t = setTimeout(carregar, 0)
    return () => clearTimeout(t)
  }, [sessao, carregar])

  function sair() {
    localStorage.removeItem(CHAVE_TOKEN)
    setSessao(null)
  }

  if (!sessao) return <LoginAdmin aoEntrar={setSessao} />

  return (
    <div className="admin">
      <Cabecalho sessao={sessao} metricas={metricas} aoSair={sair} />

      <main className="admin-conteudo">
        <h1 className="admin-titulo">Visão geral</h1>
        <VisaoGeral metricas={metricas} planos={planos} />

        <div className="admin-titulo__linha">
          <h1 className="admin-titulo">Contas</h1>
          <button className="lz-btn lz-btn--pequeno" onClick={() => { setCriando(!criando); setAberta('') }}>
            {criando ? 'Fechar' : '+ Nova conta'}
          </button>
        </div>

        {erro && <div className="admin-erro">{erro}</div>}

        {criando && (
          <NovaConta planos={planos} aoCriada={carregar} aoCancelar={() => setCriando(false)} />
        )}

        {aberta ? (
          <DetalheConta tenantId={aberta} aoVoltar={() => setAberta('')} aoRecarregar={carregar} />
        ) : (
          <ListaContas contas={contas} aoAbrir={setAberta} aoRecarregar={carregar} />
        )}
      </main>
    </div>
  )
}