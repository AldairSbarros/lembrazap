import { useState, useEffect } from 'react';
import { Store, ArrowRight, QrCode, CheckCircle2, Loader2, Clock, Save, LogOut, Calendar, Plus, UserCheck } from 'lucide-react';
import Clientes from './Clientes';

const TEMPLATES_POR_NICHO = {
  barbearia: {
    label: "Barbearia 💈",
    texto: "Fala {nome}, beleza? Passando pra lembrar do seu horário marcado na {negocio} para {servico} no dia {data} às {horario}.\n\nResponda SIM para confirmar ou ADIAR para reagendar."
  },
  salao: {
    label: "Salão / Manicure / Estética 💅",
    texto: "Oi {nome}, tudo bem? ✨ Seu momento de cuidado na {negocio} para {servico} está marcado para {data} às {horario}.\n\nPor favor, responda SIM para garantir sua vaga ou ADIAR caso precise remarcar."
  },
  petshop: {
    label: "Petshop / Banho e Tosa 🐾",
    texto: "Olá {nome}! 🐾 Lembrança da {negocio}: o horário do seu pet para {servico} está agendado para {data} às {horario}.\n\nPodemos confirmar? Responda SIM para confirmar ou ADIAR para reagendar."
  },
  boutique: {
    label: "Boutique / Moda 👗",
    texto: "Olá {nome}! Seu atendimento exclusivo na {negocio} para {servico} está marcado para {data} às {horario}.\n\nConfirma sua visita? Responda SIM para confirmar ou ADIAR para agendar outra data."
  },
  geral: {
    label: "Geral / Outros Negócios 📌",
    texto: "Olá {nome}! Lembramos do seu agendamento de {servico} na {negocio} no dia {data} às {horario}.\n\nResponda SIM para confirmar ou ADIAR para remarcar."
  }
};

