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

### As duas campanhas

Rodam no mesmo worker, diferenciadas pelo valor de `campanha` em `fila`:

| Campanha | Quando dispara | Quem entra | Janela |
|---|---|---|---|
| `lembrete_agendamento` | beat a cada 10 min | `agenda` com status `agendado` dentro de `horas_antecedencia` | 30 min de tolerância |
| `reativacao_inativos` | beat, uma vez à meia-noite | `clientes` com `ultima_visita` anterior ao corte e **sem** `opt_out` | teto de `limite_por_dia` |

O corte da reativação é `dias_sem_visitar`, configurável por conta (7 a 365).
Cliente sem `ultima_visita` **não entra**: não há como saber há quanto tempo não vem,
e afirmar "faz 90 dias" para quem acabou de ser cadastrado queima a credibilidade do
número.

---

## Cobrança e acesso

O dono do sistema opera em `/admin`, com sessão separada. O admin **não é um
tenant**: outra tabela, outro header, outra chave de `localStorage`.

```
┌──────────────┐  X-LZ-Admin   ┌──────────────┐
│  /admin      │ ─────────────▶ │  /api/admin  │ ──▶ tenants (status, plano)
│  React       │               │  contas,     │ ──▶ pagamentos (histórico)
└──────────────┘               │  cobrança    │ ──▶ clientes (leitura, máscara)
                               └──────┬───────┘
                                      ▲
                          POST /api/admin/stripe/webhook
                                      │
                               ┌──────┴───────┐
                               │    Stripe     │
                               └──────────────┘

┌──────────────┐  X-LZ-Token   ┌──────────────┐
│  painel do   │ ─────────────▶ │  /api/*      │
│  assinante   │   402 se      │  clientes,   │
└──────────────┘  bloqueado    │  agenda, cfg │
```

### Onde o bloqueio é verificado

`pode_operar()` em `services/assinatura.py` é a função única de decisão, e é
chamada em três camadas — **duas delas no worker**, porque a fila tem latência:

| Camada | Arquivo | Efeito |
|---|---|---|
| API | `api/deps.py: exigir_acesso_ativo` | `402` em agendamento, teste de fila e importação |
| Enfileirar | `worker/tasks.py` | lembrete e reativação pulam a conta |
| Enviar | `worker/tasks.py: processar_item_fila` | barrado mesmo se enfileirado **antes** da suspensão |

Suspender também **esvazia a fila pendente** da conta. Sem isso, um lembrete marcado
antes da suspensão sairia depois dela.

O webhook do WhatsApp **não** é bloqueado: com a conta suspensa, o `SAIR` de um
cliente precisa continuar sendo registrado e concluir uma visita precisa zerar o
contador de dias.

### Idempotência do Stripe

O Stripe reenvia um webhook até receber `200`, então a mesma cobrança pode chegar
várias vezes. `pagamentos.stripe_event_id` tem **índice único**: reentregar o mesmo
evento não conta a cobrança duas vezes no painel.

A rota responde `200` mesmo sem conseguir identificar a conta. Devolver erro faz o
Stripe reenviar por dias, e um evento órfão de conta apagada viraria ciclo
infinito de reenvio.

---

## Componentes

### `backend/app/main.py`

Rotas FastAPI, CORS e descrição do OpenAPI. Instância única do Celery importada
de `worker/celery_app.py` — usado só para `send_task`.

### `backend/app/api/`

Três módulos de rotas, porque `main.py` sozinho já estava grande demais e o painel
administrativo precisa ficar longe do fluxo do assinante:

| Arquivo | Prefixo | Sessão |
|---|---|---|
| `clientes.py` | `/api/clientes` | `X-LZ-Token` |
| `assinatura.py` | `/api/assinatura` | `X-LZ-Token` (`/planos` é pública) |
| `admin.py` | `/api/admin` | `X-LZ-Admin` |

### `backend/app/api/deps.py`

Duas autenticações, deliberadamente independentes:

| Dependência | Header | Resolve |
|---|---|---|
| `obter_tenant_atual` | `X-LZ-Token` | `tenants.token_hash` = SHA-256 do token |
| `obter_admin_atual` | `X-LZ-Admin` | `admin_usuarios.token_hash` = SHA-256 |

`exigir_acesso_ativo` é a dependência que devolve `402` quando a assinatura não
está em ordem. Fica separada de `obter_tenant_atual` porque conta bloqueada
**precisa** continuar lendo a própria base: o bloqueio é de envio, não de acesso.

### `backend/app/services/`

| Arquivo | Responsabilidade |
|---|---|
| `evolution.py` | Cliente da Evolution API |
| `telefone.py` | Normalização para dígitos com DDI; recusa fixo |
| `mensagem.py` | Renderização de template e validação de chaves |
| `config_disparo.py` | Leitura das regras de `tenants.config` com defaults |
| `assinatura.py` | `pode_operar()`, máquina de status e processamento do webhook |
| `stripe.py` | Checkout, portal e validação de assinatura do webhook |
| `seguranca.py` | PBKDF2 da senha de admin |

`stripe.py` importa o pacote `stripe` **de forma tardia**, só quando há
`STRIPE_SECRET_KEY`. É o que deixa a API subir sem o pacote instalado e o sistema
funcionar em cobrança manual.

### `backend/app/config/planos.py`

Catálogo de planos como **dados**, não código: preço, limite de clientes e de
mensagens por plano. `STRIPE_PRECIO_*` no ambiente sobrescreve o arquivo, então
mudar preço não exige mexer no código.

### `backend/app/db/`

`database.py` cria a engine no **import do módulo** — sem `DATABASE_URL` a API
não sobe (é o motivo de não existir execução fora do Docker sem exportar a
variável). `models.py` tem as sete tabelas.

