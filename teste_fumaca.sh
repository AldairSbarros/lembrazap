#!/usr/bin/env bash
# Teste de fumaça do LembraZap em modo simulação (roda contra 127.0.0.1:8050).
set -euo pipefail
BASE=http://127.0.0.1:8050
PY="C:/Users/aldai/AppData/Local/Programs/Python/Python312/python.exe"
JQ() { "$PY" -c "import sys,json; d=json.load(sys.stdin); print($1)"; }

echo "== 1. criar conta"
RESP=$(curl -s -X POST $BASE/api/contas -H 'Content-Type: application/json' \
  -d '{"nome":"Studio Bella","negocio":"salao de beleza"}')
TOKEN=$(echo "$RESP" | JQ "d['token']")
TID=$(echo "$RESP" | JQ "d['tenant_id']")
echo "tenant=$TID token=${TOKEN:0:8}..."
H="X-LZ-Token: $TOKEN"

echo "== 2. conta autenticada"
curl -s $BASE/api/conta -H "$H" | JQ "f\"nome={d['nome']} simulacao={d['simulacao']}\""

echo "== 3. conexao (criar + qrcode + status)"
curl -s -X POST $BASE/api/conexao/criar -H "$H" | JQ "f\"instancia={d['instancia']} ja_existia={d['ja_existia']}\""
curl -s $BASE/api/conexao/qrcode -H "$H" | JQ "f\"qr_base64_prefix={d['base64'][:30]}\""
curl -s $BASE/api/conexao/status -H "$H" | JQ "f\"conectado={d['conectado']} estado={d['estado']}\""

echo "== 4. acelerar fila (intervalo 1s) e importar CSV"
curl -s -X PUT $BASE/api/configuracao -H "$H" -H 'Content-Type: application/json' \
  -d '{"intervalo_seg":1}' | JQ "f\"intervalo={d['config']['intervalo_seg']}\""
curl -s -X POST $BASE/api/clientes/importar -H "$H" -H 'Content-Type: application/json' \
  -d '{"csv":"nome;telefone;ultima_visita;obs\nMaria Silva;11 98765-4321;10/05/2026;prefere manha\nJoao Souza;11 91234-5678;20/09/2026;\nAna Lima;21 99887-7665;01/03/2026;"}' \
  | JQ "f\"importados={d['importados']} ignorados={d['ignorados']}\""

echo "== 5. previa de reativacao (60 dias)"
curl -s "$BASE/api/reativacao/preview?dias=60" -H "$H" | JQ \
  "'; '.join(f\"{c['nome']}:{c['dias_sem_visitar']}d\" for c in d['elegiveis'])"

echo "== 6. disparar campanha"
curl -s -X POST $BASE/api/reativacao/disparar -H "$H" -H 'Content-Type: application/json' \
  -d '{"dias":60}' | JQ "f\"enfileirados={d['enfileirados']}\""

echo "== 7. compromisso na agenda (daqui a 1h => dentro da janela de 24h)"
QUANDO=$("$PY" -c "from datetime import datetime,timedelta; print((datetime.now()+timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M'))")
curl -s -X POST $BASE/api/agenda -H "$H" -H 'Content-Type: application/json' \
  -d "{\"telefone\":\"11 98765-4321\",\"quando\":\"$QUANDO\",\"nome\":\"Maria Silva\"}" | JQ "f\"status={d['item']['status']}\""

echo "== 8. aguardando loops (fila 5s / agenda 20s)..."
sleep 30

echo "== 9. log de envios"
curl -s "$BASE/api/envios" -H "$H" | JQ \
  "'; '.join(f\"{e['campanha']}:{e['status']}{'(sim)' if e['simulado'] else ''}\" for e in d['envios'])"

echo "== 10. webhook de opt-out (Maria responde SAIR)"
curl -s -X POST $BASE/webhook/evolution/$TID -H 'Content-Type: application/json' \
  -d '{"event":"messages.upsert","data":{"key":{"remoteJid":"5511987654321@s.whatsapp.net","fromMe":false},"message":{"conversation":"quero SAIR por favor"}}}' \
  | JQ "f\"acao={d['acao']} clientes={d['clientes']}\""

