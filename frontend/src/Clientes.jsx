import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Check,
  Download,
  Loader2,
  Pencil,
  Search,
  Trash2,
  Upload,
  Users,
  UserX,
  X,
} from 'lucide-react';

/**
 * Base de clientes do negócio: cadastro, edição, exclusão e importação de planilha.
 *
 * Fica em arquivo próprio porque é a tela mais pesada do painel e o `App.jsx`
 * já passou de 680 linhas somando tudo.
 *
 * Recebe o token e devolve o mesmo token para o pai, que recarrega os
 * agendamentos depois de criar um cliente novo.
 */
export default function Clientes({ token, aoMudar }) {
  const [clientes, setClientes] = useState([]);
  const [diasLimite, setDiasLimite] = useState(45);
  const [reativacaoAtiva, setReativacaoAtiva] = useState(false);

  const [busca, setBusca] = useState('');
  const [filtro, setFiltro] = useState('todos'); // todos | inativos | sem_historico | opt_out

  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState('');
  const [aviso, setAviso] = useState('');

  // Formulário
  const [editando, setEditando] = useState(null); // null = fechado, {} = novo
  const [form, setForm] = useState({ nome: '', telefone: '', ultima_visita: '', obs: '' });
  const [salvando, setSalvando] = useState(false);

  // Importação
  const [importando, setImportando] = useState(false);
  const [resultadoImport, setResultadoImport] = useState(null);
  const inputArquivo = useRef(null);

  // Recebe termo e filtro como argumento em vez de ler do estado: assim o
  // callback só depende do token, e o effect não recria a cada tecla digitada.
  const carregar = useCallback(
    async (termo, filtroAtivo) => {
      if (!token) return;
      setCarregando(true);
      setErro('');

      const params = new URLSearchParams({ limite: '500' });
      if (termo?.trim()) params.set('busca', termo.trim());
      if (filtroAtivo === 'inativos') params.set('inativos', 'true');
      if (filtroAtivo === 'sem_historico') params.set('sem_historico', 'true');

      try {
        const res = await fetch(`/api/clientes?${params}`, { headers: { 'X-LZ-Token': token } });
        if (!res.ok) throw new Error('Falha ao carregar clientes.');
        const dados = await res.json();
        setClientes(dados.clientes);
        setDiasLimite(dados.dias_sem_visitar);
        setReativacaoAtiva(dados.reativacao_ativa);
      } catch (e) {
        setErro(e.message);
      } finally {
        setCarregando(false);
      }
    },
    [token]
  );

  // Recarrega com o filtro e a busca do momento. Usado depois de gravar.
  const recarregar = useCallback(() => carregar(busca, filtro), [carregar, busca, filtro]);

  // Um effect só, com atraso só na busca: trocar o filtro responde a um clique e
  // precisa ser imediato; digitar nome espera a pessoa parar.
  useEffect(() => {
    const espera = busca ? 350 : 0;
    const t = setTimeout(() => carregar(busca, filtro), espera);
    return () => clearTimeout(t);
  }, [busca, filtro, carregar]);

  const abrirNovo = () => {
    setForm({ nome: '', telefone: '', ultima_visita: '', obs: '' });
    setEditando({});
    setErro('');
  };

  const abrirEdicao = (cliente) => {
    setForm({
      nome: cliente.nome,
      telefone: cliente.telefone,
      ultima_visita: cliente.ultima_visita ? cliente.ultima_visita.slice(0, 10) : '',
      obs: cliente.obs || '',
    });
    setEditando(cliente);
    setErro('');
  };

  const salvar = async (e) => {
    e.preventDefault();
    setSalvando(true);
    setErro('');

    const corpo = {
      nome: form.nome,
      telefone: form.telefone,
      obs: form.obs,
    };
    // Date local não pode ir vazio: enviar "" quebra o parse do backend.
    if (form.ultima_visita) corpo.ultima_visita = `${form.ultima_visita}T12:00:00`;

    try {
      const ehNovo = !editando.id;
      const res = await fetch(ehNovo ? '/api/clientes' : `/api/clientes/${editando.id}`, {
        method: ehNovo ? 'POST' : 'PUT',
        headers: { 'Content-Type': 'application/json', 'X-LZ-Token': token },
        body: JSON.stringify(corpo),
      });

      const dados = await res.json();
      if (!res.ok) throw new Error(dados.detail || 'Erro ao guardar o cliente.');

      setAviso(dados.mensagem || (ehNovo ? 'Cliente cadastrado.' : 'Cliente atualizado.'));
      setEditando(null);
      await recarregar();
      if (ehNovo && aoMudar) aoMudar();
    } catch (err) {
      setErro(err.message);
    } finally {
      setSalvando(false);
    }
  };

  const alternarOptOut = async (cliente) => {
    try {
      const res = await fetch(`/api/clientes/${cliente.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', 'X-LZ-Token': token },
        body: JSON.stringify({ opt_out: !cliente.opt_out }),
      });
      if (!res.ok) throw new Error('Erro ao alterar o opt-out.');
      setAviso(
        cliente.opt_out
          ? `${cliente.nome} voltou a receber mensagens.`
          : `${cliente.nome} não recebe mais mensagens.`
      );
      await recarregar();
    } catch (e) {
      setErro(e.message);
    }
  };

  const marcarVisitaHoje = async (cliente) => {
    try {
      const res = await fetch(`/api/clientes/${cliente.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', 'X-LZ-Token': token },
        body: JSON.stringify({ ultima_visita: new Date().toISOString().slice(0, 19) }),
      });
      if (!res.ok) throw new Error('Erro ao registar a visita.');
      setAviso(`Visita de ${cliente.nome} registada. Saiu da lista de inativos.`);
      await recarregar();
    } catch (e) {
      setErro(e.message);
    }
  };

  const remover = async (cliente) => {
    if (!window.confirm(`Remover ${cliente.nome} da base? O histórico de agendamentos é mantido.`)) return;
    try {
      const res = await fetch(`/api/clientes/${cliente.id}`, {
        method: 'DELETE',
        headers: { 'X-LZ-Token': token },
      });
      if (!res.ok) throw new Error('Erro ao remover o cliente.');
      setAviso(`${cliente.nome} foi removido.`);
      await recarregar();
    } catch (e) {
      setErro(e.message);
    }
  };

  const importar = async (evento) => {
    const arquivo = evento.target.files?.[0];
    if (!arquivo) return;

    setImportando(true);
    setErro('');
    setResultadoImport(null);

    const dadosForm = new FormData();
    dadosForm.append('arquivo', arquivo);

    try {
      const res = await fetch('/api/clientes/importar', {
        method: 'POST',
        headers: { 'X-LZ-Token': token },
        body: dadosForm,
      });
      const dados = await res.json();
      if (!res.ok) throw new Error(dados.detail || 'Falha na importação.');
      setResultadoImport(dados);
      await recarregar();
    } catch (e) {
      setErro(e.message);
    } finally {
      setImportando(false);
      if (inputArquivo.current) inputArquivo.current.value = '';
    }
  };

  // O BOM (\uFEFF) é obrigatório: sem ele o Excel abre o CSV como ISO-8859-1 e
// "Ana Lúcia" vira "Ana LÃºcia". Escrito como escape porque o caractere
// literal é comum passe-lint pegando irregular-whitespace.
const BOM = '\uFEFF';

const baixarModelo = () => {
    const conteudo =
      'Nome do Cliente;Celular;Última Visita;Observação\n' +
      'Carlos Silva;11 99999-8888;01/09/2026;Prefere barbear de manhã\n' +
      'Ana Souza;(11) 98888-7777;15/08/2026;Cliente VIP\n';
    const blob = new Blob([BOM + conteudo], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'modelo-clientes-lembrazap.csv';
    link.click();
    URL.revokeObjectURL(url);
  };

  const contagens = {
    total: clientes.length,
    inativos: clientes.filter((c) => c.inativo).length,
    sem_historico: clientes.filter((c) => c.sem_historico).length,
    opt_out: clientes.filter((c) => c.opt_out).length,
  };

  const FILTROS = [
    ['todos', 'Todos'],
    ['inativos', `Inativos (${diasLimite}d)`],
    ['sem_historico', 'Sem histórico'],
    ['opt_out', 'Não recebem'],
  ];

  return (
    <div className="config-section">
      <h2>
        <Users size={18} color="#10b981" />
        Base de Clientes
      </h2>

      <div className="dash-grid" style={{ marginBottom: '20px' }}>
        <div className="dash-card">
          <h3>Clientes</h3>
          <div className="value">{contagens.total}</div>
        </div>
        <div className="dash-card">
          <h3>Sumidos há {diasLimite}+ dias</h3>
          <div className="value" style={{ color: contagens.inativos ? '#fbbf24' : undefined }}>
            {contagens.inativos}
          </div>
        </div>
        <div className="dash-card">
          <h3>Sem histórico</h3>
          <div className="value" style={{ color: contagens.sem_historico ? '#94a3b8' : undefined }}>
            {contagens.sem_historico}
          </div>
        </div>
        <div className="dash-card">
          <h3>Reativação</h3>
          <div className="value" style={{ fontSize: '15px', color: reativacaoAtiva ? '#34d399' : '#64748b' }}>
            {reativacaoAtiva ? 'Ligada' : 'Desligada'}
          </div>
        </div>
      </div>

      {erro && (
        <div className="lz-alert-erro">
          {erro}
          <button type="button" onClick={() => setErro('')} className="lz-alert-x" aria-label="Fechar">
            <X size={14} />
          </button>
        </div>
      )}

      {aviso && (
        <div className="lz-alert-ok">
          <Check size={14} /> {aviso}
        </div>
      )}

      {/* Importação de planilha */}
      <div className="lz-import-box">
        <div className="lz-import-acoes">
          <input
            ref={inputArquivo}
            type="file"
            accept=".csv,text/csv"
            onChange={importar}
            style={{ display: 'none' }}
          />
          <button
            type="button"
            onClick={() => inputArquivo.current?.click()}
            disabled={importando}
            className="lz-btn lz-btn-secundario"
          >
            {importando ? <Loader2 size={16} className="spin" /> : <Upload size={16} />}
            Importar planilha CSV
          </button>
          <button type="button" onClick={baixarModelo} className="lz-btn lz-btn-secundario">
            <Download size={16} />
            Baixar modelo
          </button>
          <button type="button" onClick={abrirNovo} className="lz-btn">
            <Users size={16} />
            Novo cliente
          </button>
        </div>
        <p className="lz-import-dica">
          O separador <code>;</code> é detectado automaticamente. Colunas reconhecidas: nome, celular,
          última visita e observação. Telefone com DDD e 9 dígitos; fixo não entra.
        </p>

        {resultadoImport && (
          <div className="lz-import-resultado">
            <strong>{resultadoImport.mensagem}</strong>
            {resultadoImport.problemas?.length > 0 && (
              <ul>
                {resultadoImport.problemas.map((p, i) => (
                  <li key={i}>{p}</li>
                ))}
              </ul>
            )}
            <button type="button" className="lz-link" onClick={() => setResultadoImport(null)}>
              fechar
            </button>
          </div>
        )}
      </div>

      {/* Filtros */}
      <div className="lz-filtros">
        <div className="lz-busca">
          <Search size={15} />
          <input
            type="text"
            placeholder="Buscar por nome ou telefone"
            value={busca}
            onChange={(e) => setBusca(e.target.value)}
          />
        </div>
        {FILTROS.map(([chave, label]) => (
          <button
            key={chave}
            type="button"
            onClick={() => setFiltro(chave)}
            className={`lz-chip ${filtro === chave ? 'ativo' : ''}`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Formulário */}
      {editando && (
        <form onSubmit={salvar} className="lz-form-cliente">
          <div className="form-grid-2">
            <div>
              <label className="lz-label">Nome</label>
              <input
                type="text"
                required
                className="lz-input"
                value={form.nome}
                onChange={(e) => setForm({ ...form, nome: e.target.value })}
              />
            </div>
            <div>
              <label className="lz-label">Telefone (WhatsApp)</label>
              <input
                type="text"
                required
                placeholder="11 99999-8888"
                className="lz-input"
                value={form.telefone}
                onChange={(e) => setForm({ ...form, telefone: e.target.value })}
              />
            </div>
          </div>
          <div className="form-grid-2">
            <div>
              <label className="lz-label">Última visita</label>
              <input
                type="date"
                className="lz-input"
                value={form.ultima_visita}
                onChange={(e) => setForm({ ...form, ultima_visita: e.target.value })}
              />
            </div>
            <div>
              <label className="lz-label">Observação</label>
              <input
                type="text"
                className="lz-input"
                value={form.obs}
                onChange={(e) => setForm({ ...form, obs: e.target.value })}
              />
            </div>
          </div>
          <div className="lz-form-acoes">
            <button type="submit" disabled={salvando} className="lz-btn">
              {salvando ? <Loader2 size={16} className="spin" /> : <Check size={16} />}
              Guardar
            </button>
            <button type="button" onClick={() => setEditando(null)} className="lz-btn lz-btn-secundario">
              Cancelar
            </button>
          </div>
        </form>
      )}

      {/* Lista */}
      {carregando && clientes.length === 0 ? (
        <div className="lz-vazio">
          <Loader2 size={20} className="spin" /> A carregar clientes…
        </div>
      ) : clientes.length === 0 ? (
        <div className="lz-vazio">
          {busca || filtro !== 'todos' ? (
            <>Nenhum cliente encontrado neste filtro.</>
          ) : (
            <>
              <Users size={22} />
              <p>Sua base está vazia. Cadastre um cliente ou importe a planilha da sua agenda.</p>
            </>
          )}
        </div>
      ) : (
        <div className="lz-table-container">
          <table className="lz-table">
            <thead>
              <tr>
                <th>Cliente</th>
                <th>Telefone</th>
                <th>Última visita</th>
                <th>Situação</th>
                <th style={{ textAlign: 'right' }}>Ações</th>
              </tr>
            </thead>
            <tbody>
              {clientes
                .filter((c) => (filtro === 'opt_out' ? c.opt_out : true))
                .map((c) => (
                  <tr key={c.id}>
                    <td>
                      <div>{c.nome}</div>
                      {c.obs && <small className="lz-sub">{c.obs}</small>}
                    </td>
                    <td>{c.telefone_formatado}</td>
                    <td>
                      {c.ultima_visita ? (
                        <>
                          <div>{c.ultima_visita}</div>
                          <small className="lz-sub">há {c.dias_sem_visitar} dias</small>
                        </>
                      ) : (
                        <span className="lz-sub">nunca registada</span>
                      )}
                    </td>
                    <td>
                      {c.opt_out ? (
                        <span className="lz-badge lz-badge-optout">
                          <UserX size={12} /> não recebe
                        </span>
                      ) : c.inativo ? (
                        <span className="lz-badge lz-badge-inativo">sumido {c.dias_sem_visitar}d</span>
                      ) : c.sem_historico ? (
                        <span className="lz-badge">sem histórico</span>
                      ) : (
                        <span className="lz-badge lz-badge-ativo">em dia</span>
                      )}
                    </td>
                    <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                      {!c.opt_out && (
                        <button
                          type="button"
                          title="Registar visita hoje"
                          onClick={() => marcarVisitaHoje(c)}
                          className="lz-acao"
                        >
                          <Check size={15} />
                        </button>
                      )}
                      <button type="button" title="Editar" onClick={() => abrirEdicao(c)} className="lz-acao">
                        <Pencil size={15} />
                      </button>
                      <button
                        type="button"
                        title={c.opt_out ? 'Voltar a receber mensagens' : 'Não enviar mais mensagens'}
                        onClick={() => alternarOptOut(c)}
                        className="lz-acao"
                      >
                        <UserX size={15} />
                      </button>
                      <button type="button" title="Remover" onClick={() => remover(c)} className="lz-acao lz-acao-perigo">
                        <Trash2 size={15} />
                      </button>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}