### `backend/app/services/evolution.py`

Cliente da Evolution API. Cinco operações: `criar_instancia`, `obter_qrcode`,
`status_conexao`, `enviar_texto`, `definir_webhook`, mais
`extrair_mensagem_recebida` para parsear o payload de entrada. Todas com
`timeout=30` e modo simulação.

### `backend/app/worker/`

`celery_app.py` é a **única** instância do Celery: broker, serializers, fuso e
`beat_schedule`. `tasks.py` importa dela — não cria outra.

Quatro tasks:

| Task | Quando roda | O que faz |
|---|---|---|
| `verificar_e_disparar_lembretes` | Beat, a cada 600s | Varre a agenda de todos os tenants e cria itens de fila |
| `reativar_clientes_inativos` | Beat, à meia-noite | Monta a campanha de sumidos, respeitando `opt_out` e `limite_por_dia` |
| `processar_item_fila` | `.delay()` das anteriores | Envia via Evolution e atualiza status |
| `simular_envio_whatsapp` | `POST /api/teste-fila` | Só escreve no log |

As duas primeiras pulam conta sem acesso, e `processar_item_fila` barra o envio de
mensagem que já estava na fila antes da suspensão.

---

## Modelo de dados

Sete tabelas. Chaves de 12 caracteres hex (`uuid4().hex[:12]`).

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
| `campanha` | `lembrete_agendamento` ou `reativacao_inativos` |
| `prioridade` | **Nunca lida** — sobrou da fila com prioridade |
| `simulado` | Gravado por `processar_item_fila` |

### `pagamentos`

Histórico financeiro, criado na revisão `8a4c2f19d3e7`.

| Coluna | Nota |
|---|---|
| `stripe_event_id` | **Índice único.** É o que torna o webhook idempotente quando o Stripe reenvia |
| `tipo` | `checkout`, `renovacao`, `falha`, `manual` |
| `status` | `pago`, `falhou`, `pendente`, `cancelado`, `estornado` |
| `valor_centavos` | Inteiro, nunca float — centavo não tem fração |

### `planos_stripe`

Cache dos `price_id` criados sob demanda. Existe porque preço pré-criado no painel
da Stripe é o caminho que a documentação deles recomenda, mas exige passo manual na
instalação.

| Coluna | Nota |
|---|---|
| `chave` | PK: `starter`, `pro`, `business` |
| `price_id` | O que vai no `line_items` do checkout |
| `preco_centavos` | O que a Stripe está cobrando. Divergir do catálogo é sinalizado no admin |

A ordem de resolução em `garantir_preco()` é:

1. `STRIPE_PRICE_ID_*` no ambiente — configuração explícita sempre vence.
2. `planos_stripe` — evita chamada à API em todo checkout.
3. Busca na Stripe por `metadata['lembrazap_plano']` — rede de segurança para o
   caso do banco ser recriado.
4. Só então cria Product + Price.

O passo 3 é o que torna a automação segura: sem ele, recriar o banco duplicaria
todos os produtos. A busca é feita listando produtos ativos e filtrando em Python,
**não** por `products.search`, porque a Search API depende de habilitação na conta
e falha com `api_key_invalid` quando não está.

**Limite conhecido:** `price_id` é imutável na Stripe. Mudar `planos.py` afeta só
quem assinar depois; mover assinantes existentes é operação manual na Stripe.
`POST /api/admin/planos/{chave}/sincronizar` cria um preço novo, não migra ninguém.

### `admin_usuarios`

O proprietário do sistema. **Não é um tenant**: não tem base de clientes, não
recebe disparo e nunca aparece no painel do assinante.

| Coluna | Nota |
|---|---|
| `email` | Identidade de login, índice único |
| `senha_hash` | PBKDF2-HMAC-SHA256, 600k iterações |
| `token_hash` | SHA-256 do token do header `X-LZ-Admin` |

Povoado por `seed.py`, que é **idempotente** e seguro para rodar a cada deploy:
reexecutar nunca sobrescreve a senha de um admin existente. Um seed que resetasse
senha traria a conta de volta ao padrão de fábrica em produção.

---

## Assinatura em `tenants`

Colunas adicionadas na revisão `8a4c2f19d3e7`. Contas existentes entram como
`trial` com `assinatura_ativa = false`, então **nada é liberado por accident** ao
aplicar a migração: o dono abre o acesso uma a uma.

| Coluna | Nota |
|---|---|
| `status` | `trial`, `ativo`, `inadimplente`, `suspenso`, `cancelado`. Indexado |
| `plano` | Chave de `config/planos.py`. Define clientes e mensagens |
| `stripe_customer_id`, `stripe_subscription_id` | Indexados: toda mensagem do webhook busca a conta por eles |
| `assinatura_ativa` | Booleano derivado do status, mantido junto para consulta rápida |
| `renovacao_em` | Vence o teste e a renovação. `NULL` = sem expiração |
| `motivo_suspensao` | Texto livre. Aparece para o assinante no painel |

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
| 1 | **Intervalo mínimo entre mensagens**, e teto também para o lembrete de agendamento. Hoje `limite_por_dia` só cobre a reativação | Ban do número |
| 2 | **Instrução de descadastro nos templates padrão**. O opt_out por palavra-chave já funciona | LGPD, política WhatsApp |
| 3 | **Task que drene a fila `pendente`, com retry** | Mensagem perdida para sempre |
| 4 | ~~Checar `Cliente.opt_out` antes de enviar~~ — feito, em três camadas | — |
| 5 | **Janela com recuperação** para lembretes perdidos | Cliente não avisado |
| 6 | **Aviso de vencimento da assinatura**. Hoje o cliente só descobre quando algo falha com `402` | Renovação perdida |

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
