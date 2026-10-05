# Manual do Usuário

Para o **dono do negócio**. Não precisa saber programar. Se algo travar, veja
[ERROS.md](ERROS.md) no final.

---

## O que este sistema faz

Você conecta o **seu próprio WhatsApp** ao painel. A partir daí, duas campanhas
saem sozinhas, todo dia:

| Campanha | Para quem | Quando |
|---|---|---|
| **Lembrete de horário** | quem tem consulta marcada | X horas antes, como você configurar |
| **Reativação** | quem sumiu da sua base | uma vez por dia, a partir de N dias sem vir |

O número é o seu, as mensagens saem do seu WhatsApp, e o cliente vê o nome do seu
negócio no texto.

### O que o cliente responde

| O cliente responde | O que acontece |
|---|---|
| **SIM** | Horário vira **Confirmado** e zera a contagem de dias sem vir |
| **ADIAR** ou **REAGENDAR** | Horário fica **A Reagendar** para você combinar |
| **SAIR** ou **PARAR** | Cliente é marcado e **nunca mais** recebe nada, nem se você quiser |
| outra coisa | A mensagem é registrada, o horário segue pendente |

---

## 1. Criar sua conta

Na tela inicial, digite o **nome do seu negócio** e clique em
**Configurar WhatsApp**.

> **Guarde o token.** Ele só aparece uma vez e não tem como recuperar. Se perder,
> peça um novo ao suporte — o anterior deixa de funcionar na hora.

---

## 2. Conectar seu WhatsApp

Aparece um **QR Code**. No celular:

1. Abra o **WhatsApp**
2. Toque nos **três pontinhos** (canto superior direito)
3. **Aparelhos conectados** → **Conectar aparelho**
4. Escaneie o QR Code da tela do computador

Se o QR tiver expirado, feche e abra a tela de novo para gerar outro. Eles duram
pouco tempo.

Depois de escanear, o WhatsApp fica vinculado como um "aparelho conectado" no seu
celular. Isso aparece em **Aparelhos conectados** e pode ser desconectado dali mesmo.

> Deixe o celular e o computador na mesma conta do WhatsApp que atende os clientes.
> Separar número de atendimento do número pessoal é o ideal.

---

## 3. Trazer sua base de clientes

**Esta é a parte que mais muda o resultado.** Sem a base, a campanha de reativação
não tem de quem se despedir.

Vá em **Base de Clientes** e escolha uma das duas formas:

### Opção A — Importar sua planilha (recomendado para quem já tem ficha)

Clique em **Importar CSV** e suba o arquivo que você já usa para controlar a agenda.

O sistema reconhece os cabeçalhos mais comuns, então quase sempre a planilha serve
sem edição:

| Dado | Cabeçalhos aceitos |
|---|---|
| Nome | `nome`, `cliente`, `nome do cliente`, `nome completo` |
| Telefone | `telefone`, `celular`, `whatsapp`, `fone`, `contato`, `numero` |
| Última visita | `ultima visita`, `ultimo atendimento`, `data`, `visita` |
| Observação | `obs`, `observacao`, `nota`, `anotacao` |

Nada sensíveis a maiúsculas ou acentos: `Nome do Cliente`, `NOME` e `nome do
cliente` funcionam igual. Planilha separada por `;` (que é o padrão do Excel
brasileiro) também é detectada sozinha.

**Precisa ter pelo menos a coluna de nome e a de telefone.** Sem as duas, o sistema
avisa quais colunas encontrou e não importa.

Detalhes que evitam surpresa:

- **Linha suja não derruba a importação.** Telefone inválido ou linha sem nome são
  pulados e listados no relatório do que ficou de fora, com o motivo.
- **Telefone repetido é unido, não duplicado.** Planilha de histórico repete o
  contato o tempo todo; o sistema prefere a linha que traz o nome e a data mais
  recente.
