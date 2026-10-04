# Instalação e Deploy

Procedimentos para rodar o LembraZap. Para o dia a dia do negócio, veja
[MANUAL-USUARIO.md](MANUAL-USUARIO.md).

---

## Requisitos

| Item | Versão | Para quê |
|---|---|---|
| Docker Desktop | 24+ | Containers |
| Node.js | 20+ | Somente o frontend (Vite) |
| Evolution API | 2.3.x | Ponte com o WhatsApp |
| PostgreSQL | 15 | Incluído no compose |
| Redis | 7 | Incluído no compose |

---

## Rodar local (desenvolvimento)

### 1. Configurar

```bash
cp .env.example .env
```

Preencha no `.env`:

```bash
EVOLUTION_API_URL=http://IP_DA_EVOLUTION:8080
EVOLUTION_API_KEY=sua-chave
```

Para **demonstrar sem usar número real**, use `MODO_SIMULACAO=1`: o QR Code é
fictício e nenhuma mensagem é enviada.

### 2. Subir o backend

```bash
docker compose up -d --build
```

O `entrypoint.sh` roda `alembic upgrade head` antes do uvicorn, então o schema do
banco é criado/ajustado automaticamente. O `worker` só sobe depois que o `backend`
fica `healthy`, para não rodar contra um banco sem tabela.

Conferir:

```bash
docker compose ps          # todos healthy / up
curl http://localhost:8000/healthz
```

### 3. Subir o frontend

```bash
cd frontend
npm install
npm run dev                # http://localhost:5173
```

### 4. Acessar

| Serviço | Endereço |
|---|---|
| Painel | <http://localhost:5173> |
| Swagger | <http://localhost:8000/docs> |
| ReDoc | <http://localhost:8000/redoc> |
| Healthcheck | <http://localhost:8000/healthz> |

---

## O webhook precisa de URL pública

Sem isso o cliente **envia** a resposta mas o sistema **não recebe**, e o status
nunca muda para Confirmado.

O backend registra na Evolution a URL
`{WEBHOOK_PUBLIC_URL}/api/webhook/whatsapp`. Três formas de resolver:

### Opção A — Produção: domínio na VPS (recomendado)

```bash
WEBHOOK_PUBLIC_URL=https://lembrazap.aletheia.ia.br
```

Exige o bloco em `deploy/nginx-lembrazap.conf` publicado na VPS:

```bash
sudo cp deploy/nginx-lembrazap.conf /etc/nginx/conf.d/lembrazap.conf
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d lembrazap.aletheia.ia.br
```

> O arquivo aponta para `127.0.0.1:8000`. A versão antiga apontava para `8050`,
> que era o protótipo de arquivo único e não existe mais.

### Opção B — Teste temporário: túnel cloudflared

```bash
# 1. Baixar cloudflared (Windows)
Invoke-WebRequest -Uri "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" -OutFile "$env:TEMP\cloudflared.exe"

# 2. Subir o túnel apontando para o backend local
& "$env:TEMP\cloudflared.exe" tunnel --no-autoupdate --url http://localhost:8000

# 3. Colocar a URL gerada no .env e reiniciar
docker compose up -d --build

# 4. Re-registrar o webhook (a rota é idempotente)
curl -X POST http://localhost:8000/api/conexao/criar -H "X-LZ-Token: SEU_TOKEN"
```

> Túneis "quick" são **temporários**: a URL muda a cada reinício e o webhook
> precisa ser re-registrado. Não use em produção.

### Opção C — Teste local sem URL pública

Teste apenas o envio. Crie um agendamento dentro da janela de antecedência e
confirme que a mensagem chega. A resposta do cliente não será processada.

---

## Publicar na VPS

### Estrutura esperada

```
/root/lembrazap/            esta pasta
├── .env
├── docker-compose.yml
├── backend/
└── frontend/               não vai para a VPS (front é estático)
```

### Passo a passo

```bash
# 1. Copiar o projeto
scp -r .\lembrazap root@SUA_VPS:/root/lembrazap

# 2. Configurar
cd /root/lembrazap
cat > .env <<'EOF'
EVOLUTION_API_URL=http://127.0.0.1:8080
EVOLUTION_API_KEY=sua-chave
MODO_SIMULACAO=0
WEBHOOK_PUBLIC_URL=https://lembrazap.aletheia.ia.br
TIMEZONE=America/Manaus
EOF
chmod 600 .env

# 3. Subir (portas 5432/6379/8000 só na localhost, expostas via nginx)
docker compose up -d --build
docker compose ps

# 4. Publicar o subdomínio
sudo cp deploy/nginx-lembrazap.conf /etc/nginx/conf.d/lembrazap.conf
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d lembrazap.aletheia.ia.br

# 5. Conferir
curl https://lembrazap.aletheia.ia.br/healthz
```

### Segurança na VPS

O `docker-compose.yml` traz credenciais de desenvolvimento fixas
(`lembrazap_user` / `password_segura`) e publica as portas 5432 e 6379 no host
para facilitar o desenvolvimento local. **Troque tudo isso antes de expor a
VPS:**

```yaml
db:
  environment:
    POSTGRES_USER: <usuario forte>
    POSTGRES_PASSWORD: <senha forte>   # troque nos 3 lugares
```

A senha aparece em quatro lugares que precisam bater: `POSTGRES_PASSWORD` no
compose e as duas entradas `DATABASE_URL` (`backend` e `worker`). Depois:

```bash
docker compose up -d --build          # recria os containers
docker compose exec db psql -U lembrazap_user -c "\l"
```

Se o volume antigo já existir com outra senha, o `psql` vai pedir a senha antiga.
Use `docker compose down -v` (apaga os dados) ou `ALTER USER`.

O `.env` tem a chave da Evolution: `chmod 600` e nunca versione.

---

## Banco de dados e migrations

As migrations são Alembic, em `backend/alembic/versions/`.

| Revisão | O que faz |
|---|---|
| `0b5bbedbd982` | Tabelas iniciais: `tenants`, `clientes`, `agenda`, `fila` |
| `7f3d9c1b2e40` | Alinha o schema aos modelos: `agenda.servico`, `agenda.confirmado_em`, `clientes.ultima_resposta` |

Comandos:

```bash
docker compose exec backend alembic current        # revisão aplicada
docker compose exec backend alembic history        # linha do tempo
docker compose exec backend alembic upgrade head   # aplica pendentes
docker compose exec backend alembic downgrade -1   # desfaz a última
```

> `upgrade head` roda sozinho no boot do `backend`. Se você rodar manualmente
> enquanto o container sobe, pode colidir. O `worker` não roda migration.

### Backup

```bash
docker compose exec -T db pg_dump -U lembrazap_user lembrazap > backup_$(date +%F).sql
```

O Postgres guarda em volume nomeado `postgres_data`. Um `docker compose down`
**não** apaga o volume; `docker compose down -v` apaga.

---

## Atualizar

```bash
git pull
docker compose up -d --build
docker compose logs -f worker
```

A migration roda no boot. Confira se aplicou:

```bash
docker compose exec backend alembic current
```

### Rollback

```bash
docker compose down
git checkout <tag-ou-commit-anterior>
docker compose up -d --build
```

Se a migration precisar ser desfeita antes:

```bash
docker compose exec backend alembic downgrade -1
```

---

## Parar

```bash
docker compose stop          # para, mantém dados
docker compose down          # remove containers, mantém volume
docker compose down -v       # remove containers E dados (destrutivo)
```
