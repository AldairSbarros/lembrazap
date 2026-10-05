# API

Referência das rotas. Com o backend no ar, o **Swagger interativo** fica em
<http://localhost:8000/docs> — clique **Authorize** e cole o token para testar
pelo navegador.

- Base local: `http://localhost:8000`
- Schema OpenAPI: <http://localhost:8000/openapi.json>
- Leitura alternativa: <http://localhost:8000/redoc>

---

## Autenticação

Todas as rotas `/api/*` exigem o header:

```
X-LZ-Token: <token da conta>
```

Exceções: `POST /api/contas` (cria a conta) e `POST /api/webhook/whatsapp`
(chamada pela Evolution).

O token é gerado em `POST /api/contas`, mostrado **uma única vez** e nunca mais
recuperável — o banco guarda só o hash SHA-256. Sem header ou com token errado:

```json
{ "detail": "Informe o header X-LZ-Token." }
```

```json
{ "detail": "Token de conta inválido." }
```

---

## Resumo das rotas

| Método | Rota | Auth | Descrição |
|---|---|---|---|
| `GET` | `/healthz` | não | Healthcheck |
| `POST` | `/api/contas` | não | Cria conta, devolve o token |
| `GET` | `/api/conta` | sim | Dados da conta |
| `POST` | `/api/conexao/criar` | sim | Cria instância na Evolution + registra webhook |
| `GET` | `/api/conexao/qrcode` | sim | QR Code de pareamento |
| `POST` | `/api/configuracoes` | sim | Antecedência e modelo de mensagem |
| `GET` | `/api/agendamentos` | sim | Lista agendamentos |
| `POST` | `/api/agendamentos` | sim | Cria agendamento |
| `POST` | `/api/webhook/whatsapp` | não | Recebe mensagens da Evolution |
| `POST` | `/api/teste-fila` | sim | Enfileira mensagem de teste (não envia) |

---

## Diagnóstico

### `GET /healthz`

```bash
curl http://localhost:8000/healthz
```

```json
{ "status": "ok", "mensagem": "API conectada ao PostgreSQL com sucesso!" }
```

> A mensagem é fixa e **não consulta o banco** — só prova que o processo do
> FastAPI responde. Para checar o banco de verdade, use `alembic current`.

---

## Conta

### `POST /api/contas`

Cria a conta. **Única rota sem autenticação.**

```bash
curl -X POST http://localhost:8000/api/contas \
  -H "Content-Type: application/json" \
  -d '{"nome": "Barbearia Barros", "negocio": "Barbearia Barros"}'
```

```json
{
  "ok": true,
  "tenant_id": "74cb708ed4d7",
  "token": "f2d4f0a6cf075e4dca989dd70ba00799"
}
```

Guarde o `token`. Se perder, não há como recuperá-lo.

| Erro | Quando |
|---|---|
| `400` | `nome` vazio |

### `GET /api/conta`

```bash
curl http://localhost:8000/api/conta -H "X-LZ-Token: $TOKEN"
```

```json
{
  "tenant_id": "74cb708ed4d7",
  "nome": "Barbearia Barros",
  "negocio": "Barbearia Barros",
  "instancia": "LZ_74CB708ED4D7",
  "config": { "horas_antecedencia": 24, "mensagem_modelo": "Fala {nome}..." }
}
```

---

## WhatsApp

### `POST /api/conexao/criar`

Cria a instância na Evolution e registra o webhook. **Idempotente**: chamar de
novo com a instância já existente apenas re-registra o webhook — é assim que se
corrige uma URL pública mudada.

```bash
curl -X POST http://localhost:8000/api/conexao/criar -H "X-LZ-Token: $TOKEN"
```

```json
{
  "ok": true,
  "instancia": "LZ_74CB708ED4D7",
  "ja_existia": false,
  "webhook_configurado": true
}
```

`instancia` segue o padrão `LZ_<tenant_id em maiúsculas>`.

> **`webhook_configurado: false`** significa que `WEBHOOK_PUBLIC_URL` está vazio
> ou que a Evolution recusou o registro. Sem webhook o cliente responde, mas o
> sistema não enxerga. Verifique os logs do backend para o motivo exato.

| Erro | Quando |
|---|---|
| `401` | Token ausente ou inválido |
| `502` | A Evolution recusou ou está inacessível |

### `GET /api/conexao/qrcode`

```bash
curl http://localhost:8000/api/conexao/qrcode -H "X-LZ-Token: $TOKEN"
```

