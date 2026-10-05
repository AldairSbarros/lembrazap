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

Para desenvolvimento, com bind mount e recarga automática:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

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

Na VPS de produção, o nginx é o **OpenResty do painel iContainer**, em container
com rede host. Não é um nginx de instalação comum, então os caminhos são
específicos. O procedimento completo está no próprio
[`deploy/nginx-lembrazap.conf`](../deploy/nginx-lembrazap.conf), e o resumo:

```bash
SITE=/etc/icontainer/apps/openresty/openresty/www/sites/lembrazap.aletheia.ia.br
CONF=/etc/icontainer/apps/openresty/openresty/conf/conf.d/lembrazap.aletheia.ia.br.conf
mkdir -p $SITE/{log,ssl,index}

# 1. Bootstrap HTTP (necessário: o bloco HTTPS não sobe sem certificado)
cp deploy/nginx-lembrazap-http.conf $CONF
docker exec ic-openresty-wQHe openresty -t && docker exec ic-openresty-wQHe openresty -s reload

# 2. Certificado do subdomínio (não há wildcard para *.aletheia.ia.br)
#    O webroot tem que ser o diretório HOST que corresponde ao
#    `root /usr/share/nginx/html` do vhost de bootstrap, senão a emissão falha.
ACME_ROOT=/etc/icontainer/apps/openresty/openresty/root
mkdir -p $ACME_ROOT/.well-known/acme-challenge
certbot certonly --webroot -w $ACME_ROOT -d lembrazap.aletheia.ia.br
cp /etc/letsencrypt/live/lembrazap.aletheia.ia.br/{fullchain,privkey}.pem $SITE/ssl/

# 3. Vhost final com HTTPS
cp deploy/nginx-lembrazap.conf $CONF
docker exec ic-openresty-wQHe openresty -t && docker exec ic-openresty-wQHe openresty -s reload

# 4. Painel: build do frontend para o mesmo vhost (mesma origem, sem CORS)
#    Feito em container porque o Vite 8 exige Node >=20 e a VPS tem Node 18.
#    O `rm -rf` antes do build é obrigatório: `--output type=local` escreve por
#    cima mas não apaga o que sobrou do deploy anterior, e os arquivos antigos
#    com hash ficariam publicadas na pasta do site.
rm -rf frontend/dist
docker build -f frontend/Dockerfile --output type=local,dest=frontend/dist frontend/
rm -rf $SITE/index && mkdir -p $SITE/index
cp -r frontend/dist/* $SITE/index/
```

> **Renovação do certificado.** O OpenResty não lê `/etc/letsencrypt/live/`, então
> o cert em `$SITE/ssl` ficaria velho depois da renovação automática. Registre um
> hook que copie os arquivos e recarregue o OpenResty:
>
> ```bash
> mkdir -p /etc/letsencrypt/renewal-hooks/deploy
> # /etc/letsencrypt/renewal-hooks/deploy/lembrazap-openresty.sh
> #   cp /etc/letsencrypt/live/lembrazap.aletheia.ia.br/{fullchain,privkey}.pem $SITE/ssl/
> #   docker exec ic-openresty-wQHe openresty -t && docker exec ic-openresty-wQHe openresty -s reload
> certbot renew --dry-run   # valida o hook
> ```

> **Porta 8002, não 8000.** O host 8000 já é do `aletheia_backend` nessa VPS.
> O container do backend escuta em 8000; quem fala com ele de fora usa 8002.
>
> **`db` e `redis` não publicam portas** de propósito — só o backend fala com
> eles pela rede interna do compose. Isso evita conflito com o Postgres e o
> Redis compartilhados do painel (5432 e 6379) e fecha o acesso externo.

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

> O procedimento abaixo é o da **iContainer/OpenResty**, que é o ambiente em que o
> sistema roda. O nginx do host não existe nesse ambiente — o vhost vai para o
> OpenResty em Docker. Se a sua VPS usa nginx nativo, adapte os passos 4 e 5.

```bash
# 1. Copiar o projeto
git clone git@github.com:AldairSbarros/lembrazap.git /root/lembrazap
cd /root/lembrazap

# 2. Configurar
cat > .env <<'EOF'
# host.docker.internal, NUNCA 127.0.0.1: de dentro do container, 127.0.0.1 é
# o próprio container, e a Evolution responde "Connection refused" na hora de
# criar a conexão do WhatsApp. O compose expõe a host com host-gateway.
EVOLUTION_API_URL=http://host.docker.internal:8080
EVOLUTION_API_KEY=sua-chave
MODO_SIMULACAO=0
WEBHOOK_PUBLIC_URL=https://lembrazap.aletheia.ia.br
TIMEZONE=America/Manaus

# Stripe é opcional. Sem estas linhas o sistema roda por cobrança manual.
# FRONTEND_URL=https://lembrazap.aletheia.ia.br
EOF
chmod 600 .env

# 3. Subir (apenas 8002 é publicada; o banco e o Redis ficam internos)
docker compose up -d --build
docker compose ps
curl http://localhost:8002/healthz

# 4. Criar o acesso do proprietário (uma vez por instalação)
docker compose exec backend python criar_admin.py

# 5. Publicar o subdomínio — o procedimento está na seção "Opção A" acima,
#    porque a emissão do certificado depende do webroot do vhost de bootstrap.
#    Resumindo: vhost HTTP de bootstrap → certbot --webroot → vhost final em
#    deploy/nginx-lembrazap.conf → reload do OpenResty.

# 6. Conferir
curl https://lembrazap.aletheia.ia.br/healthz
curl -s -o /dev/null -w '%{http_code}\n' https://lembrazap.aletheia.ia.br/admin
```

O passo 6 espera **`200`** no `/admin`. É o mesmo `index.html` do painel, com o
fallback de SPA do vhost — não é uma rota separada, então não há o que configuração.

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

O `.env` tem a chave da Evolution e, se você ligou a cobrança, a da Stripe:
`chmod 600` e nunca versione. O `.env.example` é o **único** arquivo de configuração
que pode ser commitado — se ele contém chave real, o push protection do GitHub
recusa o push.

---

## Banco de dados e migrations

As migrations são Alembic, em `backend/alembic/versions/`.

| Revisão | O que faz |
|---|---|
| `0b5bbedbd982` | Tabelas iniciais: `tenants`, `clientes`, `agenda`, `fila` |
| `7f3d9c1b2e40` | Alinha o schema aos modelos: `agenda.servico`, `agenda.confirmado_em`, `clientes.ultima_resposta` |
| `8a4c2f19d3e7` | Assinatura e cobrança: campos de assinatura em `tenants`, tabelas `pagamentos` e `admin_usuarios` |

> A revisão `8a4c2f19d3e7` coloca **todas** as contas existentes em `trial` com a
> assinatura fechada. Isso é proposital: nada é liberado por acidente ao migrar.
> Depois de aplicar, abra `/admin` e libere o acesso das contas que já deviam
> funcionar.

Comandos:

```bash
docker compose exec backend alembic current        # revisão aplicada
docker compose exec backend alembic history        # linha do tempo
docker compose exec backend alembic upgrade head   # aplica pendentes
docker compose exec backend alembic downgrade -1   # desfaz a última
```

O `entrypoint.sh` já roda `alembic upgrade head` no boot do backend, então subir
com `docker compose up -d` aplica a migration sozinho. O comando manual é para
inspeção.

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