- **Data que não dá para ler vira "sem histórico"**, nunca uma data errada. Cliente
  sem histórico aparece separado na tela, porque você ainda não sabe há quanto tempo
  ele não vem.
- **Celular com 11 dígitos (com o 9) só.** Telefone fixo de 8 dígitos é recusado:
  WhatsApp no Brasil é só celular. Não adianta um número entrar como "importado" e
  falhar só na hora de mandar.

Se não tiver planilha, baixe o modelo com o botão **baixar modelo** ao lado do botão
de importar.

### Opção B — Cadastrar um a um

Para quem está começando. Na mesma tela, use **Novo Cliente** com nome, telefone e,
se souber, a data da última visita.

Depois de cadastrar a base, dá para filtrar em **Todos**, **Inativos** (sumiu há mais
de N dias), **Sem histórico** (veio da planilha e ninguém atualizou) ou **Não
recebem** (pediu para sair).

> **Registrar visita é o que faz a reativação funcionar.** O sistema conta os dias
> desde a última visita. Cliente que você atendeu e não registrou continua parecendo
> sumido e vai receber a mensagem de reativação sem você querer. Use o botão
> **Concluir** no agendamento, ou registre a visita direto na lista de clientes.

---

## 4. Configurar as duas campanhas

Na seção **Regras de Disparo Automático** você configura as duas campanhas
separadamente, cada uma com seu texto.

### Campanha 1 — Lembrete de horário

**Antecedência** — quantas horas antes o aviso sai. `24` = um dia antes. Se você
atende com mais frequência, use `2` ou `3`.

**Modelo da mensagem** — o texto do lembrete. Escolha o **Tipo de Negócio** para
começar com um texto pronto e depois ajuste.

### Campanha 2 — Reativação

Ligue o botão **Reativar clientes inativos** e ajuste:

| Campo | O que faz | Padrão |
|---|---|---|
| **Dias sem visitar** | a partir de quantos dias o cliente entra na lista | 45 |
| **Mensagem de reativação** | o texto do "sentimos sua falta" | — |
| **Limite por dia** | máximo de mensagens por dia | 50 |

Roda **uma vez por dia, à meia-noite**. Quem já recebeu hoje não recebe de novo.

### Os campos entre chaves

Funcionam nas duas campanhas e são substituídos automaticamente:

| Escreva | Vira |
|---|---|
| `{nome}` | Nome do cliente |
| `{negocio}` | Nome do seu negócio |
| `{servico}` | Serviço marcado (só no lembrete) |
| `{data}` | Dia e mês (ex.: `21/10`) |
| `{horario}` | Hora (ex.: `17:00`) |
| `{dias}` | Quantos dias sem vir (só na reativação) |

> **Cuidado:** escreva as chaves **exatamente** assim. Se você escrever
> `{nome do cliente}` ou deixar uma chave pela metade, o sistema avisa ao salvar e
> **não aplica** — nenhum aviso sai para ninguém até você corrigir.

Clique em **Guardar Alterações**.

---

## 5. Marcar um horário

Na seção **Novo Agendamento**:

- **Nome do Cliente** — como você chama a pessoa
- **Telefone (WhatsApp)** — **só números**, com DDI. Ex.: `5592992030250`.
  Sem o `55` o cliente não recebe nada.
- **Serviço** — ex.: `Corte + Barba`
- **Data e Hora** — o dia e a hora do atendimento

Clique em **Marcar Agendamento**. O horário entra na lista e vira **Pendente**.

---

## 6. Acompanhar

A tabela mostra cada horário com uma etiqueta de estado:

| Etiqueta | Cor | Significado |
|---|---|---|
| **Pendente** | cinza | Marcado, ainda não chegou a hora do aviso |
| **Enviado** | azul | O aviso saiu, esperando resposta |
| **Confirmado** | verde | O cliente respondeu **SIM** |
| **A Reagendar** | amarelo | O cliente pediu para remarcar |
| **Concluído** | verde-escuro | Atendimento feito; zera a contagem de dias sem vir |