export default function App() {
  const [nome, setNome] = useState('');
  const [etapa, setEtapa] = useState('registro');
  const [tokenAuth, setTokenAuth] = useState('');
  const [qrCodeBase64, setQrCodeBase64] = useState('');
  const [erro, setErro] = useState('');
  
  // Configurações
  const [nichoSelecionado, setNichoSelecionado] = useState('barbearia');
  const [tempoAntecedencia, setTempoAntecedencia] = useState('24');
  const [mensagemModelo, setMensagemModelo] = useState(TEMPLATES_POR_NICHO.barbearia.texto);
  const [salvoFeedback, setSalvoFeedback] = useState(false);

  // Reativação de cliente inativo
  const [diasSemVisitar, setDiasSemVisitar] = useState('45');
  const [reativacaoAtiva, setReativacaoAtiva] = useState(false);
  const [limitePorDia, setLimitePorDia] = useState('50');
  const [mensagemReativacao, setMensagemReativacao] = useState('');
  const [enviosPausados, setEnviosPausados] = useState(false);
  const [avisosConfig, setAvisosConfig] = useState([]);

  // Gestão de Agendamentos
  const [agendamentos, setAgendamentos] = useState([]);
  const [novoCliente, setNovoCliente] = useState('');
  const [novoTelefone, setNovoTelefone] = useState('');
  const [novoServico, setNovoServico] = useState('');
  const [novaDataHora, setNovaDataHora] = useState('');
  const [cadastrando, setCadastrando] = useState(false);

  const carregarAgendamentos = async (token) => {
    try {
      const res = await fetch('/api/agendamentos', {
        headers: { 'X-LZ-Token': token || tokenAuth }
      });
      if (res.ok) {
        const dados = await res.json();
        setAgendamentos(dados);
      }
    } catch (e) {
      console.error("Erro ao carregar agendamentos", e);
    }
  };

  const trocarNicho = (novoNicho) => {
    setNichoSelecionado(novoNicho);
    setMensagemModelo(TEMPLATES_POR_NICHO[novoNicho].texto);
  };

  const iniciarSistema = async (e) => {
    e.preventDefault();
    setErro('');
    setEtapa('carregando');

    try {
      const resConta = await fetch('/api/contas', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nome, negocio: nome })
      });
      const dadosConta = await resConta.json();
      if (!dadosConta.ok) throw new Error("Falha ao criar conta");
      
      const token = dadosConta.token;
      setTokenAuth(token);

      const resInstancia = await fetch('/api/conexao/criar', {
        method: 'POST',
        headers: { 'X-LZ-Token': token }
      });
      const dadosInstancia = await resInstancia.json();
      if (!dadosInstancia.ok) throw new Error("Falha ao criar instância");

      const resQr = await fetch('/api/conexao/qrcode', {
        method: 'GET',
        headers: { 'X-LZ-Token': token }
      });
      const dadosQr = await resQr.json();
      
      const rawBase64 = dadosQr.base64 || dadosQr.qrcode || '';
      const formattedQr = rawBase64.startsWith('data:image') 
        ? rawBase64 
        : `data:image/png;base64,${rawBase64}`;

      setQrCodeBase64(formattedQr);
      setEtapa('qrcode');
    } catch (err) {
      setErro(err.message);
      setEtapa('registro');
    }
  };

  const carregarConfiguracoes = async (token) => {
    try {
      const res = await fetch('/api/configuracoes', { headers: { 'X-LZ-Token': token } });
      if (!res.ok) return;
      const d = await res.json();
      setTempoAntecedencia(String(d.horas_antecedencia));
      setDiasSemVisitar(String(d.dias_sem_visitar));
      setReativacaoAtiva(d.reativacao_ativa);
      setLimitePorDia(String(d.limite_por_dia));
      setEnviosPausados(d.envios_pausados);
      if (d.mensagem_lembrete) setMensagemModelo(d.mensagem_lembrete);
      if (d.mensagem_reativacao) setMensagemReativacao(d.mensagem_reativacao);
    } catch (e) {
      console.error("Erro ao carregar configurações", e);
    }
  };

  // Carrega os dados ao entrar no painel. Precisa ficar depois das funções que
  // chama: um effect acima delas usaria uma variável ainda não inicializada.
  // Buscar no effect é o padrão do React para dado de servidor — o setState
  // acontece depois do await, nunca no corpo do effect.
  useEffect(() => {
    if (etapa !== 'dashboard' || !tokenAuth) return;
    /* eslint-disable react-hooks/set-state-in-effect */
    carregarAgendamentos(tokenAuth);
    carregarConfiguracoes(tokenAuth);
    /* eslint-enable react-hooks/set-state-in-effect */
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [etapa, tokenAuth]);

  // Depois das funções: o effect as usa, e declarar antes quebraria a ordem.
  const salvarConfiguracoes = async (e) => {
    e.preventDefault();
    setSalvoFeedback(false);
    setAvisosConfig([]);

    try {
      const res = await fetch('/api/configuracoes', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-LZ-Token': tokenAuth
        },
        body: JSON.stringify({
          horas_antecedencia: parseInt(tempoAntecedencia, 10) || 24,
          mensagem_lembrete: mensagemModelo,
          dias_sem_visitar: parseInt(diasSemVisitar, 10) || 45,
          reativacao_ativa: reativacaoAtiva,
          limite_por_dia: parseInt(limitePorDia, 10) || 50,
          mensagem_reativacao: mensagemReativacao,
          envios_pausados: enviosPausados
        })
      });

      const dados = await res.json();
      if (!res.ok) throw new Error(dados.detail || "Erro ao guardar configurações.");

      // O backend devolve o que foi removido do texto: placeholder digitado
      // errado é avisado aqui, não descoberto quando a mensagem chega.
      setAvisosConfig(dados.avisos || []);
      setSalvoFeedback(true);
      setTimeout(() => setSalvoFeedback(false), 3000);
    } catch (err) {
      setErro(err.message || "Erro ao comunicar com o servidor para guardar configurações.");
    }
  };

  const adicionarAgendamento = async (e) => {
    e.preventDefault();
    setCadastrando(true);
    setErro('');

    try {
      if (!novaDataHora) {
        alert("Por favor, selecione a data e o horário.");
        setCadastrando(false);
        return;
      }

      const res = await fetch('/api/agendamentos', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-LZ-Token': tokenAuth
        },
        body: JSON.stringify({
          nome: novoCliente,
          telefone: novoTelefone,
          servico: novoServico,
          quando: new Date(novaDataHora).toISOString()
        })
      });

      const dados = await res.json();

      if (!res.ok) {
        throw new Error(dados.detail || "Erro ao gravar na base de dados");
      }

      // Limpa os campos após o sucesso
      setNovoCliente('');
      setNovoTelefone('');
      setNovoServico('');
      setNovaDataHora('');

      // Recarrega a tabela de agendamentos
      await carregarAgendamentos(tokenAuth);
      alert("Agendamento marcado com sucesso!");

    } catch (err) {
      console.error("Erro ao adicionar agendamento:", err);
      alert("Falha ao agendar: " + err.message);
    } finally {
      setCadastrando(false);
    }
  };
  
  const getStatusBadge = (status) => {
    switch (status) {
      case 'confirmado':
        return <span style={{ color: '#34d399', background: 'rgba(52, 211, 153, 0.1)', padding: '4px 10px', borderRadius: '12px', fontSize: '12px', fontWeight: 600 }}>Confirmado</span>;
      case 'reagendando':
        return <span style={{ color: '#fbbf24', background: 'rgba(251, 191, 36, 0.1)', padding: '4px 10px', borderRadius: '12px', fontSize: '12px', fontWeight: 600 }}>A Reagendar</span>;
      case 'enviado':
        return <span style={{ color: '#60a5fa', background: 'rgba(96, 165, 250, 0.1)', padding: '4px 10px', borderRadius: '12px', fontSize: '12px', fontWeight: 600 }}>Enviado</span>;
      default:
        return <span style={{ color: '#94a3b8', background: 'rgba(148, 163, 184, 0.1)', padding: '4px 10px', borderRadius: '12px', fontSize: '12px', fontWeight: 600 }}>Pendente</span>;
    }
  };

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
        
        .lz-wrapper {
          position: fixed;
          inset: 0;
          background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
          display: flex;
          align-items: center;
          justify-content: center;
          font-family: 'Inter', sans-serif;
          padding: 20px;
          overflow-y: auto;
        }

        .lz-card {
          width: 100%;
          max-width: ${etapa === 'dashboard' ? '920px' : '440px'};
          background: #1e293b;
          border: 1px solid #334155;
          border-radius: 24px;
          box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
          overflow: hidden;
          color: #f8fafc;
          transition: max-width 0.3s ease;
          margin: auto;
        }

        .lz-header {
          background: linear-gradient(135deg, #059669 0%, #047857 100%);
          padding: 32px 24px;
          text-align: center;
        }

        .lz-icon-box {
          margin: 0 auto 16px auto;
          background: rgba(255, 255, 255, 0.15);
          width: 64px;
          height: 64px;
          border-radius: 16px;
          display: flex;
          align-items: center;
          justify-content: center;
          backdrop-filter: blur(8px);
          border: 1px solid rgba(255, 255, 255, 0.2);
        }

        .lz-header h1 {
          font-size: 26px;
          font-weight: 700;
          letter-spacing: -0.5px;
          color: #ffffff;
          margin: 0;
        }

        .lz-header p {
          color: #d1fae5;
          font-size: 14px;
          margin-top: 6px;
          font-weight: 500;
        }

        .lz-body {
          padding: 32px;
        }

        .lz-error {
          margin-bottom: 24px;
          padding: 14px 16px;
          background: rgba(239, 68, 68, 0.1);
          color: #f87171;
          border-radius: 12px;
          font-size: 14px;
          border: 1px solid rgba(239, 68, 68, 0.2);
        }

        .lz-label {
          display: block;
          font-size: 13px;
          font-weight: 600;
          color: #94a3b8;
          margin-bottom: 8px;
          text-transform: uppercase;
          letter-spacing: 0.5px;
        }

        .lz-input, .lz-select, .lz-textarea {
          width: 100%;
          padding: 12px 16px;
          border-radius: 12px;
          background: #0f172a;
          border: 1px solid #334155;
          color: #ffffff;
          font-size: 14px;
          outline: none;
          transition: all 0.2s;
          margin-bottom: 16px;
          box-sizing: border-box;
          font-family: 'Inter', sans-serif;
        }

        .lz-input:focus, .lz-select:focus, .lz-textarea:focus {
          border-color: #10b981;
          box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.2);
        }

        .lz-textarea {
          resize: vertical;
          min-height: 100px;
        }

        .lz-btn {
          width: 100%;
          background: #10b981;
          color: #0f172a;
          font-weight: 700;
          padding: 12px 16px;
          border-radius: 12px;
          border: none;
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 10px;
          font-size: 15px;
          transition: all 0.2s;
        }

        .lz-btn:hover {
          background: #34d399;
        }

        .lz-tags-help {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
          margin-top: -8px;
          margin-bottom: 16px;
        }

        .lz-tag-pill {
          background: #0f172a;
          border: 1px solid #334155;
          color: #10b981;
          font-size: 11px;
          padding: 2px 8px;
          border-radius: 6px;
          font-family: monospace;
        }

        .dash-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
          gap: 16px;
          margin-bottom: 24px;
        }

        .dash-card {
          background: #0f172a;
          border: 1px solid #334155;
          padding: 20px;
          border-radius: 16px;
        }

        .dash-card h3 {
          font-size: 13px;
          color: #94a3b8;
          text-transform: uppercase;
          letter-spacing: 0.5px;
          margin-bottom: 8px;
        }

        .dash-card .value {
          font-size: 24px;
          font-weight: 700;
          color: #ffffff;
        }

        .config-section {
          background: #0f172a;
          border: 1px solid #334155;
          padding: 24px;
          border-radius: 16px;
          margin-bottom: 24px;
        }

        .config-section h2 {
          font-size: 16px;
          font-weight: 600;
          color: #ffffff;
          margin-bottom: 16px;
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .form-grid-2 {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 12px;
        }

        .lz-table-container {
          overflow-x: auto;
        }

        .lz-table {
          width: 100%;
          border-collapse: collapse;
          text-align: left;
          font-size: 14px;
        }

        .lz-table th {
          background: #1e293b;
          color: #94a3b8;
          padding: 12px;
          font-weight: 600;
          border-bottom: 1px solid #334155;
        }

        .lz-table td {
          padding: 12px;
          border-bottom: 1px solid #334155;
          color: #f1f5f9;
        }

        .spin {
          animation: spin 1s linear infinite;
        }

        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>

      <div className="lz-wrapper">
        <div className="lz-card">
          <div className="lz-header">
            <div className="lz-icon-box">
              <Store size={32} color="#ffffff" />
            </div>
            <h1>{nome || 'LembraZap'}</h1>
            <p>Painel de Gestão e Automação de Agendamentos</p>
          </div>

          <div className="lz-body">
            {erro && <div className="lz-error">{erro}</div>}

            {etapa === 'registro' && (
              <form onSubmit={iniciarSistema}>
                <label className="lz-label">Nome do seu Negócio</label>
                <input
                  type="text"
                  required
                  value={nome}
                  onChange={(e) => setNome(e.target.value)}
                  placeholder="Ex: Barbearia Vip..."
                  className="lz-input"
                />
                <button type="submit" className="lz-btn">
                  Configurar WhatsApp
                  <ArrowRight size={18} />
                </button>
              </form>
            )}

            {etapa === 'carregando' && (
              <div style={{ textAlign: 'center', padding: '30px 0' }}>
                <Loader2 size={42} color="#10b981" className="spin" style={{ margin: '0 auto' }} />
                <p style={{ marginTop: '16px', color: '#94a3b8' }}>A preparar infraestrutura...</p>
              </div>
            )}

            {etapa === 'qrcode' && (
              <div style={{ textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                <div style={{ background: 'rgba(16, 185, 129, 0.1)', color: '#34d399', padding: '8px 16px', borderRadius: '9999px', fontSize: '13px', fontWeight: 600, display: 'flex', gap: '8px', marginBottom: '20px' }}>
                  <CheckCircle2 size={16} /> Instância criada com sucesso
                </div>
                <div style={{ background: '#ffffff', padding: '16px', borderRadius: '16px', marginBottom: '20px' }}>
                  {qrCodeBase64 ? (
                    <img src={qrCodeBase64} alt="QR Code WhatsApp" style={{ width: '220px', height: '220px', display: 'block' }} />
                  ) : (
                    <div style={{ width: '220px', height: '220px', background: '#f8fafc', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                      <QrCode size={40} color="#cbd5e1" />
                    </div>
                  )}
                </div>
                <button onClick={() => setEtapa('dashboard')} className="lz-btn">
                  Entrar no Painel
                  <ArrowRight size={18} />
                </button>
              </div>
            )}

            {etapa === 'dashboard' && (
              <div>
                <div className="dash-grid">
                  <div className="dash-card">
                    <h3>Estado do WhatsApp</h3>
                    <div className="value" style={{ color: '#34d399', fontSize: '18px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span style={{ width: '10px', height: '10px', borderRadius: '50%', background: '#34d399', display: 'inline-block' }}></span>
                      Conectado
                    </div>
                  </div>
                  <div className="dash-card">
                    <h3>Total de Agendamentos</h3>
                    <div className="value">{agendamentos.length}</div>
                  </div>
                  <div className="dash-card">
                    <h3>Confirmados</h3>
                    <div className="value" style={{ color: '#34d399' }}>
                      {agendamentos.filter(a => a.status === 'confirmado').length}
                    </div>
                  </div>
                </div>

                {/* Secção de Novo Agendamento */}
                <div className="config-section">
                  <h2>
                    <Plus size={18} color="#10b981" />
                    Novo Agendamento
                  </h2>
                  <form onSubmit={adicionarAgendamento}>
                    <div className="form-grid-2">
                      <div>
                        <label className="lz-label">Nome do Cliente</label>
                        <input
                          type="text"
                          required
                          placeholder="Ex: Carlos Silva"
                          value={novoCliente}
                          onChange={(e) => setNovoCliente(e.target.value)}
                          className="lz-input"
                        />
                      </div>
                      <div>
                        <label className="lz-label">Telefone (WhatsApp)</label>
                        <input
                          type="text"
                          required
                          placeholder="Ex: 5592999998888"
                          value={novoTelefone}
                          onChange={(e) => setNovoTelefone(e.target.value)}
                          className="lz-input"
                        />
                      </div>
                    </div>

                    <div className="form-grid-2">
                      <div>
                        <label className="lz-label">Serviço</label>
                        <input
                          type="text"
                          required
                          placeholder="Ex: Corte de Cabelo"
                          value={novoServico}
                          onChange={(e) => setNovoServico(e.target.value)}
                          className="lz-input"
                        />
                      </div>
                      <div>
                        <label className="lz-label">Data e Horário</label>
                        <input
                          type="datetime-local"
                          required
                          value={novaDataHora}
                          onChange={(e) => setNovaDataHora(e.target.value)}
                          className="lz-input"
                        />
                      </div>
                    </div>

                    <button type="submit" disabled={cadastrando} className="lz-btn">
                      {cadastrando ? <Loader2 size={16} className="spin" /> : <Calendar size={16} />}
                      Marcar Agendamento
                    </button>
                  </form>
                </div>

                {/* Tabela de Agendamentos */}
                <div className="config-section">
                  <h2>
                    <Calendar size={18} color="#10b981" />
                    Lista de Agendamentos
                  </h2>
                  <div className="lz-table-container">
                    <table className="lz-table">
                      <thead>
                        <tr>
                          <th>Cliente</th>
                          <th>Telefone</th>
                          <th>Serviço</th>
                          <th>Data / Hora</th>
                          <th>Estado</th>
                        </tr>
                      </thead>
                      <tbody>
                        {agendamentos.length === 0 ? (
                          <tr>
                            <td colSpan="5" style={{ textAlign: 'center', color: '#64748b', padding: '24px' }}>
                              Nenhum agendamento registado ainda.
                            </td>
                          </tr>
                        ) : (
                          agendamentos.map((item) => (
                            <tr key={item.id}>
                              <td>{item.nome}</td>
                              <td>{item.telefone}</td>
                              <td>{item.servico}</td>
                              <td>{item.quando}</td>
                              <td>{getStatusBadge(item.status)}</td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Base de Clientes */}
                <Clientes token={tokenAuth} aoMudar={() => carregarAgendamentos(tokenAuth)} />

                {/* Regras de Disparo Automático */}
                <form onSubmit={salvarConfiguracoes}>
                <div className="config-section">
                  <h2>
                    <Clock size={18} color="#10b981" />
                    Regras de Disparo Automático
                  </h2>

                  {enviosPausados && (
                    <div className="lz-alert-aviso">
                      Envios automáticos estão <strong>pausados</strong>. Nenhuma mensagem vai sair até
                      você desmarcar abaixo.
                    </div>
                  )}

                  <label className="lz-label lz-label-toggle">
                    <input
                      type="checkbox"
                      checked={enviosPausados}
                      onChange={(e) => setEnviosPausados(e.target.checked)}
                    />
                    Pausar todos os envios automáticos
                  </label>

                  <h3 className="lz-subtitulo">
                    <Clock size={15} /> Campanha 1 — Lembrete de consulta marcada
                  </h3>

                  <label className="lz-label">Tipo de Negócio (Tom de Voz)</label>
                  <select
                    value={nichoSelecionado}
                    onChange={(e) => trocarNicho(e.target.value)}
                    className="lz-select"
                  >
                    {Object.entries(TEMPLATES_POR_NICHO).map(([chave, item]) => (
                      <option key={chave} value={chave}>{item.label}</option>
                    ))}
                  </select>

                  <label className="lz-label">Avisar quantas horas antes</label>
                  <input
                    type="number"
                    min="1"
                    max="720"
                    value={tempoAntecedencia}
                    onChange={(e) => setTempoAntecedencia(e.target.value)}
                    className="lz-input"
                  />

                  <label className="lz-label">Texto do lembrete</label>
                  <textarea
                    value={mensagemModelo}
                    onChange={(e) => setMensagemModelo(e.target.value)}
                    className="lz-textarea"
                  />

                  <div className="lz-tags-help">
                    <span className="lz-tag-pill">{'{nome}'}</span>
                    <span className="lz-tag-pill">{'{negocio}'}</span>
                    <span className="lz-tag-pill">{'{servico}'}</span>
                    <span className="lz-tag-pill">{'{data}'}</span>
                    <span className="lz-tag-pill">{'{horario}'}</span>
                  </div>

                  <h3 className="lz-subtitulo">
                    <UserCheck size={15} /> Campanha 2 — Reativação de cliente sumido
                  </h3>

                  <label className="lz-label lz-label-toggle">
                    <input
                      type="checkbox"
                      checked={reativacaoAtiva}
                      onChange={(e) => setReativacaoAtiva(e.target.checked)}
                    />
                    Ligar a reativação de clientes que não vêm há um tempo
                  </label>

                  <div className="form-grid-2">
                    <div>
                      <label className="lz-label">Dias sem visitar para receber</label>
                      <input
                        type="number"
                        min="7"
                        max="365"
                        value={diasSemVisitar}
                        onChange={(e) => setDiasSemVisitar(e.target.value)}
                        className="lz-input"
                      />
                    </div>
                    <div>
                      <label className="lz-label">Máximo por dia</label>
                      <input
                        type="number"
                        min="1"
                        max="500"
                        value={limitePorDia}
                        onChange={(e) => setLimitePorDia(e.target.value)}
                        className="lz-input"
                      />
                    </div>
                  </div>

                  <label className="lz-label">
                    Texto da reativação — este é o que vai com o nome do cliente
                  </label>
                  <textarea
                    value={mensagemReativacao}
                    placeholder="Deixe vazio para usar o texto padrão. Ex.: Fala {nome}, faz {dias} dias que não te vemos na {negocio}! Passa aqui."
                    onChange={(e) => setMensagemReativacao(e.target.value)}
                    className="lz-textarea"
                  />

                  <div className="lz-tags-help">
                    <span className="lz-tag-pill">{'{nome}'}</span>
                    <span className="lz-tag-pill">{'{dias}'}</span>
                    <span className="lz-tag-pill">{'{negocio}'}</span>
                    <span className="lz-tag-pill">{'{telefone}'}</span>
                  </div>

                  {avisosConfig.length > 0 && (
                    <div className="lz-alert-aviso">
                      <ul style={{ margin: 0, paddingLeft: '18px' }}>
                        {avisosConfig.map((a, i) => <li key={i}>{a}</li>)}
                      </ul>
                    </div>
                  )}

                  {salvoFeedback && (
                    <div style={{ color: '#34d399', fontSize: '13px', marginBottom: '16px', fontWeight: 600 }}>
                      ✓ Configurações guardadas e sincronizadas!
                    </div>
                  )}

                  <button type="submit" className="lz-btn">
                    <Save size={18} /> Guardar Alterações
                  </button>
                </div>
                </form>

                <button onClick={() => setEtapa('registro')} className="lz-btn" style={{ background: '#334155', color: '#f8fafc' }}>
                  <LogOut size={18} /> Desconectar / Alterar Negócio
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}