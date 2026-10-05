#!/bin/sh
# Merge das chaves da Stripe no .env de PRODUCAO, preservando o que ja existe.
#
# Nao sobrescreve o arquivo inteiro: EVOLUTION_API_URL e WEBHOOK_PUBLIC_URL de
# producao estao corretos e um .env de desenvolvimento os quebraria. Este script
# troca apenas as linhas que precisam mudar e remove duplicatas.

set -e

ARQUIVO=/root/lembrazap/.env
NOVO=/tmp/stripe.env

if [ ! -f "$NOVO" ]; then
  echo "ERRO: /tmp/stripe.env nao existe" >&2
  exit 1
fi

# Remove linhas anteriores das chaves que estamos trazendo, para nao duplicar.
grep -vE '^(STRIPE_SECRET_KEY|STRIPE_WEBHOOK_SECRET|STRIPE_PRICE_ID_|STRIPE_PRECIO_|FRONTEND_URL)=' "$ARQUIVO" > /tmp/env.limpo

{
  echo ""
  echo "# --- Stripe: chaves e planos (enviados da maquina local) ---"
  echo "# Produto e preco recorrente sao criados pela API na primeira compra."
  echo "# STRIPE_PRICE_ID_ fica vazio de proposito: preenchido, sempre vence"
  echo "# sobre a criacao automatica."
  grep '^STRIPE_SECRET_KEY=' "$NOVO"
  grep '^STRIPE_WEBHOOK_SECRET=' "$NOVO"
  echo "STRIPE_PRICE_ID_STARTER="
  echo "STRIPE_PRICE_ID_PRO="
  echo "STRIPE_PRICE_ID_BUSINESS="
  echo "STRIPE_PRECIO_STARTER=4900"
  echo "STRIPE_PRECIO_PRO=9900"
  echo "STRIPE_PRECIO_BUSINESS=19900"
  # URL de producao. Com localhost aqui, o cliente pagaria e voltaria para a
  # maquina dele em vez de voltar para o painel.
  echo "FRONTEND_URL=https://lembrazap.aletheia.ia.br"
  echo ""
  echo "# --- Master user do painel administrativo ---"
  echo "# Senha vazia: o seed gera uma e mostra uma unica vez."
  echo "# Reexecutar o seed NUNCA sobrescreve a senha de um admin existente."
  echo "ADMIN_NOME=Proprietario"
  echo "ADMIN_SENHA="
} >> /tmp/env.limpo

mv /tmp/env.limpo "$ARQUIVO"
chmod 600 "$ARQUIVO"
shred -u "$NOVO" 2>/dev/null || rm -f "$NOVO"

echo "merge concluido"