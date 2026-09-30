# LembraZap — imagem mínima, usuário não privilegiado, dados em volume.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY armazem.py evolution.py ia.py app.py ./
COPY static ./static

RUN useradd --create-home lz && mkdir -p /app/dados && chown -R lz:lz /app
USER lz

ENV DADOS_DIR=/app/dados \
    PORTA=8050

EXPOSE 8050

CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8050"]
