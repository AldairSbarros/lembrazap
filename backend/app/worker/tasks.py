import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

from app.db.database import SessionLocal
from app.db.models import Tenant, Agenda, FilaEnvio, Cliente
from app.services import evolution
from app.services.assinatura import pode_operar
from app.services.config_disparo import ler_regras
from app.services.mensagem import (
    _PADRAO_LEMBRETE,
    _PADRAO_REATIVACAO,
    formatar_mensagem,
)
from app.services.telefone import telefone_destino
from app.worker.celery_app import celery_app


@celery_app.task(name="simular_envio_whatsapp")
def simular_envio_whatsapp(tenant_id: str, telefone: str, mensagem: str):
    """Simulação simples para testes manuais via API."""
    print(f"[Worker] A simular envio para {telefone} (Tenant: {tenant_id}): {mensagem}")
    return {"status": "sucesso", "telefone": telefone}


@celery_app.task(name="verificar_e_disparar_lembretes")
def verificar_e_disparar_lembretes():
    """Varre a agenda de todos os tenants e agenda os envios necessários.

    Roda a cada 10 minutos. Dispara para agendamento ainda `agendado` cujo horário
    cai na janela de antecedência configurada pelo dono.

    O `try/except` fica **dentro** do laço de tenants de propósito: quando
    envolvia o laço inteiro, um template inválido de um negócio impedia o
    disparo de todos os outros.
    """
    db: Session = SessionLocal()
    agora = datetime.utcnow()

    try:
        tenants = db.query(Tenant).all()
        for tenant in tenants:
            try:
                regras = ler_regras(tenant.config)

                if regras.envios_pausados:
                    continue

                # Conta suspensa, inadimplente ou com teste vencido não entra no
                # disparo. `envios_pausados` é decisão do próprio negócio; o acesso
                # bloqueado é decisão de cobrança e vale mais, então vem primeiro.
                liberado, motivo = pode_operar(tenant)
                if not liberado:
                    log.info("[worker] tenant %s pulado: %s", tenant.id, motivo)
                    continue

                # Janela de envio: agendamentos previstos para daqui a X horas,
                # com 30 min de tolerância porque a task roda a cada 10 min.
                limite_inicio = agora + timedelta(hours=regras.horas_antecedencia)
                limite_fim = limite_inicio + timedelta(minutes=30)

                agendas_pendentes = db.query(Agenda).filter(
                    Agenda.tenant_id == tenant.id,
                    Agenda.status == "agendado",
                    Agenda.quando >= limite_inicio,
                    Agenda.quando <= limite_fim,
                ).all()

                for item in agendas_pendentes:
                    texto = formatar_mensagem(
                        template=regras.mensagem_lembrete,
                        nome=item.nome,
                        negocio=tenant.negocio,
                        servico=item.servico,
                        quando=item.quando,
                        padrao=_PADRAO_LEMBRETE,
                    )

                    # Opt-out é lei: cliente que pediu para não receber não
                    # recebe, mesmo com horário marcado.
                    if item.cliente_id:
                        cliente = db.query(Cliente).filter(Cliente.id == item.cliente_id).first()
                        if cliente and cliente.opt_out:
                            continue

                    fila = FilaEnvio(
                        tenant_id=tenant.id,
                        cliente_id=item.cliente_id,
                        agenda_id=item.id,
                        telefone=telefone_destino(item.telefone),
                        texto=texto,
                        campanha="lembrete_agendamento",
                        status="pendente",
                    )
                    db.add(fila)
                    item.status = "na_fila"
                    db.commit()

                    processar_item_fila.delay(fila.id)

            except Exception as exc:
                db.rollback()
                print(f"[Worker] Erro nos lembretes do tenant {tenant.id}: {exc}")

    finally:
        db.close()


