"""Confere que a fila do worker não envia para conta suspensa nem inadimplente.

Testa a barreira de cobrança no momento do envio, que é separada das demais: uma
mensagem pode ter sido enfileirada antes da suspensão e só ser despachada depois.

    python _teste_worker_bloqueio.py
"""

import sys

from app.db.database import SessionLocal
from app.db.models import FilaEnvio, Tenant
from app.services import evolution
from app.worker.tasks import processar_item_fila

falhas = []

# Substitui o envio real: o teste é sobre a barreira, não sobre a Evolution.
enviados = []
evolution.enviar_texto = lambda instancia, telefone, texto: enviados.append(
    (instancia, telefone, texto)
) or {"ok": True, "simulado": True}


def conferir(rotulo, condicao, detalhe=""):
    marca = "ok  " if condicao else "FALHA"
    print(f"  {marca} {rotulo}" + (f"  -> {detalhe}" if detalhe else ""))
    if not condicao:
        falhas.append(rotulo)


def fila_para(tenant, telefone="5592992030250"):
    return FilaEnvio(
        tenant_id=tenant.id,
        telefone=telefone,
        texto="mensagem de teste",
        campanha="teste_bloqueio",
        status="pendente",
    )


db = SessionLocal()
try:
    print("== envio barrado para conta suspensa ==")
    tenant = db.query(Tenant).filter(Tenant.id == "74cb708ed4d7").first()
    if not tenant:
        sys.exit("Conta de teste 74cb708ed4d7 nao encontrada.")

    status_original = tenant.status
    assinatura_original = tenant.assinatura_ativa
    try:
        tenant.status = "suspenso"
        tenant.assinatura_ativa = False
        db.commit()

        fila = fila_para(tenant)
        db.add(fila)
        db.commit()

        processar_item_fila.run(fila.id)

        db.refresh(fila)
        conferir("nada foi enviado", not enviados, f"{len(enviados)} envio(s)")
        conferir("item marcado como falha", fila.status == "falha", fila.status)
        conferir(
            "motivo registra o bloqueio",
            "bloqueado" in (fila.erro or "").lower(),
            (fila.erro or "")[:60],
        )
        db.delete(fila)
        db.commit()

        print("\n== envio liberado quando assinatura esta ativa ==")
        enviados.clear()
        tenant.status = status_original
        tenant.assinatura_ativa = assinatura_original
        db.commit()

        fila = fila_para(tenant)
        db.add(fila)
        db.commit()
        processar_item_fila.run(fila.id)
        db.refresh(fila)

        conferir("envio saiu", len(enviados) == 1, f"{len(enviados)} envio(s)")
        conferir("item marcado como enviado", fila.status == "enviado", fila.status)
        db.delete(fila)
        db.commit()

        print("\n== opt-out continua prevalecendo sobre assinatura ativa ==")
        enviados.clear()
        from app.db.models import Cliente

        cliente = Cliente(tenant_id=tenant.id, nome="OptOut Teste", telefone="5511999990000", opt_out=True)
        db.add(cliente)
        db.commit()

        fila = fila_para(tenant, "5511999990000")
        fila.cliente_id = cliente.id
        db.add(fila)
        db.commit()
        processar_item_fila.run(fila.id)
        db.refresh(fila)

        conferir("nada enviado para opt_out", not enviados, f"{len(enviados)} envio(s)")
        conferir("item marcado como opt_out", fila.status == "opt_out", fila.status)
        db.delete(fila)
        db.delete(cliente)
        db.commit()

    finally:
        tenant.status = status_original
        tenant.assinatura_ativa = assinatura_original
        db.commit()
finally:
    db.close()

if falhas:
    print(f"\nFALHAS: {', '.join(falhas)}")
else:
    print("\nTodas as barreiras funcionam.")
sys.exit(1 if falhas else 0)