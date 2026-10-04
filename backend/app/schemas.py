from pydantic import BaseModel
from typing import Optional

class ContaReq(BaseModel):
    """Criação de conta (nome do negócio e segmento)."""
    nome: str
    negocio: str = ""

class ContaResp(BaseModel):
    ok: bool
    tenant_id: str
    token: str
    

TEMPLATES_NICHOS = {
    "barbearia": {
        "label": "Barbearia",
        "texto": (
            "Fala {nome}, beleza? Passando pra lembrar do seu horário marcado na {negocio} "
            "para {servico} no dia {data} às {horario}. 💈\n\n"
            "Responda *SIM* para confirmar ou *ADIAR* para remarcar."
        ),
        "resposta_sim": "Fechado, {nome}! Horário confirmado com sucesso. Te esperamos aqui na {negocio}! 👊",
        "resposta_adiar": "Entendido, {nome}! Vamos remarcar. Que outro dia ou horário fica melhor pra você?"
    },
    "petshop": {
        "label": "Petshop / Banho e Tosa",
        "texto": (
            "Olá {nome}! 🐾 Lembrança especial da {negocio}: o horário do seu pet para {servico} "
            "está agendado para {data} às {horario}.\n\n"
            "Podemos confirmar? Responda *SIM* para confirmar ou *ADIAR* para reagendar."
        ),
        "resposta_sim": "Que ótimo! A equipe da {negocio} já está pronta para receber seu amiguinho(a)! 🐶✨",
        "resposta_adiar": "Sem problemas! Vamos encontrar outro momento ideal para o pet. Qual data prefere?"
    },
    "salao_manicure": {
        "label": "Salão / Manicure / Estética",
        "texto": (
            "Oi {nome}, tudo bem? ✨ Seu momento de cuidado na {negocio} para {servico} "
            "está marcado para {data} às {horario}.\n\n"
            "Por favor, responda *SIM* para garantir sua vaga ou *ADIAR* caso precise alterar."
        ),
        "resposta_sim": "Perfeito, {nome}! Horário reservado e profissional a postos. Até logo! 💖",
        "resposta_adiar": "Tudo bem, querida(o)! Quando seria um bom dia para reagendarmos seu horário?"
    },
    "boutique": {
        "label": "Boutique / Consultoria de Moda",
        "texto": (
            "Olá {nome}! Tudo bem? Seu atendimento exclusivo / prova na {negocio} "
            "está marcado para {data} às {horario}. 👗\n\n"
            "Confirma sua visita? Responda *SIM* para confirmar ou *ADIAR* para agendar outra data."
        ),
        "resposta_sim": "Maravilha! Já estamos preparando tudo para te receber na {negocio}. Até breve!",
        "resposta_adiar": "Combinado! Qual seria a melhor data para organizarmos a sua visita?"
    },
    "geral": {
        "label": "Geral / Outros Negócios",
        "texto": (
            "Olá {nome}! Lembramos do seu agendamento de {servico} na {negocio} "
            "no dia {data} às {horario}.\n\n"
            "Responda *SIM* para confirmar ou *ADIAR* para remarcar."
        ),
        "resposta_sim": "Confirmação recebida com sucesso! Aguardamos você.",
        "resposta_adiar": "Tudo bem! Em breve entraremos em contato para remarcar."
    }
}