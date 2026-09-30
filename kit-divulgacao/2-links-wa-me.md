# Links `wa.me` — mensagem pré-preenchida

Quando o dono de negócio clica no link, o WhatsApp dele já abre com uma mensagem
pronta pra você. Isso **qualifica** o lead (você já sabe de onde veio) e **quebra o
gelo** (a pessoa não precisa pensar no que escrever).

> ⚠️ **Troque o número.** Todos os links abaixo usam o placeholder `5511999999999`.
> Substitua pelo SEU número comercial no formato internacional: `55` + DDD + número,
> só dígitos, sem `+`, espaços ou traços. Ex.: `5511987654321`.

## Como o link é montado

```
https://wa.me/<NUMERO>?text=<MENSAGEM-CODIFICADA>
```

A mensagem precisa estar *URL-encoded* (espaço = `%20`, ç = `%C3%A7`, ã = `%C3%A3`…).
Os links abaixo **já estão codificados** — é só trocar o número.

## Link A — vem do anúncio (mensagem mais completa)

Mensagem que o lead envia: *"Olá! Vi o anúncio do LembraZap e quero entender como
ele pode recuperar clientes inativos no meu negócio."*

```
https://wa.me/5511999999999?text=Ol%C3%A1!%20Vi%20o%20an%C3%BAncio%20do%20LembraZap%20e%20quero%20entender%20como%20ele%20pode%20recuperar%20clientes%20inativos%20no%20meu%20neg%C3%B3cio.
```

## Link B — curto (Stories, bio do Instagram, botão)

Mensagem: *"Quero testar o LembraZap no meu negócio."*

```
https://wa.me/5511999999999?text=Quero%20testar%20o%20LembraZap%20no%20meu%20neg%C3%B3cio.
```

## Link C — indicação (quando alguém te indica a um dono de negócio)

Mensagem: *"Me indicaram o LembraZap pra automatizar o WhatsApp da minha empresa.
Pode me explicar?"*

```
https://wa.me/5511999999999?text=Me%20indicaram%20o%20LembraZap%20pra%20automatizar%20o%20WhatsApp%20da%20minha%20empresa.%20Pode%20me%20explicar%3F
```

## Onde usar cada um

| Onde | Link |
|---|---|
| Botão CTA do anúncio Meta Ads | A |
| Bio do Instagram / botão de Stories | B |
| Cartão de visita / QR code impresso | B |
| Mensagem de indicação enviada por um cliente | C |

## Gerar o seu próprio link (qualquer mensagem)

Se quiser trocar o texto, gere o link codificado sem erro. Opções:

- **Navegador (console):** `encodeURIComponent("sua mensagem aqui")` e cole depois de `?text=`.
- **Site pronto:** procure "wa.me link generator" (ex.: wa.me geradores online) — mas
  confira se o número fica no formato `55DDD...` sem `+`.

## Bônus — QR Code para o balcão

Transforme o Link B em QR (qualquer gerador de QR grátis) e imprima um adesivo pro
balcão do piloto: *"Chama no Zap e agende sem fila"*. É divulgação gratuita e
contínua dentro do estabelecimento do cliente.
