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

```bash
cd /root/lembrazap
docker compose exec backend python criar_admin.py
```

Ele pergunta o e-mail e a senha. Para não digitar interativamente (útil em
instalação automatizada):

```bash
docker compose exec \
  -e ADMIN_EMAIL=voce@seudominio.com.br \
  -e ADMIN_SENHA='uma-senha-forte-aqui' \
  -e ADMIN_NOME='Seu nome' \
  backend python criar_admin.py
```

O script imprime um token inicial, mas **você não precisa usá-lo**: ele existe só
caso queira chamar a API direto. Para usar o painel, basta abrir `/admin` e entrar
com e-mail e senha.

Rodar o script de novo com o mesmo e-mail **atualiza** a senha em vez de criar
duplicata. É o caminho de recuperação se esquecer a senha.

Trocar a senha depois de entrar também dá pelo próprio painel, e aí a senha atual é
exigida — se o token vazar, o atacante não troca a senha.

---

## 2. Ligar o Stripe

Sem nenhuma configuração o sistema funciona **por cobrança manual**: você marca a
conta como ativa, suspende ou estende o prazo à mão. Nada quebra.

Para cobrança automática por cartão, preencha no `.env`:

| Variável | Onde achar |
|---|---|
| `STRIPE_SECRET_KEY` | Stripe → Desenvolvedores → Chaves da API → *Secret key* (prefixo `sk_test_` em teste) |
| `STRIPE_WEBHOOK_SECRET` | Stripe → Desenvolvedores → Webhooks → criado o endpoint, o segredo aparece na URL de comando |
| `STRIPE_PRICE_ID_STARTER` | Stripe → Produtos → preço recorrente do Starter (`price_...`) |
| `STRIPE_PRICE_ID_PRO` | idem, do Pro |
| `STRIPE_PRICE_ID_BUSINESS` | idem, do Business |
| `FRONTEND_URL` | `https://lembrazap.aletheia.ia.br` |

Depois:

```bash
docker compose up -d
```

O painel mostra um aviso âmbar **"Stripe não configurado"** no topo enquanto as
chaves faltarem — é o sinal de que a cobrança ainda é manual.

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