Quando aparecer **A Reagendar**, ligue para o cliente e combine o novo horário.

Clique em **Concluir** depois do atendimento: é isso que zera o contador de dias do
cliente e tira ele da lista de reativação.

---

## Quem para de receber

Cliente que responde **SAIR**, **PARAR** ou **NÃO QUERO** é marcado e nunca mais
recebe disparo. Isso vale para as duas campanhas.

Para marcar à mão, use o botão **Não recebe** na lista de clientes — útil quando
alguém pede para parar pelo telefone, sem ter mandado nada no WhatsApp.

> Coloque a instrução de saída no texto das suas campanhas. A marcação é
> automática, mas o cliente precisa saber que pode.:
>
> *Responda SAIR para não receber mais mensagens.*

---

## Privacidade

Quem recebe as mensagens é cliente do seu negócio — vale a política de privacidade
da LGPD. Os dados ficam no servidor e só o hash do seu token de acesso é guardado.

Você é dono da sua base: pode buscar, editar e remover qualquer cliente a qualquer
momento, e o sistema não manda para quem pediu para sair.

---

## Dicas

- **Comece com antecedência baixa.** Nas primeiras semanas, use 3 horas em vez de 24
  — você vê o aviso funcionando rápido e não incomoda o cliente.
- **Cadastre a base antes de ligar a reativação.** Sem cliente com histórico
  registrado, a campanha não encontra ninguém.
- **Registre a visita de quem você atendeu.** É o que mantém a lista de reativação
  honesta.
- **Não mande para a agenda inteira de uma vez.** Existe limite diário, mas ele se
  refere à reativação. Marcar 200 horários para o mesmo dia ainda pode fazer o
  WhatsApp reclamar. Marque aos poucos.
- **Confira o telefone.** É o erro mais comum: número sem o `55` inicial é o motivo
  mais frequente de o cliente não receber nada.

---

## Seu plano

O plano define **quantos clientes** você pode ter e **quantas mensagens por mês**:

| Plano | Clientes | Mensagens/mês |
|---|---|---|
| Starter | 300 | 2.000 |
| Pro | 1.000 | 8.000 |
| Business | 3.000 | 25.000 |

A tela de clientes mostra quanto você já usou. Ao passar do limite de clientes, o
sistema **para a importação** e avisa quantas linhas ficaram de fora — não importa
metade do arquivo e deixa você descobrir depois.

Se a assinatura vencer ou for suspensa, você continua **entrando no painel e lendo
tudo**, mas o sistema para de enviar mensagens e de marcar novos horários, e uma
tela explica o motivo.

---

## Problemas

Os problemas mais comuns e como resolver:

| Sintoma | O que fazer |
|---|---|
| Cliente não recebeu nada | Confira o telefone com DDI. Veja se a antecedência já passou. |
| Nenhum aviso sai para ninguém | Seu texto da mensagem tem `{chave}` errada. Veja [ERROS.md](ERROS.md#a-mensagem-personalizada-quebrou). |
| Cliente recebeu mensagem de reativação sem querer | Você atendeu e não registrou a visita. Use **Concluir**. |
| Reativação não encontra ninguém | Falta a data da última visita. Na importação, preencha a coluna de data. |
| Importação não aceitou o arquivo | Faltou a coluna de nome ou de telefone. O sistema diz quais encontrou. |
| Telefone fixo foi recusado | WhatsApp no Brasil é só celular. Use o celular do cliente. |
| Cliente respondeu e não mudou | O sistema não está recebendo as respostas. Veja [ERROS.md](ERROS.md#o-webhook-não-chega). |
| Não consigo marcar horário | Sua assinatura pode estar vencida. Veja a tela de assinatura. |
| QR Code não funciona | Ele expira. Gere outro. |
| Painel mostra "Conectado" mas você nunca conectou | A tela mostra "Conectado" fixo, é um defeito conhecido. |

Lista completa em **[ERROS.md](ERROS.md)**.