```json
{ "base64": "data:image/svg+xml;base64,PHN2Zy...", "simulado": false }
```

O `base64` já vem em data-uri, pronto para `<img src>`. Com `MODO_SIMULACAO=1` o
QR é fictício e `simulado` vem `true`.

> O QR expira em pouco tempo na Evolution. Se a leitura falhar, chame a rota de
> novo para gerar outro.

| Erro | Quando |
|---|---|
| `404` | Instância ainda não criada |
| `502` | Falha ao gerar o QR |

### `POST /api/webhook/whatsapp`

**Chamada pela Evolution API**, não pelo painel. Precisa estar alcançável em
`WEBHOOK_PUBLIC_URL`.

Payload da Evolution 2.3.x:

```json
{
  "event": "messages.upsert",
  "instance": "LZ_74CB708ED4D7",
  "data": {
    "key": {
      "remoteJid": "5592992030250@s.whatsapp.net",
      "fromMe": false
    },
    "message": { "conversation": "SIM" }
  }
}
```

Regras aplicadas ao texto (uppercase, busca por substring):

| Texto contém | Efeito |
|---|---|
| `SIM` | Agendamento `agendado` → `confirmado`, grava `confirmado_em` |
| `ADIAR` ou `REAGENDAR` | Agendamento `agendado` → `reagendando` |

Resposta quando o texto é reconhecido:

```json
{
  "ok": true,
  "instancia": "LZ_74CB708ED4D7",
  "telefone": "5592992030250",
  "resposta_recebida": "SIM",
  "status_agenda": "confirmado"
}
```

Respostas de "ignorado" — todas devolvem `200`, nunca erro:

| Situação | Corpo |
|---|---|
| Evento não é `messages.upsert` | `{"ok": true, "ignorado": "evento nao relevante"}` |
| Mensagem própria ou grupo | `{"ok": true, "ignorado": "mensagem propria ou remetente invalido"}` |
| Sem texto | `{"ok": true, "ignorado": "sem texto"}` |
| Instância desconhecida | `{"ok": false, "detalhe": "Instancia nao localizada"}` |
| Sem agendamento pendente | `{"ok": true, "info": "Cliente registado, sem agendamento pendente"}` |

> O cliente é localizado pelos **últimos 8 dígitos** do número, enquanto a criação
> de agendamento compara o telefone **inteiro**. Um cliente gravado como
> `5592992030250` e que responde como `992030250` casa no webhook, mas na criação
> do agendamento gera duplicata. Ver [ERROS.md](ERROS.md).

---

## Agendamentos

### `GET /api/agendamentos`

Ordenado por data, mais antigo primeiro. Sem paginação.

```bash
curl http://localhost:8000/api/agendamentos -H "X-LZ-Token: $TOKEN"
```

```json
[
  {
    "id": "00ead7447689",
    "nome": "Carlos Silva",
    "telefone": "5592992030250",
    "servico": "Corte + Barba",
    "quando": "2026-11-03 14:49",
    "status": "agendado"
  }
]
```

### `POST /api/agendamentos`

```bash
curl -X POST http://localhost:8000/api/agendamentos \
  -H "Content-Type: application/json" \
  -H "X-LZ-Token: $TOKEN" \
  -d '{
        "nome": "Carlos Silva",
        "telefone": "5592992030250",
        "servico": "Corte + Barba",
        "quando": "2026-11-03T17:00:00"
      }'
```

```json
{ "ok": true, "id": "00ead7447689" }
```

Cria o `Cliente` automaticamente se ainda não existir para o telefone exato.

> `quando` em ISO 8601. O frontend envia UTC (`.toISOString()`); grave sempre no
> mesmo fuso para evitar deslocamento na mensagem.

| Erro | Quando |
|---|---|
| `422` | Campo faltando ou `quando` inválido |

---

## Configurações

### `POST /api/configuracoes`

Gravação parcial: chaves já existentes que não vêm no corpo são preservadas.

```bash
curl -X POST http://localhost:8000/api/configuracoes \
  -H "Content-Type: application/json" \
  -H "X-LZ-Token: $TOKEN" \
  -d '{
        "horas_antecedencia": 24,
        "mensagem_modelo": "Fala {nome}, lembra do horário na {negocio} para {servico} em {data} às {horario}. Responda SIM para confirmar."
      }'
```

```json
{ "ok": true, "mensagem": "Configurações guardadas com sucesso!" }
```

`horas_antecedencia` aceita de 1 a 720.

