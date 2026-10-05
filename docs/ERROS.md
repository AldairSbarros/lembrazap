# Diagnóstico e Erros

Sintomas, causas e soluções. Ao final, as
[limitações conhecidas](#limitações-conhecidas) do sistema.

---

## Começando

```bash
docker compose ps                                  # estado dos 4 serviços
docker compose logs -f backend                     # API e migrations
docker compose logs -f worker                      # envios e lembretes
docker compose exec backend alembic current        # revisão do banco
curl http://localhost:8000/healthz                 # a API responde?
```

Os dois serviços que importam:

| Serviço | Saudável quando | Se não estiver |
|---|---|---|
| `backend` | `healthy` | API fora do ar — nada funciona |
| `worker` | `up` + logs com `ready` | Nenhum lembrete é disparado |

---

## Container não sobe

### `backend` reinicia em loop

```
Erro: relation "tenants" does not exist
```

O banco subiu sem schema. O `entrypoint.sh` roda `alembic upgrade head` antes do
uvicorn; se a migration falhou, o uvicorn nem chega a subir.

```bash
docker compose logs backend | Select-String "alembic"   # ver o erro real
docker compose exec backend alembic current
docker compose exec backend alembic upgrade head
```

### `worker` não sobe e o `backend` está healthy

Esperado. O `worker` só sobe depois que o `backend` fica `healthy`, para não
lidar com o banco sem tabela. Se o backend está healthy e o worker ainda não
subiu, confira se o `backend` não reiniciou durante o processo.

### `dependency failed to start: container is unhealthy`

O Postgres ou o Redis não ficaram prontos. Os dois têm healthcheck com 10
tentativas de 5s.

```bash
docker compose logs db | Select-Object -Last 20
```

Causa comum: porta `5432` ou `6379` ocupada na máquina.

```bash
docker compose ps -a        # ver o status de cada um
netstat -ano | findstr :5432
```

---

## Banco de dados

### `UndefinedColumn: column agenda.servico does not exist`

O código está à frente do schema. Aplique as migrations:

```bash
docker compose exec backend alembic current
docker compose exec backend alembic upgrade head
```

Revisões esperadas:

| Revisão | Conteúdo |
|---|---|
| `0b5bbedbd982` | Tabelas iniciais |
| `7f3d9c1b2e40` | `agenda.servico`, `agenda.confirmado_em`, `clientes.ultima_resposta` |

### `password authentication failed for user`

O `docker-compose.yml` fixa `lembrazap_user` / `password_segura` / base `lembrazap`.
Se você já tinha um volume antigo com outra senha, as credenciais do compose não
batem.

```bash
docker compose exec db psql -U lembrazap_user -d lembrazap -c "\dt"
```

Para recomeçar do zero (apaga tudo):

```bash
docker compose down -v && docker compose up -d --build
```

---

## O webhook não chega

**Sintoma:** o cliente responde `SIM`, mas o status continua `Pendente`.

Este é o problema mais comum, porque tem duas causas independentes.

### 1. `WEBHOOK_PUBLIC_URL` vazio

Na criação da instância, a resposta mostra:

```json
{ "webhook_configurado": false }
```

Confirme:

```bash
docker compose exec backend printenv WEBHOOK_PUBLIC_URL
docker compose logs backend | Select-String "Webhook não configurado"
```

Sem essa variável a Evolution não é avisada de nada. O cliente responde, a
resposta vai para o vazio.

**Correção:** definir a variável e **re-registrar** (a rota é idempotente):

```bash
docker compose up -d --build
curl -X POST http://localhost:8000/api/conexao/criar -H "X-LZ-Token: $TOKEN"
```

### 2. A URL não está alcançável

```bash
curl -X POST "$WEBHOOK_PUBLIC_URL/api/webhook/whatsapp" \
  -H "Content-Type: application/json" \
  -d '{"event":"messages.upsert","instance":"X","data":{"key":{"remoteJid":"1@s.whatsapp.net","message":{"conversation":"SIM"}}}}'
```

Esperado: `200` com `Instancia nao localizada`. Se der timeout, 502 ou 404, a URL
pública não alcança este backend.

Sintomas por ambiente:

| Ambiente | Sintoma | Causa |
|---|---|---|
| Produção | 404 no domínio | Bloco do nginx não publicado, ou proxy para a porta errada |
| Produção | Erro de SSL | `certbot` não rodou para o subdomínio |
| Túnel | URL mudou | Túneis quick mudam a cada reinício — re-registre o webhook |
| Local | `localhost` na URL | A Evolution está em outro máquina e não alcança `localhost` |

### 3. A Evolution recusou o registro

```
Webhook não configurado para LZ_...: 400 Client Error
```

Nesta versão (2.3.x) o corpo tem que ser enviado **encapsulado**:

```json
{
  "webhook": { "enabled": true, "url": "...", "events": ["MESSAGES_UPSERT"] },
  "events": ["MESSAGES_UPSERT"]
}
```

Enviar os campos na raiz devolve `400` com
`instance requires property "webhook"`. Se o erro for esse, o código está
desatualizado — confira `app/services/evolution.py`.

### Testar a cadeia sem esperar o cliente

```bash
curl -X POST http://localhost:8000/api/webhook/whatsapp \
  -H "Content-Type: application/json" \
  -d '{
        "event": "messages.upsert",
        "instance": "LZ_SEU_TENANT",
        "data": {
          "key": {"remoteJid": "5592992030250@s.whatsapp.net", "fromMe": false},
          "message": {"conversation": "SIM"}
        }
      }'
```

Com um agendamento `agendado` do mesmo telefone, o status deve virar
`confirmado`.

---

## A mensagem personalizada quebrou

**Sintoma:** nenhum cliente recebe aviso, mesmo com tudo saudável.

> **Corrigido em duas frentes.** Hoje uma chave inválida **não derruba mais** o
> lote: `formatar_mensagem` substitui o que reconhece e devolve os `avisos` do que
> sobrou, e o `try/except` do worker passou a ficar **dentro** do laço de tenants —
> um texto quebrado de um cliente não impede mais o disparo dos outros.
>
> Os comandos abaixo servem para diagnóstico e para o caso de você ter um texto
> salvo antes da correção.

**Causa original:** a montagem usava `str.format()`. Uma chave desconhecida no texto
— `{foo}`, `{nome do cliente}`, ou uma chave pela metade como `{nome` — gerava
`KeyError` e derrubava o lote inteiro.

**Como está agora:** chaves inválidas viram aviso no `POST /api/configuracoes`, e a
mensagem segue com o trecho substituído pelo que deu para substituir. O painel
mostra os `avisos` na hora em que você salva.

```bash
# conferir o que está gravado e os avisos
curl -H "X-LZ-Token: $TOKEN" http://localhost:8000/api/configuracoes
```

Aceitos nas duas campanhas:

| Campanha | Chaves |
|---|---|
| Lembrete | `{nome}`, `{negocio}`, `{servico}`, `{data}`, `{horario}`, `{telefone}` |
| Reativação | `{nome}`, `{negocio}`, `{dias}`, `{telefone}` |

Qualquer outro nome vira aviso. O aviso mais comum é o nome do cliente escrito com
espaço — `{nome do cliente}` em vez de `{nome}`.

---

## Nenhum lembrete é disparado

### O agendamento está fora da janela

O worker só enxerga agendamentos **entre `agora + antecedência` e
`agora + antecedência + 30 minutos`**. É uma janela de 30 minutos.

Se o worker esteve parado durante a janela, **o lembrete é perdido
definitivamente** — não existe reprocessamento.

```bash
docker compose logs worker | Select-String "Scheduler: Sending"
docker compose exec -T db psql -U lembrazap_user -d lembrazap \
  -c "select id, quando, status from agenda order by quando;"
```

Confirme que `quando` está entre `24h + 5min` e `24h + 35min` à frente, se a
antecedência for 24.

### O status não é `agendado`

O worker só pega `status = 'agendado'`. Se ficou `na_fila` de uma rodada
anterior que falhou, nunca mais entra na fila.

```sql
select status, count(*) from agenda group by status;
```

Corrigindo manualmente para testar:

```sql
update agenda set status='agendado' where id='SEU_ID';
```

### O beat não está disparando

```bash
docker compose logs worker | Select-String "Scheduler: Sending due task"
```

Deveria aparecer a cada 600s (10 min). Se não aparecer:

```bash
docker compose exec backend python -c "from app.worker.celery_app import celery_app; print(celery_app.conf.beat_schedule)"
```

Deveria listar `verificar-lembretes-a-cada-10-minutos`. Schedule vazio significa
que o worker subiu com uma instância do Celery diferente daquela que define o
beat — todos os módulos precisam importar de `app.worker.celery_app`.

### Redis fora

```
[Worker] Erro ao verificar lembretes: Error 111 connecting to redis:6379
```

```bash
docker compose logs redis
docker compose ps redis
```

---

## WhatsApp

### O QR Code expira

Esperado. O QR da Evolution dura pouco. Gere outro:

```bash
curl http://localhost:8000/api/conexao/qrcode -H "X-LZ-Token: $TOKEN"
```

Salve o `base64` como PNG e abra:

```bash
docker compose exec backend python -c "
import base64, os, requests
t = open('/app/.credenciais').read().split()[1]
r = requests.get('http://localhost:8000/api/conexao/qrcode', headers={'X-LZ-Token': t}, timeout=60)
b = r.json()['base64'].split('base64,',1)[1]
open('/app/qr.png','wb').write(base64.b64decode(b))
print('QR salvo em /app/qr.png')"
```

O arquivo também pode ser aberto direto no Windows, em
`backend/qr-barbearia.png`.

### `502` ao criar a instância

```bash
docker compose logs backend | Select-String "Erro ao criar instância"
```

Causas: `EVOLUTION_API_URL` errada, Evolution fora do ar, ou API key inválida.

```bash
docker compose exec backend python -c "
import os, requests
u = os.environ['EVOLUTION_API_URL'].rstrip('/')
h = {'apikey': os.environ['EVOLUTION_API_KEY']}
print(requests.get(u + '/', headers=h, timeout=15).text)"
```

Saudável: `{"status":200,"message":"Welcome to the Evolution API..."}`.

### A Evolution não entrega nada

```bash
docker compose exec backend python -c "
import os, requests
h = {'apikey': os.environ['EVOLUTION_API_KEY']}
u = os.environ['EVOLUTION_API_URL'].rstrip('/')
r = requests.get(u + '/instance/connectionState/LZ_SEU_TENANT', headers=h, timeout=15)
print(r.text)"
```

O estado precisa ser `open`. `connecting` significa que o QR não foi escaneado.

### Mensagem não chega no número

O telefone precisa estar **só com dígitos e com DDI**: `5592992030250`. O
`enviar_texto` remove não-dígitos, mas não adiciona o `55` que estiver faltando.

---

## Painel

### Ao recarregar a página, o token se perde

O token fica só no estado do React, sem `localStorage`. Recarregar desconecta.

Pior: o botão **Desconectar / Alterar Negócio** volta ao formulário inicial e
**cria uma conta nova** — e uma instância nova na Evolution — em vez de apenas
sair. Isso deixa órfãs na Evolution.

Guarde o token no console do navegador para recuperar:

```javascript
// leia o token antes de recarregar
copy(localStorage.getItem('token') ?? 'não salvo')
```

O token também está em `POST /api/contas` na resposta, ou em
`backend/.barbearia-credenciais` durante os testes.

### A configuração aparece sempre como barbearia

Não existe rota `GET` de configurações e o painel não carrega a config salva. Ao
salvar, o template personalizado é sobrescrito pelo padrão.

```bash
curl http://localhost:8000/api/conta -H "X-LZ-Token: $TOKEN"
```

O `config` mostra o que está realmente gravado.

> **Corrigido.** Agora existe `GET /api/configuracoes` e o painel reidrata o
> formulário ao carregar. Se você ainda vê barbearia, é navegador com cache antigo —
> recarregue com Ctrl+Shift+R.

### Importação de CSV não entra nada

Quatro causas, em ordem de probabilidade:

**Faltou a coluna de nome ou a de telefone.** O sistema precisa das duas para
reconhecer a planilha. A resposta traz `colunas_reconhecidas` com o que ele achou.

```bash
curl -H "X-LZ-Token: $TOKEN" -F "arquivo=@base.csv" \
  http://localhost:8000/api/clientes/importar
```

**O telefone veio sem o 9.** `2199998888` tem 10 dígitos e é recusado — em
telefone fixo não tem WhatsApp. O formato aceito é `55` + DDD + 9 dígitos + número.

**Bateu o limite do plano.** A resposta traz `excedente_limite` e
`limite_clientes`. A importação **para** no teto e devolve o que ficou de fora, em
vez de estourar o plano.

**A conta está suspensa.** A importação responde `402`. Veja
[seção Assinatura](#assinatura).

### Cliente sumido não entra na reativação

Quase sempre é porque `ultima_visita` está vazia. Cliente sem histórico **não é
considerado inativo** — não há como saber há quanto tempo não vem, e mandar "faz 90
dias" para quem acabou de ser cadastrado queima a credibilidade do número.

A tela tem o filtro **Sem histórico** para você ver exatamente quem são esses e
decidir o que fazer: cadastrar a data da última visita de cada um.

### "Conectado" aparece mesmo sem WhatsApp conectado

O cartão do painel é fixo no código — não consulta a Evolution. Use:

```bash
docker compose exec backend python -c "
import os, requests
h = {'apikey': os.environ['EVOLUTION_API_KEY']}
u = os.environ['EVOLUTION_API_URL'].rstrip('/')
print(requests.get(u + '/instance/connectionState/LZ_SEU_TENANT', headers=h, timeout=15).text)"
```

### Frontend não conecta na API

- CORS só libera `5173` e `3000`. Outro puerto precisa entrar em `allow_origins`.
- A URL da API está **hardcoded** em 4 pontos de `frontend/src/App.jsx`. Para
  apontar para outro host, use um proxy do Vite ou edite o código.
- `npm run dev` precisa estar rodando; o frontend não está no `docker-compose`.

> **Corrigido.** O painel agora chama a API por caminho relativo (`/api/...`), e em
> desenvolvimento quem resolve é o proxy do `vite.config.js`. Para apontar o dev
> para outro host, use `VITE_API_TARGET` — sem editar código.

---

## Assinatura

Sintomas de conta com assinatura bloqueada. O `402` é proposital: o frontend usa
esse status para abrir a tela de assinatura vencida em vez de mostrar erro.

### `402` ao marcar horário ou importar CSV

A conta está `suspensa`, `inadimplente` ou `cancelada`, **ou** o teste venceu.

```bash
curl -H "X-LZ-Token: $TOKEN" http://localhost:8000/api/assinatura
```

A resposta traz `status`, `acesso_liberado` e `mensagem_bloqueio`. Para saber o
motivo exato (não só o estado):

```bash
curl -H "X-LZ-Token: $TOKEN" http://localhost:8000/api/assinatura | python -m json.tool
```

O dono resolve pelo painel administrativo: **reativar** (30 dias), **liberar sem
prazo**, ou suspender de novo.

### A conta entrou em teste e o acesso não liga

`dias_teste = 0` cria a conta já como **inadimplente**, deliberadamente: sem teste
não há acesso. Para criar com acesso, mande `dias_teste: 14`.

### O webhook do Stripe não muda o status

Quatro causas, em ordem de probabilidade:

**Falta `STRIPE_WEBHOOK_SECRET`.** Sem ele a rota recusa a requisição com `400`, e
não valida nada. Copie o segredo de Stripe → Desenvolvedores → Webhooks.

**O evento não está marcado no endpoint do Stripe.** Confira se
`invoice.paid` e `invoice.payment_failed` estão na lista de eventos do webhook. Se
faltar o de falha, **a conta nunca é suspensa automaticamente** — que é o mais
importante dos dois.

**A URL não está alcançável.** Ela precisa ser pública e terminar em
`/api/admin/stripe/webhook`:

```bash
curl -X POST https://seudominio/api/admin/stripe/webhook   # deve devolver 400, não timeout
```

Um `400` de "Assinatura inválida" é sinal de que a rota está viva e o Stripe não
mandou a assinatura certa.

**Você está em modo teste.** Chave `sk_test_` só processa eventos de teste. Para
produção, use `sk_live_`.

Veja o log do backend a cada evento:

```bash
docker compose logs backend | grep stripe
```

### Suspender a conta não parou o envio

Suspender esvazia a fila pendente e barra o envio no worker. O que **não** para é
uma mensagem que já saiu da Evolution antes da suspensão — ela chega mesmo assim.
Espere alguns segundos.

### O Stripe está configurado mas o painel diz que não

O aviso âmbar **"Stripe não configurado"** compara com a variável de ambiente do
container, não com o painel:

```bash
docker compose exec backend printenv STRIPE_SECRET_KEY | head -c 8
```

Vazio? A chave não chegou. Confira se a linha existe no `.env` e rode
`docker compose up -d` — `restart` **não** relê o `.env**.

---

## Frontend

### `postcss` / Tailwind não aplica

O arquivo está com nome errado: **`frontend/postccs.config.js`**. O nome correto
é `postcss.config.js`. Além disso, o Tailwind instalado é v4, whose configuração é
feita por CSS (`@import "tailwindcss"`), e o `index.css` usa sintaxe v3
(`@tailwind base`).

O painel não depende disso — todo o CSS do `App.jsx` é inline.

### `Module not found: can't resolve './App.css'`

```bash
cd frontend && npm install
```

---

## Ruído esperado nos logs

Não são erros:

| Mensagem | Motivo |
|---|---|
| `DeprecationWarning: datetime.utcnow()` | Python 3.12 depreciou `utcnow`; ainda funciona |
| `404 Not Found` no `/healthz` | Tentativa antes do uvicorn subir |
| `Webhook não configurado` | `WEBHOOK_PUBLIC_URL` vazio |

---

## Limitações conhecidas

Não são bugs com conserto imediato — são funcionalidades ausentes. Ignorar
qualquer uma delas pode **banir seu número no WhatsApp**.

### Sem intervalo mínimo entre mensagens

Existe **limite diário por negócio** (`limite_por_dia`, padrão 50), mas ele só cobre
a campanha de reativação. O lembrete de agendamento não tem teto: marcar 200
horários para o mesmo dia faz o worker processar tudo em rajada, e o WhatsApp pode
tratar o número como spam.

Marcar aos poucos continua sendo a recomendação.

### Templates sem instrução de descadastro

O **descadastro automático existe**: responder `SAIR`, `PARAR` ou `NÃO QUERO` marca
o cliente com `opt_out` e ele nunca mais recebe — verificado no filtro da reativação,
no filtro do lembrete e numa barreira final antes do envio.

O que **não** existe é a frase pronta: os modelos padrão não trazem "responda SAIR
para não receber mais". Sem essa linha no texto, o cliente não descobre que pode
sair — e o descadastro que o sistema faz não serve de nada se ele nunca souber que
existe. Acrescente você mesmo às duas campanhas.

### Fila sem reprocessamento

Só existe uma task de envio imediato. Nada percorre a fila buscando itens
`pendentes`. Falha de envio deixa o item travado em `pendente` para sempre, e o
agendamento em `na_fila` também.

### `reagendando` não tem saída

O webhook só busca agendamentos com `status = 'agendado'`. Depois de `ADIAR`, um
`SIM` posterior responde
`Cliente registado, sem agendamento pendente` e não confirma nada.

### Janela de 30 minutos sem recuperar

Lembretes perdidos se o worker estava parado na janela. O protótipo antigo tinha
uma janela de recuperação; o rewrite perdeu.

### Fuso horário

O banco guarda UTC (`datetime.utcnow()`) e `{data}`/`{horario}` são renderizados
direto desse valor. Um horário marcado para 14h local pode aparecer como 18h na
mensagem ao cliente.

Este é o defeito mais provável de acontecer sem ninguém perceber, e o mais fácil de
corrigir agora: marque o horário **4 horas adiantado** em relação ao real e o texto
mostra a hora certa para o cliente.

### Depende de você registrar a visita

A reativação conta os dias desde `clientes.ultima_visita`. Esse campo é atualizado
em dois lugares: quando o cliente responde `SIM` e quando você clica em **Concluir**
no agendamento.

Se você atender pelo telefone e não marcar nada, o cliente continua parecendo
"sumido" e vai receber a reativação sem você querer. Clique em **Concluir**, ou
registre a visita direto na lista de clientes.

Quem veio da planilha sem data de preenchimento entra como **sem histórico**: fica
separado na tela e **não** entra na reativação, porque não há como saber há quanto
tempo não vem. Isso é proposital — mandar "faz 90 dias" para quem acabou de ser
cadastrado destrói a credibilidade do número.

### A reativação não personaliza o motivo

A mensagem não sabe **por que** o cliente sumiu. O texto é o mesmo para todos os
inativos, então não dá para variar o argumento por motivo (preço, mudança de
endereço, fechou por projeto). Dá para escrever uma mensagem mais genérica e deixar
a ligação para o time fazer em paralelo.

### Evolução não sincronizada

Você avisou que o QR expirou. Motivos possíveis, em ordem de probabilidade:

- O QR é gerado com `qrcode: True` e expira rápido; o cliente recai em
  `GET /instance/connect` que rotaciona a cada chamada.
- O celular e o computador podem estar em contas do WhatsApp diferentes.
- Escaneei a imagem antiga: gere outra na hora da leitura.

O QR mais estável para testar é o pairing via **código de oito dígitos**, que a
Evolution aceita em `/instance/connect` — ele não expira em segundos.

---

## Painel administrativo

O painel do proprietario fica em `/admin` do mesmo dominio. Operacao completa em
[PAINEL-ADMIN.md](PAINEL-ADMIN.md).

### `/admin` nao abre ou fica em branco

Confirme que a rota existe no HTML publicado:

```bash
curl -s https://seudominio/admin | grep -o 'src="[^"]*"'
```

Tem que devolver 200 com o `index.html` do painel. O vhost ja faz fallback de SPA
para qualquer caminho; se der 404, o `try_files` do nginx esta incompleto.

### "E-mail ou senha invalidos" com a senha certa

Proposital: login **nao** diferencia e-mail inexistente de senha errada, para nao
permitir enumerar contas. Se voce nunca criou o admin, rode:

```bash
docker compose exec backend python criar_admin.py
```

Rodar de novo com o mesmo e-mail **atualiza** a senha — e o caminho de recuperacao.

### Token de assinante nao abre `/admin`

Esperado, e e proposital. Os dois paineis usam headers diferentes:

| Sessao | Header | Chave no navegador |
|---|---|---|
| Assinante | `X-LZ-Token` | `token` |
| Proprietario | `X-LZ-Admin` | `lz_admin_token` |

Para testar a API do admin por `curl`:

```bash
ADMIN=$(curl -s -X POST http://localhost:8000/api/admin/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@seudominio.com","senha":"sua-senha"}' \
  | python -c "import json,sys; print(json.load(sys.stdin)['token'])")

curl -H "X-LZ-Admin: $ADMIN" http://localhost:8000/api/admin/metricas
```

### Nao consigo revogar o acesso de alguem

Use **Gerar novo token**, nao suspender. O novo token funciona e o anterior para na
hora, que e o que voce quer quando o token vazou.

**Suspender** corta o envio mas a pessoa continua entrando e lendo. **Apagar conta**
nao existe de proposito: perderia o historico de cobranca, e o cliente continuaria
existindo no Stripe.

### A busca de contas nao encontra o negocio

A busca ignora acento e maiuscula, mas nao cadastro parcial por telefone nem por
id. Para achar por id, use o filtro direto:

```bash
curl -H "X-LZ-Admin: $ADMIN" http://localhost:8000/api/admin/contas/<tenant_id>
```