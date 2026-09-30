# Templates do Drip — prontos para colar no LembraZap

Estas são as mensagens que o sistema envia. Cole na aba **Configuração** do painel
nos campos indicados. As variáveis `{nome}`, `{negocio}` e `{dias}` são preenchidas
sozinhas pelo LembraZap (o `{nome}` vira só o primeiro nome).

> **Compliance:** toda mensagem de reativação termina com a opção de saída
> ("responda SAIR"). Não remova — é o que mantém o número do seu cliente vivo e é
> exigência do WhatsApp. O opt-out é automático (o sistema para de enviar pra quem
> responder SAIR/PARAR/CANCELAR).

---

## Sequência de reativação (rotação manual)

O LembraZap dispara **uma** campanha por vez. A cadência abaixo é você trocando o
template e redisparando no segmento que **continuou inativo**. Sugestão de ritmo:

| Toque | Quando | Para quem | Template |
|---|---|---|---|
| **Dia 0** | primeiro disparo | inativos há 60+ dias | Reativação 1 |
| **Dia 3** | 3 dias depois | quem **não respondeu** o Dia 0 | Reativação 2 (reforço leve) |
| **Dia 7** | 7 dias depois | quem ainda não respondeu | Reativação 3 (última chamada + isca) |

> Como redisparar só pra quem não respondeu: hoje o filtro é manual — dispare o
> Dia 3 com um corte maior (ex.: 63 dias) ou exporte/reimporte a base tirando quem
> já respondeu (a aba Clientes mostra o selo "respondeu SIM"). Automatizar essa
> cadência é um próximo passo do produto (veja a nota no `README.md` do kit).

### Reativação 1 — Dia 0 (campo `template_reativacao`)

```
Oi, {nome}! Tudo bem? Aqui é da {negocio} 👋
Sentimos sua falta — já faz {dias} dias desde a sua última visita.
Que tal agendar um horário esta semana? É só responder SIM que eu já reservo pra você.
(Se preferir não receber mais mensagens, é só responder SAIR.)
```

### Reativação 2 — Dia 3 (reforço, sem ser chato)

```
Oi, {nome}! Passando rapidinho 😊
A agenda da {negocio} desta semana ainda tem alguns horários livres.
Quer que eu guarde um pra você? Responde SIM e me diz o melhor dia.
(Para não receber mais, responda SAIR.)
```

### Reativação 3 — Dia 7 (última chamada + isca)

```
{nome}, é a última vez que te chamo, prometo 🙏
Deixei um mimo pra você na {negocio}: [10% off / serviço extra grátis] voltando esta semana.
Topa? Responde SIM que eu já deixo seu horário reservado.
(Se não quiser mais receber, responda SAIR.)
```

> Preencha a isca `[...]` com a oferta real do cliente (desconto, brinde, serviço
> extra). É o que destrava quem ignorou os dois primeiros toques.

---

## Resposta automática ao SIM (campo `template_resposta_sim`)

Quando o cliente responde SIM, o sistema manda isto **na hora**, com prioridade:

```
Que bom te ver de volta, {nome}! 🎉
Me diz o dia e o horário que ficam melhores pra você que eu já deixo reservado aqui na {negocio}.
Pode escrever natural, tipo "amanhã às 15h" ou "sábado de manhã".
```

## Confirmação de agendamento (campo `template_confirmacao`)

Depois que a IA entende o horário proposto, o sistema confirma e cria o compromisso
na agenda (com lembrete automático antes):

```
Perfeito, {nome}! ✅
Seu horário ficou reservado para {quando} aqui na {negocio}.
Você recebe um lembrete antes do compromisso. Qualquer remarcação, é só responder por aqui.
```

---

## Lembrete de compromisso (campo `template_lembrete`)

Enviado automaticamente com a antecedência configurada (padrão 24h) para quem tem
horário na agenda:

```
Oi, {nome}! Passando pra lembrar do seu compromisso em {quando} aqui na {negocio} 🙂
Precisa remarcar? É só responder por aqui.
(Para não receber mais mensagens, responda SAIR.)
```

---

## Dicas de copy que convertem mais

- **Primeiro nome sempre.** `{nome}` já faz isso — aumenta resposta.
- **Pergunta fechada no fim** ("Quer que eu guarde um horário?") responde mais que
  texto aberto.
- **Uma isca no Dia 7** (desconto/brinde) destrava quem ignorou os dois primeiros.
- **Emoji com moderação** (1–2 por mensagem) humaniza sem parecer spam.
- **Mensagem curta.** No WhatsApp, 2–4 linhas é o teto. Textão ninguém lê.
- **Teste A/B:** rode a Reativação 1 com e sem emoji, ou com pergunta vs. afirmação,
  e veja qual gera mais "SIM" na aba Clientes.

## O que medir (aba Enviados / Clientes)

- **Taxa de resposta SIM** = respondentes ÷ disparados. Bom: 10–25% em base quente.
- **Opt-outs** = quantos responderam SAIR. Se passar de ~5%, o texto está agressivo
  demais ou a base é fria.
- **Agendamentos via IA** = selo "via IA" na aba Agenda. É o resultado que vende o
  produto pro seu cliente — mostre esse número na renovação do piloto.
