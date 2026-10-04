# Manual do Usuário

Para o **dono do negócio**. Não precisa saber programar. Se algo travar, veja
[ERROS.md](ERROS.md) no final.

---

## O que este sistema faz

Você conecta o **seu próprio WhatsApp** ao painel. A partir daí, quando alguém
marca um horário, o sistema manda uma mensagem de lembrete antes do atendimento
e registra a resposta:

| O cliente responde | O que acontece |
|---|---|
| **SIM** | Horário vira **Confirmado** |
| **ADIAR** ou **REAGENDAR** | Horário fica **A Reagendar** para você combinar |
| outra coisa | A mensagem é registrada, o horário segue pendente |

O número é o seu, as mensagens saem do seu WhatsApp, e o cliente vê o nome do
seu negócio.

---

## 1. Criar sua conta

Na tela inicial, digite o **nome do seu negócio** e clique em
**Configurar WhatsApp**.

> **Guarde o token.** Ele só aparece uma vez e não tem como recuperar. Se perder,
> precisa criar outra conta.

---

## 2. Conectar seu WhatsApp

Aparece um **QR Code**. No celular:

1. Abra o **WhatsApp**
2. Toque nos **três pontinhos** (canto superior direito)
3. **Aparelhos conectados** → **Conectar aparelho**
4. Escaneie o QR Code da tela do computador

Se o QR tiver expirado, feche e abra a tela de novo para gerar outro. Eles
duram pouco tempo.

Depois de escanear, o WhatsApp fica vinculado como um "aparelho conectado" no
seu celular. Isso aparece em **Aparelhos conectados** e pode ser desconectado
dali mesmo.

> Deixe o celular e o computador na mesma conta do WhatsApp que atende os
> clientes. Separe número de atendimento do número pessoal é o ideal.

---

## 3. Ajustar o aviso

Na seção **Regras de Disparo Automático**:

**Antecedência do Lembrete** — quantas horas antes o aviso sai. `24` = um dia
antes. Se você atende com mais frequência, use `2` ou `3`.

**Modelo da Mensagem** — o texto que o cliente recebe. Escolha o **Tipo de
Negócio** para começar com um texto pronto e depois ajuste como quiser.

Os campos entre chaves são substituídos automaticamente:

| Escreva | Vira |
|---|---|
| `{nome}` | Nome do cliente |
| `{negocio}` | Nome do seu negócio |
| `{servico}` | Serviço marcado |
| `{data}` | Dia e mês (ex.: `21/10`) |
| `{horario}` | Hora (ex.: `17:00`) |

> **Cuidado:** escreva as chaves **exatamente** assim. Se você escrever
> `{nome do cliente}` ou deixar uma chave pela metade, o sistema não consegue
> montar a mensagem e **nenhum aviso sai** para nenhum cliente até você corrigir.
> Veja [ERROS.md](ERROS.md#a-mensagem-personalizada-quebrou).

Clique em **Guardar Alterações**.

---

## 4. Marcar um horário

Na seção **Novo Agendamento**:

- **Nome do Cliente** — como você chama a pessoa
- **Telefone (WhatsApp)** — **só números**, com DDI. Ex.: `5592992030250`.
  Sem o `55` o cliente não recebe nada.
- **Serviço** — ex.: `Corte + Barba`
- **Data e Hora** — o dia e a hora do atendimento

Clique em **Marcar Agendamento**.

O horário entra na lista e vira **Pendente**. Não precisa fazer mais nada: o
sistema avisa o cliente sozinho na antecedência que você configurou.

---

## 5. Acompanhar

A tabela mostra cada horário com uma etiqueta de estado:

| Etiqueta | Cor | Significado |
|---|---|---|
| **Pendente** | cinza | Marcado, ainda não chegou a hora do aviso |
| **Enviado** | azul | O aviso saiu, esperando resposta |
| **Confirmado** | verde | O cliente respondeu **SIM** |
| **A Reagendar** | amarelo | O cliente pediu para remarcar |

Quando aparecer **A Reagendar**, ligue para o cliente e combine o novo horário.

---

## Dicas

- **Comece com antecedência baixa.** Nas primeiras semanas, use 3 horas em vez de
  24 — você vê o aviso funcionando rápido e não incomoda o cliente com antecedência
  longa.
- **Não mande para a agenda inteira de uma vez.** Hoje o sistema **não tem limite
  diário de envios nem intervalo entre mensagens**. Se você disparar para 200
  clientes de uma vez, o WhatsApp pode bloquear o seu número. Marque os horários
  aos poucos e acompanhe.
- **Não mande para quem pediu para não receber.** O sistema ainda **não tem opção
  de descadastro**. Se alguém pedir para parar, anote fora do sistema e não o
  inclua nos próximos avisos.
- **Confira o telefone.** É o erro mais comum: número sem o `55` inicial é o
  motivo mais frequente de o cliente não receber nada.

---

## Privacidade

Quem recebe as mensagens é cliente do seu negócio — vale a política de
privacidade da LGPD. Os dados ficam no seu servidor e só o hash do seu token de
acesso é guardado.

Como o sistema **ainda não tem descadastro automático**, incorpore a instrução
de resposta no texto do aviso, por exemplo acrescentando ao final:

> *Responda SAIR para não receber mais mensagens.*

O sistema reconhece apenas `SIM`, `ADIAR` e `REAGENDAR` — a palavra `SAIR` ainda
não é tratada, mas o texto já deixa o cliente com a saída correta.

---

## Problemas

Os problemas mais comuns e como resolver:

| Sintoma | O que fazer |
|---|---|
| Cliente não recebeu nada | Confira o telefone com DDI. Veja se a antecedência já passou. |
| Nenhum aviso sai para ninguém | Seu texto da mensagem tem `{chave}` errada. Veja [ERROS.md](ERROS.md#a-mensagem-personalizada-quebrou). |
| Cliente respondeu e não mudou | O sistema não está recebendo as respostas. Veja [ERROS.md](ERROS.md#o-webhook-não-chega). |
| QR Code não funciona | Ele expira. Gere outro. |
| Painel mostra "Conectado" mas você nunca conectou | A tela mostra "Conectado" fixo, é um defeito conhecido. |

Lista completa em **[ERROS.md](ERROS.md)**.
