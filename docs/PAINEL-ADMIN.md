# Painel do proprietário

Como operar as contas assinantes, a cobrança e o Stripe.

O painel fica em **`/admin`** do mesmo domínio do sistema:
<https://lembrazap.aletheia.ia.br/admin>.

Ele é separado do painel do assinante de propósito: header de sessão diferente,
chave de `localStorage` diferente, bundle separado. Um token de assinante não abre
o painel administrativo, e vice-versa.

---

## 1. Criar seu acesso (uma vez por instalação)

O admin não é uma conta de cliente — não tem base, não recebe disparo e não aparece
na lista de assinantes. Ele vive na tabela `admin_usuarios`.

### Seed (recomendado em deploy)

```bash
docker compose exec backend python seed.py
```

O seed lê `ADMIN_EMAIL`, `ADMIN_NOME` e `ADMIN_SENHA` do `.env`. Deixando a senha
**no `.env`**, e não como argumento na linha de comando, ela não fica no histórico
do shell nem aparece no `ps` da máquina.

Se `ADMIN_SENHA` estiver vazio, o seed gera uma senha aleatória e mostra **uma
única vez**.

Comandos:

| Comando | O que faz |
|---|---|
| `seed.py` | Garante o master user. Seguro para rodar a cada deploy |
| `seed.py --status` | Mostra o que existe. Não altera nada |
| `seed.py --demo` | Cria também uma conta de demonstração com 7 clientes |
| `seed.py --forcar-senha` | Reaplica `ADMIN_SENHA` mesmo se o admin já existe |

### A regra que importa

> **Reexecutar o seed nunca sobrescreve a senha de um admin que já existe.**

Um seed que resetasse a senha a cada deploy traria a conta de volta ao padrão de
fábrica em produção. Por isso `ADMIN_SENHA` só vale na primeira criação, ou com
`--forcar-senha`.

Se `ADMIN_SENHA` estiver definida e o seed a ignorar, ele **avisa** — porque essa é a
combinação que mais confunde: você troca a senha no `.env`, roda o seed achando que
aplicou, e o deploy seguinte volta à antiga.

### Vários administradores

Cada `ADMIN_EMAIL` diferente cria um acesso novo, e todos veem todas as contas. Para
um operador assistente, defina um `ADMIN_EMAIL` diferente e rode o seed de novo.

### Primeiro acesso manual (alternativa)

Se preferir digitar a senha no terminal em vez de deixá-la no `.env`:

```bash
docker compose exec backend python criar_admin.py
```

Ele pergunta o e-mail e a senha. Rodar de novo com o mesmo e-mail atualiza a senha —
é o caminho de recuperação se esquecer.

---

## 2. Ligar o Stripe

Sem nenhuma configuração o sistema funciona **por cobrança manual**: você marca a
conta como ativa, suspende ou estende o prazo à mão. Nada quebra.

Para cobrança automática por cartão, basta **uma variável**:

| Variável | Onde achar |
|---|---|
| `STRIPE_SECRET_KEY` | Stripe → Desenvolvedores → Chaves da API → *Secret key* (prefixo `sk_test_` em teste) |
| `STRIPE_WEBHOOK_SECRET` | Stripe → Desenvolvedores → Webhooks → criado o endpoint, o segredo aparece na URL de comando |
| `FRONTEND_URL` | `https://lembrazap.aletheia.ia.br` |

```bash
docker compose up -d
```

O painel mostra um aviso âmbar **"Stripe não configurado"** no topo enquanto a chave
faltar — é o sinal de que a cobrança ainda é manual.

### Você **não precisa** criar produto nenhum na Stripe

Essa era a dúvida mais comum na instalação, e a resposta é **não precisa**. Quando
alguém clica em **Assinar** e o plano ainda não tem preço, o sistema cria o produto e
o preço recorrente pela API da Stripe na hora, e abre o checkout. O cliente não vê
nada disso — paga e a assinatura ativa.

O `price_id` fica guardado em `planos_stripe`, então o produto é criado **uma vez por
plano**, não uma vez por venda. Antes de criar, o sistema também procura na Stripe por
`metadata['lembrazap_plano']`: se o banco for recriado, ele reencontra o produto em
vez de duplicar.

Para conferir o que existe:

```bash
docker compose exec backend python seed.py --status
```

Se você preferir fixar os preços à mão no painel da Stripe, defina
`STRIPE_PRICE_ID_STARTER`, `_PRO` e `_BUSINESS` no `.env` — essa configuração
**sempre vence** sobre a criação automática.

### Mudar o preço depois