echo "== 11. base apos opt-out"
curl -s $BASE/api/clientes -H "$H" | JQ \
  "'; '.join(f\"{c['nome']}:opt_out={c['opt_out']}\" for c in d['clientes'])"

echo "== 12. envios pendentes derrubados?"
curl -s "$BASE/api/envios?status=opt_out" -H "$H" | JQ "f\"opt_out_na_fila={len(d['envios'])}\""

echo "== 13. Ana responde SIM a campanha recente"
curl -s -X POST $BASE/webhook/evolution/$TID -H 'Content-Type: application/json' \
  -d '{"event":"messages.upsert","data":{"key":{"remoteJid":"5521998877665@s.whatsapp.net","fromMe":false},"message":{"conversation":"Sim, quero agendar"}}}' \
  | JQ "f\"acao={d['acao']} auto={d['auto']}\""

echo "== 14. segundo SIM nao gera segunda resposta automatica"
curl -s -X POST $BASE/webhook/evolution/$TID -H 'Content-Type: application/json' \
  -d '{"event":"messages.upsert","data":{"key":{"remoteJid":"5521998877665@s.whatsapp.net","fromMe":false},"message":{"conversation":"sim"}}}' \
  | JQ "f\"acao={d['acao']} auto={d['auto']}\""

echo "== 15. mensagem longa com 'sim' no meio nao dispara (anti falso positivo)"
curl -s -X POST $BASE/webhook/evolution/$TID -H 'Content-Type: application/json' \
  -d '{"event":"messages.upsert","data":{"key":{"remoteJid":"5511912345678@s.whatsapp.net","fromMe":false},"message":{"conversation":"oi tudo bem? eu estava pensando se talvez sim mas preciso ver com meu marido antes de decidir qualquer coisa essa semana"}}}' \
  | JQ "f\"acao={d['acao']}\""

echo "== 16. aguardando fila prioritaria..."
sleep 8
curl -s "$BASE/api/envios?status=enviado" -H "$H" | JQ \
  "'; '.join(f\"{e['campanha']}:{e['status']}\" for e in d['envios'])"
curl -s $BASE/api/clientes -H "$H" | JQ \
  "'; '.join(f\"{c['nome']}:respondeu={bool(c.get('respondeu_em'))}\" for c in d['clientes'])"

echo "== 17. Ana (cliente quente) propoe horario: IA reserva e confirma"
curl -s -X POST $BASE/webhook/evolution/$TID -H 'Content-Type: application/json' \
  -d '{"event":"messages.upsert","data":{"key":{"remoteJid":"5521998877665@s.whatsapp.net","fromMe":false},"message":{"conversation":"posso amanha as 15:00, funciona?"}}}' \
  | JQ "f\"acao={d['acao']} quando={d.get('quando','')} fonte={d.get('fonte','')}\""

echo "== 18. agenda tem o compromisso com origem ia"
curl -s $BASE/api/agenda -H "$H" | JQ \
  "'; '.join(f\"{i['nome']}:{i['quando']}:{i['status']}:origem={i.get('origem','manual')}\" for i in d['agenda'])"

echo "== 19. mensagem sem horario nao reserva nada"
curl -s -X POST $BASE/webhook/evolution/$TID -H 'Content-Type: application/json' \
  -d '{"event":"messages.upsert","data":{"key":{"remoteJid":"5521998877665@s.whatsapp.net","fromMe":false},"message":{"conversation":"sera que voces atendem por aqui?"}}}' \
  | JQ "f\"acao={d['acao']}\""

echo "== 20. confirmacao da reserva sai na fila prioritaria"
sleep 8
curl -s "$BASE/api/envios?status=enviado" -H "$H" | JQ \
  "'; '.join(f\"{e['campanha']}:{e['status']}\" for e in d['envios'] if e['campanha']=='ia-confirmacao')"
curl -s $BASE/healthz | JQ "f\"healthz ok={d['ok']}\""
echo "== FIM OK"
