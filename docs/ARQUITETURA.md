# Arquitetura

Como o sistema é montado por dentro.

---

## Visão geral

```
┌─────────────┐   HTTP    ┌──────────────┐   SQL    ┌────────────┐
│  frontend   │ ────────▶ │   backend    │ ───────▶ │ PostgreSQL │
│ React/Vite  │ ◀──────── │ FastAPI      │ ◀─────── │     15     │
│  :5173      │           │  :8000       │          └────────────┘
└─────────────┘           └──────┬───────┘
                                  │                    ┌────────────┐
                       enfileira  │    busca/templates │   Redis    │
                                  ▼                    │     7      │
                           ┌─────────────┐             └─────▲──────┘
                           │   worker    │─────────────── ┘
                           │ Celery+beat │◀──── tick 10 min
                           └──────┬──────┘
                                  │ sendText / create / webhook:set
                                  ▼
                           ┌─────────────┐   POST   ┌────────────────┐
                           │ Evolution    │ ───────▶ │  WhatsApp do   │
                           │ API 2.3.x    │ ◀─────── │  cliente       │
                           └─────────────┘  messages └────────────────┘
                                  ▲                upsert
                                  └────────────────┘
                                     webhook
```

**Fluxo do lembrete (push):** worker encontra agendamento na janela → monta o
texto → cria item em `fila` → chama a Evolution → marca como enviado.

**Fluxo da resposta (pull):** cliente responde no WhatsApp → Evolution faz POST no
webhook → backend identifica o cliente pelos últimos 8 dígitos → atualiza o
status do agendamento.

O segundo fluxo **depende inteiramente** do webhook. Sem URL pública, o cliente
responde e o sistema não fica sabendo.

---

## Componentes

### `backend/app/main.py`

Rotas FastAPI, CORS e descrição do OpenAPI. Instância única do Celery importada
de `worker/celery_app.py` — usado só para `send_task`.

### `backend/app/api/deps.py`

Autenticação. `X-LZ-Token` → SHA-256 → busca em `tenants.token_hash`. O token em
si nunca é persistido.

### `backend/app/db/`

`database.py` cria a engine no **import do módulo** — sem `DATABASE_URL` a API
não sobe (é o motivo de não existir execução fora do Docker sem exportar a
variável). `models.py` tem as quatro tabelas.

### `backend/app/services/evolution.py`

Cliente da Evolution API. Cinco operações: `criar_instancia`, `obter_qrcode`,
`status_conexao`, `enviar_texto`, `definir_webhook`, mais
`extrair_mensagem_recebida` para parsear o payload de entrada. Todas com
`timeout=30` e modo simulação.

### `backend/app/worker/`

`celery_app.py` é a **única** instância do Celery: broker, serializers, fuso e
`beat_schedule`. `tasks.py` importa dela — não cria outra.

Três tasks:

| Task | Quando roda | O que faz |
|---|---|---|
| `verificar_e_disparar_lembretes` | Beat, a cada 600s | Varre a agenda de todos os tenants e cria itens de fila |
| `processar_item_fila` | `.delay()` da anterior | Envia via Evolution e atualiza status |
| `simular_envio_whatsapp` | `POST /api/teste-fila` | Só escreve no log |

---

## Modelo de dados

Quatro tabelas. Chaves de 12 caracteres hex (`uuid4().hex[:12]`).

### `tenants` — uma linha por conta

| Coluna | Tipo | Nota |
|---|---|---|
| `id` | `varchar` PK | 12 chars |
| `nome`, `negocio` | `varchar` | |
| `token_hash` | `varchar` | Único, indexado. SHA-256 do token |
| `instancia` | `varchar` | Nome da instância na Evolution |
| `config` | `json` | `horas_antecedencia`, `mensagem_modelo` |
| `criado_em` | `datetime` | `datetime.utcnow()` |
| `ultima_envio_em` | `datetime` | **Nunca usado** — sobrou do rate limit do protótipo |

### `clientes`

| Coluna | Nota |
|---|---|
| `tenant_id` | FK `tenants.id`, `ON DELETE CASCADE` |
| `telefone` | Indexado, **normalizado** para dígitos com DDI (55 + DDD + 9) por `app/services/telefone.py`. É o que impede o mesmo contato entrar duas vezes |
| `ultima_visita` | Alimenta o motor de reativação. Gravada ao confirmar (`SIM`) e em `POST /api/agendamentos/{id}/concluir` |
| `obs` | Campo livre, exibido no painel |
| `opt_out` | **Respeitado** em três camadas: filtro do motor de reativação, filtro do lembrete de agendamento e barreira final em `processar_item_fila`. Quem responde `SAIR`/`PARAR` nunca mais recebe |
| `respondeu_em`, `ultima_resposta` | Gravados pelo webhook em qualquer resposta recebida |
| `resposta_auto_enviada` | **Nunca usado** |

### `agenda`

| Coluna | Nota |
|---|---|
| `quando` | Indexado. Guardado em UTC |
| `servico` | Adicionado na revisão `7f3d9c1b2e40` |
| `status` | `agendado`, `na_fila`, `enviado`, `confirmado`, `reagendando` |
| `confirmado_em` | Adicionado em `7f3d9c1b2e40` |
| `origem` | **Sempre `manual`** — o agendamento por IA foi removido |
| `mensagem` | **Nunca usado** |