> **Atenção:** na Stripe, preço é imutável. Quem assina hoje paga o preço gravado em
> `planos_stripe`. Mudar `planos.py` de R$ 99 para R$ 109 afeta **só quem assinar
> depois**.

O painel marca o plano como divergente quando o valor do catálogo não bate com o que
a Stripe está cobrando. Para gerar um preço novo:

```bash
curl -X POST http://localhost:8002/api/admin/planos/pro/sincronizar \
  -H "X-LZ-Admin: $ADMIN"
```

Isso cria um preço novo para os próximos assinantes. **Não move quem já está
assinado** — para isso é preciso editar o item de cada assinatura na Stripe
(*Assinaturas → Editar item → Atualizar preço*).

### Planos

Os preços e limites ficam em `backend/app/config/planos.py`:

| Plano | Preço | Clientes | Mensagens/mês |
|---|---|---|---|
| Starter | R$ 49 | 300 | 2.000 |
| Pro | R$ 99 | 1.000 | 8.000 |
| Business | R$ 199 | 3.000 | 25.000 |

Para mudar preço sem mexer no código, defina `STRIPE_PRECIO_*` no `.env` e
reinicie o container. O `.env` tem precedência sobre o arquivo.

### Webhook

Crie em **Stripe → Desenvolvedores → Webhooks** apontando para:

```
https://lembrazap.aletheia.ia.br/api/admin/stripe/webhook
```

Eventos que precisam estar marcados:

```
checkout.session.completed
invoice.paid
invoice.payment_failed
customer.subscription.updated
customer.subscription.deleted
```

Copie o **Segredo de assinatura** para `STRIPE_WEBHOOK_SECRET`. É ele que prova que a
requisição veio do Stripe — sem ele qualquer um poderia suspender suas contas
chamando a URL.

Teste o Stripe CLI:

```bash
stripe listen --forward-to localhost:8002/api/admin/stripe/webhook
stripe trigger invoice.payment_failed
```

---

## 3. O que o painel faz

**Visão geral** — total de contas, receita do mês, mensagens enviadas no mês,
quantas contas têm acesso e a distribuição por status.

**Contas** — lista com busca e filtro por status. Cada linha mostra plano, status,
total de clientes, clientes ativos, mensagens do mês e data de renovação.

**Detalhe de uma conta** — métricas, histórico de cobrança, base de clientes
(telefone mascarado) e as ações:

| Ação | Efeito |
|---|---|
| Trocar plano | Muda clientes e mensagens disponíveis |
| Suspender | Corta o envio agora e **esvazia a fila pendente** |
| Reativar 30 dias | Libera o acesso por 30 dias |
| Liberar sem prazo | Libera sem data de expiração |
| Gerar novo token | Invalida o token anterior de imediato |

**Nova conta** — cria a conta e mostra o token do cliente **uma única vez**. Use para
teste, cortesia ou venda presencial. Para venda com pagamento, use o checkout do
Stripe: ele já ativa o acesso sozinho depois da confirmação.

---

## 4. Como o bloqueio funciona

Conta suspensa ou inadimplente pode **entrar no painel e ler tudo o que é dela**,
mas não pode disparar. Três camadas verificam isso:

1. **API** — `POST /api/agendamentos`, `POST /api/teste-fila` e
   `POST /api/clientes/importar` devolvem `402`.
2. **Worker, na hora de enfileirar** — lembrete e reativação pulam a conta.
3. **Worker, na hora de enviar** — o envio é barrado mesmo que a mensagem tenha sido
   enfileirada **antes** da suspensão. A fila tem latência, então checar só no
   enfileiramento deixaria passar mensagens de conta suspensa.

O webhook do WhatsApp **não** é bloqueado: mesmo com a conta suspensa, o `SAIR` de um
cliente precisa continuar sendo registrado, e concluir uma visita precisa zerar o
contador.

---

## 5. O que o sistema **não** faz

- **Não apaga conta.** Só suspende. Apagar perderia o histórico de cobrança e o
  cliente continuaria existindo no Stripe. Para revogar o acesso, suspenda ou gere
  um novo token.
- **Não mostra telefone completo** no painel admin. Serve para suporte, não para
  exportar contatos.
- **Não emite nota fiscal.**
- **Não manda SMS nem e-mail** de cobrança. A cobrança automática é do Stripe; o
  cliente recebe o e-mail do próprio Stripe.
- **Não há relatório financeiro** além da receita do mês. Para lucro, use o painel do
  Stripe, que é a fonte da verdade do que foi cobrado de fato.