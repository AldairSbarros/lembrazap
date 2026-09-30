# LembraZap — protótipo

Micro-SaaS de remarketing por WhatsApp para negócios locais (salões, clínicas,
oficinas, estúdios). Cada conta conecta o **próprio número** de WhatsApp via QR
Code e usa duas automações:

1. **Reativação** — clientes sem visitar há N dias recebem mensagem personalizada (`{nome}`, `{negocio}`, `{dias}`).
2. **Lembrete de agenda** — compromissos cadastrados geram lembrete automático com a antecedência configurada.
3. **Resposta automática ao SIM** — quem responde SIM / quero / confirmo à campanha (em até 7 dias)
   recebe na hora o template de reserva, com prioridade máxima na fila, e ganha o selo
   "respondeu SIM" no painel — a lista de leads quentes do dono do negócio.
4. **Agendamento por IA** — se o cliente quente propuser dia e horário ("posso terça às 14h?"),
   o sistema extrai a data, reserva na agenda e confirma sozinho. Groq como primário e
   Gemini como fallback; sem chaves configuradas, usa um parser local (amanhã/hoje/dia da semana + hora).

Roda sobre a **mesma Evolution API** que o AletheIA já usa na VPS (instância
isolada por conta, padrão copiado da integração de produção). Sem banco: JSON em
disco com escrita atômica.

## Proteções embutidas (não remova)

- **Limite diário** de envios por conta (padrão 80) e **intervalo mínimo** entre
  mensagens (padrão 20 s) — WhatsApp bloqueia número que spamma.
- **Opt-out** automático: quem responde SAIR / PARAR / CANCELAR sai da base via
  webhook e tem os envios pendentes derrubados. Também há opt-out manual no painel.
- Toda mensagem padrão **inclui a instrução de opt-out** (exigência da política do
  WhatsApp e boa prática de LGPD).
- Token de conta: só o hash SHA-256 é persistido; o token é mostrado uma única vez.

## Estrutura

```
lembrazap/
  app.py            API + loops de fundo (fila de envio e agenda)
  evolution.py      cliente Evolution API v2 com MODO_SIMULACAO
  armazem.py        JsonStore (escrita atômica + lock)
  static/index.html painel sem build (Conexão, Clientes, Reativação, Agenda, Enviados, Config)
  dados/            JSON em disco (criado automaticamente)
```

## Rodar local (sem WhatsApp real)

```bash
pip install -r requirements.txt
MODO_SIMULACAO=1 python app.py        # http://localhost:8050
```

Em simulação o QR é fictício e os "envios" só aparecem no log e na aba Enviados
com o selo `(sim)` — dá para demonstrar o produto inteiro sem tocar em número real.

## Deploy na VPS (ao lado do AletheIA)

O passo a passo completo — upload, `.env`, build, bloco do OpenResty, teste com
WhatsApp real, backup cronado, atualização, rollback e troubleshooting — está em
**[DEPLOY_VPS.md](DEPLOY_VPS.md)**. Resumo:

1. Copie esta pasta para a VPS (ex.: `/root/lembrazap`).
2. `cp .env.example .env` e preencha `EVOLUTION_API_URL` / `EVOLUTION_API_KEY`
   com **os mesmos valores** do `docker-compose.yml` do AletheIA.
3. `WEBHOOK_PUBLIC_URL=https://aletheia.ia.br/lembrazap` (para opt-out e respostas).
4. `docker compose up -d --build` e confira `docker compose ps` (healthy).
5. Publique no OpenResty com `location /lembrazap/ { proxy_pass http://lembrazap:8050/; ... }`.
6. Abra `https://aletheia.ia.br/lembrazap/`, crie a conta piloto e conecte o WhatsApp pelo QR.

## Fluxo do piloto pagante

1. Conta criada no painel → token entregue ao cliente (ou você cria para ele).
2. Conexão → QR Code com o número do negócio.
3. Clientes → importar CSV da agenda atual dele.
4. Reativação → prévia com corte de 60/90 dias → disparar.
5. Agenda → cadastros novos; o lembrete sai sozinho.
6. Enviados → acompanhamento com status por mensagem.

## O que ficou de fora de propósito (v1)

- **Cobrança Stripe** — entre depois que 3-5 pilotos pagarem no pix/manual; o
  AletheIA já tem o padrão de checkout para copiar.
- Negociação conversacional completa com IA ("posso mais cedo?" → contraproposta
  de horários) — hoje a IA **extrai o horário proposto e reserva**; contrapropostas
  e remarcações ficam com o dono do negócio na conversa.
- Multi-usuário por conta, papéis, auditoria.
- Migração para banco — o JSON aguenta centenas de contas; migre quando doer.

## Variáveis de ambiente

| Variável | Efeito |
|---|---|
| `EVOLUTION_API_URL` / `EVOLUTION_API_KEY` | apontam para a Evolution API da VPS |
| `MODO_SIMULACAO` | `1` desliga qualquer chamada externa (demo/dev) |
| `WEBHOOK_PUBLIC_URL` | base pública para o webhook de opt-out |
| `DADOS_DIR` | onde os JSON ficam (volume no container) |
| `PORTA` | porta HTTP (padrão 8050) |
