#!/bin/sh
# Aplica as migrations antes de subir o serviço.
#
# Sem isso o container sobe com o banco sem schema e o primeiro SELECT já estoura
# com UndefinedColumn. O worker NÃO usa este entrypoint (ver docker-compose.yml)
# para não rodar upgrade head em paralelo com o backend.
set -e

echo "[entrypoint] aplicando migrations..."
alembic upgrade head

echo "[entrypoint] migrations ok, iniciando: $*"
exec "$@"