@celery_app.task(name="reativar_clientes_inativos")
def reativar_clientes_inativos():
    """Manda a mensagem de "sentimos sua falta" para quem está sumido.

    Roda uma vez por dia. Para cada tenant com reativação ligada, seleciona os
    clientes que não registrados visita há mais de `dias_sem_visitar` dias e
    enfileira a mensagem de reativação.

    Três exclusões, nesta ordem de importância:

    1. `opt_out` — quem pediu para não receber não recebe. WhatsApp Business
       bane número que insiste em mensagem para quem recusou.
    2. Cliente sem histórico (`ultima_visita` vazio) — não há como saber há
       quanto tempo não vem, então não é mensurável. Fica para o dono decidir,
       e o painel mostra esse grupo separado.
    3. `limite_por_dia` — teto por negócio, para não estourar a janela da
       Evolution com um disparo de 800 mensagens de uma vez.
    """
    db: Session = SessionLocal()
    agora = datetime.utcnow()
    totais = {"enfileirados": 0, "ignorados_opt_out": 0, "ignorados_sem_historico": 0, "tenants": 0}

    try:
        tenants = db.query(Tenant).all()
        for tenant in tenants:
            try:
                regras = ler_regras(tenant.config)

                if not regras.reativacao_ativa or regras.envios_pausados:
                    continue

                liberado, motivo = pode_operar(tenant)
                if not liberado:
                    log.info("[worker] reativação: tenant %s pulado: %s", tenant.id, motivo)
                    continue

                if not tenant.instancia:
                    continue

                corte = agora - timedelta(days=regras.dias_sem_visitar)

                candidatos = db.query(Cliente).filter(
                    Cliente.tenant_id == tenant.id,
                    Cliente.ultima_visita.isnot(None),
                    Cliente.ultima_visita <= corte,
                ).order_by(Cliente.ultima_visita.asc()).all()

                enviados = 0

                for cliente in candidatos:
                    if enviados >= regras.limite_por_dia:
                        break

                    if cliente.opt_out:
                        totais["ignorados_opt_out"] += 1
                        continue

                    # Não repetir para quem já recebeu esta campanha hoje.
                    ja_enviado = db.query(FilaEnvio).filter(
                        FilaEnvio.tenant_id == tenant.id,
                        FilaEnvio.cliente_id == cliente.id,
                        FilaEnvio.campanha == "reativacao",
                        FilaEnvio.status == "enviado",
                        FilaEnvio.criado_em >= agora - timedelta(hours=20),
                    ).first()
                    if ja_enviado:
                        continue

                    dias = (agora - cliente.ultima_visita).days

                    texto = formatar_mensagem(
                        template=regras.mensagem_reativacao,
                        nome=cliente.nome,
                        negocio=tenant.negocio,
                        telefone=cliente.telefone,
                        dias_sem_visita=dias,
                        padrao=_PADRAO_REATIVACAO,
                    )

                    fila = FilaEnvio(
                        tenant_id=tenant.id,
                        cliente_id=cliente.id,
                        telefone=telefone_destino(cliente.telefone),
                        texto=texto,
                        campanha="reativacao",
                        status="pendente",
                    )
                    db.add(fila)
                    enviados += 1

                    db.commit()
                    processar_item_fila.delay(fila.id)

                totais["tenants"] += 1
                totais["enfileirados"] += enviados
                print(f"[Worker] Reativação tenant {tenant.id}: {enviados} enfileirado(s).")

            except Exception as exc:
                db.rollback()
                print(f"[Worker] Erro na reativação do tenant {tenant.id}: {exc}")

        print(f"[Worker] Reativação concluída: {totais}")

    finally:
        db.close()

    return totais


@celery_app.task(name="processar_item_fila")
def processar_item_fila(fila_id: str):
    """Executa o envio real pela Evolution API."""
    db: Session = SessionLocal()
    try:
        fila = db.query(FilaEnvio).filter(FilaEnvio.id == fila_id).first()
        if not fila or fila.status != "pendente":
            return

        tenant = db.query(Tenant).filter(Tenant.id == fila.tenant_id).first()
        if not tenant or not tenant.instancia:
            fila.status = "falha"
            fila.erro = "Instância do WhatsApp não configurada."
            db.commit()
            return

        # Última barreira de cobrança: a mensagem pode ter sido enfileirada antes da
        # suspensão e só agora ser despachada. Checagem no momento do envio, e não
        # só na hora de enfileirar, porque a fila tem latência.
        liberado, motivo = pode_operar(tenant)
        if not liberado:
            fila.status = "falha"
            fila.erro = f"Envio bloqueado: {motivo}"
            db.commit()
            log.info("[worker] envio de %s barrado para tenant %s", fila_id, tenant.id)
            return

        # Última barreira do opt-out: mesmo que algo tenha enfileirado errado,
        # o envio não sai para quem pediu para não receber.
        if fila.cliente_id:
            cliente = db.query(Cliente).filter(Cliente.id == fila.cliente_id).first()
            if cliente and cliente.opt_out:
                fila.status = "opt_out"
                fila.erro = "Cliente pediu para não receber mensagens."
                db.commit()
                return

        try:
            resposta = evolution.enviar_texto(tenant.instancia, fila.telefone, fila.texto)

            fila.status = "enviado"
            fila.enviado_em = datetime.utcnow()
            fila.simulado = bool(resposta.get("simulado"))

            if fila.agenda_id:
                agenda = db.query(Agenda).filter(Agenda.id == fila.agenda_id).first()
                if agenda:
                    agenda.status = "enviado"

            db.commit()
        except Exception as e:
            fila.status = "falha"
            fila.erro = str(e)
            db.commit()

    except Exception as exc:
        db.rollback()
        print(f"[Worker] Falha ao processar envio: {exc}")
    finally:
        db.close()