### `fila`

| Coluna | Nota |
|---|---|
| `agenda_id`, `cliente_id` | Sem FK — sem integridade referencial |
| `campanha` | Sempre `lembrete_remarcacao` |
| `prioridade` | **Nunca lida** — sobrou da fila com prioridade |
| `simulado` | Gravado por `processar_item_fila` |

> Sete colunas existem no schema e nunca são exercitadas pelo código. O modelo
> ficou à frente da implementação.

---

## Identificadores e instância Evolution

O `id` do tenant vira o nome da instância na Evolution:

```python
nome_instancia = f"LZ_{tenant.id}".upper()   # "LZ_74CB708ED4D7"
```

---

## Fuso horário

Inconsistente em três pontos:

1. Modelos gravam `datetime.utcnow()` — UTC sem timezone awareness
2. O frontend manda `new Date(valor).toISOString()` — UTC
3. `formatar_mensagem` renderiza `{data}` e `{horario}` do valor UTC cru

Ou seja: o horário marcado como 14h local chega ao cliente como 18h. `TIMEZONE`
afeta apenas o Celery (beat e `enable_utc=True`).

---

## Idempotência

`POST /api/conexao/criar` é idempotente: com a instância já existente, apenas
re-registra o webhook. Antes disso, corrigir uma URL pública errada exigia criar
uma segunda instância e orfanar a primeira na Evolution.

---

## Pontos de atenção para quem mexer

**Importar o Celery só de `app.worker.celery_app`.** Houve três instâncias
concorrentes no histórico (uma em `celery_app.py`, uma em `tasks.py`, uma em
`main.py`). O worker sobe com `-A app.worker.celery_app`; se as tasks forem
registradas em outro objeto, o beat fica com schedule vazio e nenhum lembrete
dispara.

**`definir_webhook` usa o corpo encapsulado.** A Evolution 2.3.x valida por schema:

```json
{"webhook": {"enabled": true, "url": "...", "events": ["MESSAGES_UPSERT"]},
 "events": ["MESSAGES_UPSERT"]}
```

Na raiz, devolve `400 instance requires property "webhook"`.

**Migrations no boot, só no `backend`.** O `worker` usa `entrypoint: []` para não
rodar `upgrade head` em paralelo.

**O `try/except` do scan é global.** Em `verificar_e_disparar_lembretes` o
`try` envolve o laço de todos os tenants. Um template malformado em uma conta
derruba o disparo das outras.

---

## Pendências

Ordem sugerida, do mais urgente ao menos:

### P0 — WhatsApp real

| # | Pendência | Risco |
|---|---|---|
| 1 | **Limite diário e intervalo entre envios** | Ban do número |
| 2 | **Opt-out por palavra-chave + template com instrução de descadastro** | LGPD, política WhatsApp |
| 3 | **Task que drene a fila `pendente`, com retry** | Mensagem perdida para sempre |
| 4 | **Checar `Cliente.opt_out` antes de enviar** | Envio para quem pediu para sair |
| 5 | **Janela com recuperação** para lembretes perdidos | Cliente não avisado |

### P1 — Fechar o produto

| # | Pendência |
|---|---|
| 6 | Resposta automática ao `SIM` (os textos já existem em `schemas.py`, nunca usados) |
| 7 | ~~Campanha de reativação~~ — feita: task `reativar_clientes_inativos`, diária |
| 8 | ~~CRUD de clientes + import CSV~~ — feito: `api/clientes.py` e tela no painel |
| 9 | Abordagem de `reagendando` (hoje é beco sem saída) |
| 10 | Agendamento por IA (`origem` já existe) |
| 11 | Log de envios (`GET /api/envios`) |
| 12 | Prévia da campanha antes de disparar (`GET /api/reativacao/preview`) — hoje o dono liga a reativação às cegas |

### P2 — Correção

| # | Pendência |
|---|---|
| 12 | Padronizar fuso horário (decidir UTC ou local e aplicar nos três pontos) |
| 13 | Normalizar telefone e unificar os dois critérios de busca |
| 14 | `GET /api/conexao/status` e ligar o cartão "Conectado" ao estado real |
| 15 | `GET` de configurações e carregar a config ao abrir o painel |
| 16 | Persistir o token no navegador, com tela de login |
| 17 | Parar de criar conta nova ao "desconectar" |
| 18 | `try/except` por tenant no scan |
| 19 | Fonte única para os templates de nicho (hoje divergem em 3 lugares) |
| 20 | Renomear `postccs.config.js` e migrar o Tailwind para v4 |
| 21 | `alembic revision --autogenerate` no CI, para pegar drift de schema |

### P3 — Operação

| # | Pendência |
|---|---|
| 22 | Testes (o `teste_fumaca.sh` do protótipo foi removido) |
| 23 | Pinos de versão em `requirements.txt` |
| 24 | Rate limit em `POST /api/contas` (cria instâncias sem limite) |
| 25 | HTTPS na URL da Evolution (hoje é HTTP com a chave no header) |
