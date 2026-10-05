"""Objeto Celery único do projeto.

Importar sempre daqui — ``from app.worker.celery_app import celery_app``. Existiam
três instâncias de Celery concorrentes (esta, uma em ``tasks.py`` e outra em
``main.py``), cada uma com configuração diferente. O worker sobe com
``-A app.worker.celery_app``, mas as tasks eram registradas e o ``beat_schedule``
era definido na instância de ``tasks.py``: o beat ficava com schedule vazio e os
lembretes automáticos nunca disparavam.
"""
import os

from celery import Celery
from celery.schedules import crontab

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery(
    "lembrazap_worker",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["app.worker.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone=os.getenv("TIMEZONE", "America/Manaus"),
    enable_utc=True,
    broker_connection_retry_on_startup=True,
)

celery_app.conf.beat_schedule = {
    "verificar-lembretes-a-cada-10-minutos": {
        "task": "verificar_e_disparar_lembretes",
        "schedule": 600.0,
    },
    # Reativação roda uma vez por dia, à meia-noite (horário do Celery, que
    # respeita TIMEZONE). Janela curta de envio: quem ficou de fora espera o
    # dia seguinte, o que dá tempo de o dono perceber antes do próximo disparo.
    "reativar-clientes-inativos-diario": {
        "task": "reativar_clientes_inativos",
        "schedule": crontab(hour=0, minute=0),
    },
}