Placeholders do `mensagem_modelo`:

| Placeholder | Vira |
|---|---|
| `{nome}` | Nome do cliente (ou `"Cliente"`) |
| `{negocio}` | Nome do negócio (ou `"nosso espaço"`) |
| `{servico}` | Serviço (ou `"atendimento"`) |
| `{data}` | `dd/mm` |
| `{horario}` | `hh:mm` |

> Um placeholder desconhecido — `{foo}` — causa `KeyError` no worker e **derruba o
> lote inteiro de todos os clientes**. Ver
> [ERROS.md](ERROS.md#a-mensagem-personalizada-quebrou).

**Não há rota `GET` de configurações.** O painel nunca carrega a config salva, e
ao salvar de novo sobrescreve o template com o padrão. Use `GET /api/conta`.

---

## Diagnóstico

### `POST /api/teste-fila`

Parâmetros de **query**, não de corpo.

```bash
curl -X POST "http://localhost:8000/api/teste-fila?telefone=5592992030250&mensagem=teste" \
  -H "X-LZ-Token: $TOKEN"
```

```json
{
  "ok": true,
  "info": "Tarefa enviada para a fila (background) com sucesso!",
  "tarefa_id": "a1b2c3d4-..."
}
```

> Enfileira `simular_envio_whatsapp`, que **apenas escreve no log**. Não envia
> WhatsApp. Serve para confirmar que Redis e worker estão conversando. Não é um
> teste de entrega.

---

## Clientes

Base de clientes do negócio. Toda query filtra por `tenant_id`: um negócio nunca
enxerga a base de outro, mesmo com token válido.

### `GET /api/clientes`

Lista a base. Query params:

| Param | Padrão | O que faz |
|---|---|---|
| `busca` | `""` | Filtra por nome (parcial, case-insensitive) ou por telefone. Com dígitos, casa o sufixo — `999998888` acha `5511999998888` |
| `inativos` | `false` | Só quem está a **mais dias** sem visitar que o configurado |
| `sem_historico` | `false` | Só quem nunca teve visita registrada |
| `limite` | `200` | Máximo de itens (1–1000) |

Resposta:

```json
{
  "total": 5,
  "dias_sem_visitar": 45,
  "reativacao_ativa": true,
  "clientes": [
    {
      "id": "02f613714d7f",
      "nome": "Carlos Silva",
      "telefone": "5511999998888",
      "telefone_formatado": "(11) 99999-8888",
      "ultima_visita": "2026-09-01 00:00",
      "dias_sem_visitar": 34,
      "obs": "Prefere de manhã",
      "opt_out": false,
      "ultima_resposta": "SIM",
      "respondeu_em": "2026-09-01 18:22",
      "inativo": false,
      "sem_historico": false
    }
  ]
}
```

`sem_historico` é separado de `inativo` de propósito: quem nunca registrou
visita é o caso ambíguo — nunca voltou, ou veio da planilha e ninguém
atualizou. O que fazer com eles é decisão do dono.

### `POST /api/clientes`

```json
{ "nome": "Carlos Silva", "telefone": "(11) 99999-8888", "ultima_visita": "2026-09-01T14:30:00", "obs": "" }
```

O telefone é normalizado para dígitos com DDI (`5511999998888`). `+55`,
`(11)`, espaços e `-` são aceitos; **fixo de 8 dígitos é recusado** com 422
porque WhatsApp no Brasil é só celular — aceitar faria o contato passar pela
importação e falhar só no envio.

Se já existir cliente com o mesmo telefone nesta conta, **atualiza** em vez de
duplicar e devolve `"atualizado": true`.

### `PUT /api/clientes/{id}`

Atualização parcial; campos omitidos ficam como estão. Aceita `nome`,
`telefone`, `ultima_visita`, `obs` e `opt_out`. É esta rota que o painel usa
para registrar visita e para reativar manualmente quem pediu para não receber.
Trocar o telefone para um já usado nesta conta devolve 409.

### `DELETE /api/clientes/{id}`

Remove o cliente. Os agendamentos antigos são mantidos (`cliente_id` fica nulo):
excluir um cliente não deve apagar o histórico de visitas que aconteceram.

### `POST /api/clientes/opt-out`

Marca um telefone como não querendo receber. Chamado pelo webhook quando o
cliente responde `SAIR`/`PARAR`, e pelo painel quando o pedido chega pelo
telefone.

```json
{ "telefone": "(11) 99999-8888" }
```

### `POST /api/clientes/importar`

`multipart/form-data` com o campo `arquivo`. Query param `atualizar_existentes`
(padrão `true`).

O separador é detectado automaticamente entre `,`, `;` e tabulação — planilha
brasileira exporta com `;`, e assumir `,` importaria um arquivo de uma coluna
só.

| Campo | Cabeçalhos aceitos |
|---|---|
| nome | `nome`, `cliente`, `nome do cliente`, `nome completo`, `name` |
| telefone | `telefone`, `celular`, `whatsapp`, `fone`, `contato`, `numero`, `tel` |
| última visita | `ultima visita`, `ultimo atendimento`, `data`, `visita` |
| observação | `obs`, `observacao`, `nota`, `anotacao` |

Datas aceitas: ISO (`2026-07-20T10:30:00`), `dd/mm/aaaa`, `dd/mm/aa`,
`dd-mm-aaaa`, `aaaa-mm-dd`. `nunca` e vazio significam "sem histórico". O que
não dá para interpretar fica sem histórico, em vez de virar data errada — data
errada decide quem entra na campanha de reativação.

Resposta:

```json
{
  "ok": true,
  "criados": 5,
  "atualizados": 2,
  "ignorados": 1,
  "duplicados_no_arquivo": 1,
  "colunas_reconhecidas": ["nome", "obs", "telefone", "ultima_visita"],
  "problemas": ["Carla Dias: telefone '21 3333-4444' inválido"],
  "mensagem": "5 cliente(s) importado(s), 2 atualizado(s), 1 ignorado(s). 1 telefone(s) repetido(s) foram unidos."
}
```

Telefone repetido **dentro do próprio arquivo** vira um registro só, preferring
a linha que traz o nome e a data mais recente. Planilha de histórico repete o
contato com frequência, e nem sempre a linha boa vem primeiro.

A importação nunca falha inteira por causa de uma linha suja: o que não entra
aparece em `ignorados` e `problemas`.

### `POST /api/agendamentos/{id}/concluir`

Marca a visita como realizada e zera o contador de dias sem visita. Devolve
`cliente_registrado` indicando se havia cliente vinculado.

O `SIM` no WhatsApp confirma que o cliente *vai* vir; concluir confirma que ele
*veio*. Só o segundo deve zerar o contador.

---

## Regras de disparo

### `GET /api/configuracoes`

Lê as regras da conta com os defaults já aplicados, mais a lista de
placeholders válidos. Existia só o `POST`: o painel não conseguia reidratar o
formulário e perdia o que o dono tinha digitado ao recarregar.

```json
{
  "horas_antecedencia": 24,
  "mensagem_lembrete": "Fala {nome}, seu horário na {negocio} é {data} às {horario}.",
  "dias_sem_visitar": 45,
  "reativacao_ativa": true,
  "limite_por_dia": 50,
  "mensagem_reativacao": "Fala {nome}, faz {dias} dias que não te vemos!",
  "envios_pausados": false,
  "placeholders": ["nome", "negocio", "servico", "data", "horario", "telefone", "dias"]
}
```

### `POST /api/configuracoes`

Grava as regras. Todos os campos têm default, então dá para mandar só o que
muda.

| Campo | Faixa | Default | Efeito |
|---|---|---|---|
| `horas_antecedencia` | 1–720 | 24 | Avisar quantas horas antes da consulta |
| `dias_sem_visitar` | 7–365 | 45 | Quando o cliente entra na reativação |
| `reativacao_ativa` | bool | `false` | Liga o disparo diário dos sumidos |
| `limite_por_dia` | 1–500 | 50 | Teto por negócio, para não estourar a janela da Evolution |
| `envios_pausados` | bool | `false` | Pausa tudo sem perder a fila |

Devolve `avisos` com o que foi removido do texto — um `{cliente}` digitado no
lugar de `{nome}` é avisado na hora de salvar, em vez de a mensagem chegar sem
o nome do cliente.

---

## Não documentado (não existe)

Estas rotas são referenciadas em versões anteriores e **não estão implementadas**:

| Rota prevista | Para quê |
|---|---|
| `GET /api/conexao/status` | Estado real da instância. Hoje o painel mostra "Conectado" fixo |
| `GET /api/reativacao/preview` | Prévia da campanha de inativos antes de disparar |
| `POST /api/reativacao/disparar` | Disparo manual, fora do horário do beat |
| `GET /api/envios` | Log de mensagens enviadas |
| `DELETE /api/agendamentos/{id}` | Cancelar um horário |
