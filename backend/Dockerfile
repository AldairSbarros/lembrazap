FROM python:3.12-slim

WORKDIR /app

# Copia e instala as dependências primeiro (otimiza o cache do Docker)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o resto do código
COPY . .

# Aplica as migrations antes de subir o serviço.
# Invocado via `sh` em vez de depender do bit de execução: o git não preserva
# o modo 100755 entre Windows e Linux, e o chmod abaixo é anulado quando
# existe bind mount sobre /app.
RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["sh", "/app/entrypoint.sh"]

# Comando para iniciar o servidor
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]