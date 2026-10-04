# LembraZap

Micro-SaaS de **lembretes e remarketing por WhatsApp** para negócios locais —
barbearias, salões, clínicas, oficinas, estúdios.

Cada conta conecta o **próprio número** de WhatsApp via QR Code, numa instância
isolada da Evolution API. O sistema avisa o cliente antes do horário e registra a
resposta (`SIM` confirma, `ADIAR` entra em remarcação).

---

## Documentação

| Documento | Para quê |
|---|---|
| [docs/MANUAL-USUARIO.md](docs/MANUAL-USUARIO.md) | **Comece aqui se você é o dono do negócio.** Passo a passo sem código. |
| [docs/INSTALACAO.md](docs/INSTALACAO.md) | Instalar, rodar local e publicar na VPS. |
| [docs/API.md](docs/API.md) | Referência de todas as rotas, com exemplos de `curl`. |
| [docs/ERROS.md](docs/ERROS.md) | Diagnóstico: sintomas, causas e soluções. |
| [docs/ARQUITETURA.md](docs/ARQUITETURA.md) | Como o sistema é montado por dentro. |

**Swagger interativo:** com o backend no ar, em
<http://localhost:8000/docs> (UI) e <http://localhost:8000/redoc> (leitura).

---

## Subir o sistema

Pré-requisitos: **Docker Desktop** e **Node.js 20+**.

```bash
cp .env.example .env      # ajuste EVOLUTION_API_URL e EVOLUTION_API_KEY
docker compose up -d --build
```

Isso sobe quatro serviços:

| Serviço | Porta | Função |
|---|---|---|
| `backend` | 8000 | API FastAPI + Swagger |
| `worker` | — | Celery: envia mensagens e agenda lembretes (beat a cada 10 min) |
| `db` | 5432 | PostgreSQL 15 |
| `redis` | 6379 | Fila do Celery |

O frontend é separado (Vite, porta 5173):

```bash
cd frontend
npm install
npm run dev
```

Conferir se está tudo de pé:

```bash
docker compose ps                        # todos devem estar healthy/up
curl http://localhost:8000/healthz       # {"status":"ok", ...}
```

---

## Como funciona, em 6 passos

```
1. POST /api/contas          cria a conta e devolve o token (uma única vez)
2. POST /api/conexao/criar   cria a instância na Evolution + registra o webhook
3. GET  /api/conexao/qrcode  você escaneia e pareia o seu WhatsApp
4. POST /api/configuracoes   antecedência do lembrete e texto da mensagem
5. POST /api/agendamentos    marca um horário
6. o worker manda            na janela de antecedência, e a resposta volta via webhook
```

**Detalhe que costuma travar:** o passo 6 depende do webhook, que precisa de URL
pública. Ver [docs/ERROS.md](docs/ERROS.md#o-webhook-não-chega).

---

## Variáveis de ambiente

| Variável | Obrigatória | Efeito |
|---|---|---|
| `EVOLUTION_API_URL` | sim | Endereço da Evolution API (ex.: `http://216.22.5.199:8080`) |
| `EVOLUTION_API_KEY` | sim | Chave `apikey` da Evolution |
| `MODO_SIMULACAO` | não | `1` = nenhum HTTP externo (QR fictício, nada é enviado). Padrão: ligado se a URL estiver vazia |
| `WEBHOOK_PUBLIC_URL` | produção | Base pública do backend, usada para registrar o webhook. Sem ela o cliente responde mas o sistema não vê |
| `TIMEZONE` | não | Fuso do Celery. Padrão `America/Manaus` |
| `DATABASE_URL` | não | Injetada pelo compose. Só defina à mão fora do Docker |
| `REDIS_URL` | não | Injetada pelo compose |

Copie `.env.example` e preencha. **Nunca comite o `.env`** — ele tem a chave da
Evolution. O `.gitignore` já protege.

---

## Estrutura

```
lembrazap/
├── docker-compose.yml        4 serviços + healthchecks
├── .env.example              modelo de configuração
├── deploy/
│   └── nginx-lembrazap.conf  server block para publicar na VPS
├── backend/
│   ├── Dockerfile
│   ├── entrypoint.sh         roda `alembic upgrade head` e sobe o uvicorn
│   ├── alembic/              migrations do banco
│   └── app/
│       ├── main.py           rotas da API
│       ├── schemas.py        modelos de entrada e templates por nicho
│       ├── api/deps.py       autenticação por X-LZ-Token
│       ├── db/               engine, sessão e modelos (4 tabelas)
│       ├── services/         cliente da Evolution API
│       └── worker/           Celery: app, tasks e beat
└── frontend/                 painel em React + Vite (porta 5173)
```

---

## Regras do produto

- **Lembrete de agenda** — dispara `horas_antecedencia` antes do horário.
- **Resposta automática** — `SIM` confirma; `ADIAR`/`REAGENDAR` marca para remarcar.
- **Token de conta** — só o hash SHA-256 é guardado no banco; o token em si aparece
  uma única vez e não é recuperável.

---

## Limitações conhecidas

Estão documentadas em detalhe em [docs/ERROS.md](docs/ERROS.md#limitações-conhecidas).
As mais relevantes:

- **Não há limite diário de envios nem intervalo entre mensagens.** O worker dispara
  em rajada. Mandar campanha grande para número real **pode banir o número**.
  Implemente o P1 de [docs/ARQUITETURA.md](docs/ARQUITETURA.md#pendências) antes.
- **Não há opt-out.** Não existe palavra-chave de descadastro, e os templates não
  trazem a instrução de resposta. Isso é exposição de LGPD e contra a política do WhatsApp.
- **Não há tarefa que reprocesse a fila.** Se um envio falhar, o item fica
  `pendente` para sempre.
- **`reagendando` é beco sem saída.** Depois de `ADIAR`, um `SIM` posterior não
  confirma, porque o webhook só busca agendamentos com status `agendado`.
- **Fuso horário.** O banco guarda UTC e o texto renderiza `{data}`/`{horario}`
  direto do valor UTC — a hora mostrada ao cliente pode estar errada.
- **O painel mostra "Conectado" fixo.** Não consulta o estado real da instância.
- **Sair do painel sem querer cria outra conta** e outra instância na Evolution.

---

## Licença

Projeto privado. Todos os direitos reservados.
