# Kit de Divulgação — LembraZap

Material pronto para você **conseguir os primeiros pilotos pagantes** e para
**demonstrar o produto funcionando** na hora da venda.

Dois públicos, duas partes:

- **Parte 1 — vender o LembraZap (B2B).** Anúncios, link de WhatsApp e roteiro
  de fechamento para atrair e converter donos de negócio local (salão, barbearia,
  clínica, petshop, delivery…). É isso que gera receita.
- **Parte 2 — demo e arranque do piloto (in-produto).** Um CSV de clientes de
  mentira importável no LembraZap + os templates de mensagem prontos. Serve para
  você mostrar o produto rodando ao vivo na call de venda e para entregar o piloto
  já com copy no ar (o cliente não começa do zero).

## Arquivos

| Arquivo | Para quê |
|---|---|
| `1-anuncios-meta-ads.md` | Copys A/B de anúncio (Meta Ads → WhatsApp), segmentação e orçamento |
| `2-links-wa-me.md` | Links `wa.me` com mensagem pré-preenchida (já codificados) |
| `3-roteiro-fechamento-whatsapp.md` | Script de venda no WhatsApp: abertura → demo → objeções → preço → close |
| `drip/clientes-demo.csv` | Base de clientes fictícia para importar e demonstrar |
| `drip/templates-drip.md` | Mensagens Dia 0/3/7 + resposta ao SIM + confirmação, prontas para colar |

## Como usar (ordem sugerida)

1. **Defina 1 nicho** para os primeiros pilotos (ex.: barbearias da sua cidade).
   Falar com "salão" genérico converte menos do que falar com "barbeiro".
2. **Suba o anúncio A** (dor) com R$ 10–20/dia, raio de 5–10 km do nicho, destino
   = o link `wa.me` da Parte 1. Deixe 3–4 dias, leia as conversas que chegam.
3. **Atenda no WhatsApp com o roteiro** (`3-roteiro-fechamento-whatsapp.md`).
4. **Na call de demo**, importe o `clientes-demo.csv` (com o SEU número numa das
   linhas), dispare a reativação e mostre o fluxo SIM → IA → confirmação ao vivo.
5. **Fechou?** Entregue o piloto já com os `templates-drip.md` colados na aba
   Configuração e a base real do cliente importada.

## Nota de honestidade sobre o "drip"

O LembraZap hoje faz **campanha de reativação de tiro único** (um template
configurável enviado a quem está inativo há N dias) + **lembrete de agenda** +
**resposta automática ao SIM**. Não existe (ainda) um motor que dispare uma
sequência multi-toque sozinho. O "drip" deste kit é, portanto, uma **sequência de
templates** (Dia 0 → Dia 3 → Dia 7) que você rotaciona na aba Configuração e
redispara no segmento que continuou inativo. Automatizar essa rotação (via cron ou
uma feature de "cadência") é um próximo passo natural do produto — não está pronto.

## Antes de gastar em anúncio

- [ ] O deploy na VPS está no ar e o painel abre (`https://SEU-DOMINIO/lembrazap/`).
- [ ] Você conectou um número real e testou o fluxo ponta a ponta (item 6 do `DEPLOY_VPS.md`).
- [ ] Definiu preço do piloto (sugestão: R$ 67–97/mês + R$ 150–300 de implantação).
- [ ] Tem o link `wa.me` do SEU número comercial (troque o placeholder dos arquivos).
