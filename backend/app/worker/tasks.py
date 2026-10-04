from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.db.models import Tenant, Agenda, FilaEnvio, Cliente
from app.services import evolution
from app.worker.celery_app import celery_app

def formatar_mensagem(template: str, nome: str, negocio: str, servico: str, quando: datetime) -> str:
    """Substitui os placeholders dinâmicos pelo contexto real da marcação."""
    texto = template or "Olá {nome}, lembramos do seu agendamento no {negocio} dia {data} às {horario}."
    return texto.format(
        nome=nome or "Cliente",
        negocio=negocio or "nosso espaço",
        servico=servico or "atendimento",
        data=quando.strftime("%d/%m") if quando else "",
        horario=quando.strftime("%H:%M") if quando else ""
    )

@celery_app.task(name="simular_envio_whatsapp")
def simular_envio_whatsapp(tenant_id: str, telefone: str, mensagem: str):
    """Simulação simples para testes manuais via API."""
    print(f"[Worker] A simular envio para {telefone} (Tenant: {tenant_id}): {mensagem}")
    return {"status": "sucesso", "telefone": telefone}

@celery_app.task(name="verificar_e_disparar_lembretes")
def verificar_e_disparar_lembretes():
    """Varre a agenda de todos os tenants e agenda os envios necessários."""
    db: Session = SessionLocal()
    agora = datetime.utcnow()
    
    try:
        tenants = db.query(Tenant).all()
        for tenant in tenants:
            # 1. Obtém as configurações do negócio
            config = tenant.config or {}
            horas_antecedencia = int(config.get("horas_antecedencia", 24))
            template = config.get("mensagem_modelo", "")
            
            # Janela de envio: agendamentos previstos para daqui a X horas (com tolerância de 30 min)
            limite_inicio = agora + timedelta(hours=horas_antecedencia)
            limite_fim = limite_inicio + timedelta(minutes=30)
            
            # 2. Localiza marcações pendentes dentro da janela
            agendas_pendentes = db.query(Agenda).filter(
                Agenda.tenant_id == tenant.id,
                Agenda.status == "agendado",
                Agenda.quando >= limite_inicio,
                Agenda.quando <= limite_fim
            ).all()

            for item in agendas_pendentes:
                # 3. Monta o texto personalizado
                texto_pronto = formatar_mensagem(
                    template=template,
                    nome=item.nome,
                    negocio=tenant.negocio,
                    servico=item.servico,
                    quando=item.quando
                )

                # 4. Cria o item na fila de envio
                fila = FilaEnvio(
                    tenant_id=tenant.id,
                    cliente_id=item.cliente_id,
                    agenda_id=item.id,
                    telefone=item.telefone,
                    texto=texto_pronto,
                    campanha="lembrete_remarcacao",
                    status="pendente"
                )
                db.add(fila)
                
                # Marca como na_fila para não reenviar na próxima rodada
                item.status = "na_fila"
                db.commit()

                # 5. Despacha a tarefa assíncrona de envio imediato
                processar_item_fila.delay(fila.id)
                
    except Exception as exc:
        print(f"[Worker] Erro ao verificar lembretes: {exc}")
        db.rollback()
    finally:
        db.close()

@celery_app.task(name="processar_item_fila")
def processar_item_fila(fila_id: str):
    """Executa a comunicação real com a Evolution API para disparar a mensagem."""
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

        # Envio real pela Evolution API. Sem o hasattr que existia antes: ele
        # caía num print e marcava a fila como enviada sem nada ter saído.
        try:
            resposta = evolution.enviar_texto(tenant.instancia, fila.telefone, fila.texto)

            fila.status = "enviado"
            fila.enviado_em = datetime.utcnow()
            fila.simulado = bool(resposta.get("simulado"))
            
            # Atualiza o agendamento de origem
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