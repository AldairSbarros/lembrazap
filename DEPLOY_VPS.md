# Deploy do LembraZap na VPS — passo a passo

Documento operacional para subir o LembraZap ao lado do AletheIA na mesma VPS
(painel icontainer, rede `icontainer-network`, OpenResty como proxy reverso).
Tempo estimado: 20 minutos na primeira vez, 3 minutos nas atualizações.

> Pré-requisitos: Docker + plugin compose instalados (o AletheIA já exige isso),
> e acesso SSH à VPS. Todos os comandos abaixo rodam **na VPS**, exceto onde dito.

---

## 1. Subir os arquivos para a VPS

Do seu computador, dentro da pasta do projeto:

```bash
rsync -avz --exclude dados --exclude __pycache__ --exclude .env \
  ./lembrazap/ root@SEU_IP:/root/lembrazap/
```

Sem `rsync` no Windows, use `scp -r` ou o cliente SFTP que preferir (WinSCP,
FileZilla). O destino sugerido é `/root/lembrazap` — o mesmo padrão de lugar
onde o AletheIA mora (`/root/aletheia...`), fácil de achar depois.

## 2. Criar o `.env`

```bash
cd /root/lembrazap
cp .env.example .env
nano .env
```

Preencha:

| Variável | Valor |
|---|---|
| `EVOLUTION_API_URL` | **o mesmo** do `docker-compose.yml` do AletheIA (ex.: `http://evolution-api:8080`) |
| `EVOLUTION_API_KEY` | **a mesma** do AletheIA |
| `MODO_SIMULACAO` | `0` em produção |
| `WEBHOOK_PUBLIC_URL` | `https://lembrazap.aletheia.ia.br` (sem barra no fim) |
| `GROQ_API_KEY` | opcional — liga o agendamento por IA de verdade |
| `GEMINI_API_KEY` | opcional — fallback da IA |

Sem `GROQ_API_KEY`/`GEMINI_API_KEY` o produto funciona igual; o agendamento
automático usa o parser local (entende "amanhã às 14:30", "terça 10h" etc.).

## 3. Conferir a rede externa

O compose entra na `icontainer-network` para o LembraZap conseguir chamar a
**Evolution API pelo nome do container** (`http://evolution-api:8080`). O proxy
público é o nginx/OpenResty do **host** (não participa dessa rede) — ele chega no
LembraZap pela porta publicada `127.0.0.1:8050`. Se a rede já existe por causa do
AletheIA, pule. Para conferir:

```bash
docker network ls | grep icontainer
# se não existir:
docker network create icontainer-network
```

## 4. Build e subida

```bash
cd /root/lembrazap
docker compose up -d --build
docker compose ps          # STATUS deve ficar em "healthy" após ~20 s
docker compose logs -f --tail=50 lembrazap
```

O log deve mostrar `LembraZap no ar (simulação=False)`.

Teste local na VPS:

```bash
curl -s http://127.0.0.1:8050/healthz     # {"ok":true,"simulacao":false}
```

## 5. Publicar no nginx do host (subdomínio próprio)

O LembraZap usa um **subdomínio isolado** (`lembrazap.aletheia.ia.br`) em vez de um
path `/lembrazap/`. Motivo: um `server` block próprio **não toca** na configuração do
`aletheia.ia.br` que já funciona — risco zero de quebrar o Aletheia ou o Financeiro,
e sem a pegadinha da barra no `proxy_pass`.

> Diferença importante pro AletheIA: o LembraZap é **um único container** que serve
> painel + API + webhook, tudo na porta 8050. Então basta **um** `location /` — não
> precisa de blocos separados para `/api` ou `/webhook`.

### 5.1 DNS

No painel de DNS do `aletheia.ia.br`, crie um registro:

| Tipo | Nome | Valor |
|---|---|---|
| A | `lembrazap` | o mesmo IP público de `aletheia`/`api` (o IP da VPS) |

Aguarde propagar (normalmente minutos). Teste: `getent hosts lembrazap.aletheia.ia.br`.

### 5.2 Bloco HTTP (antes do certificado)

Adicione ao config do nginx (o mesmo arquivo `default` da VPS, ou um
`sites-available/lembrazap` novo com symlink em `sites-enabled`). O bloco abaixo
também está versionado em [`deploy/nginx-lembrazap.conf`](deploy/nginx-lembrazap.conf)
— é só copiar e colar no fim do `default` (não mexe em nada do que já existe):

```nginx
# --- LEMBRAZAP (painel + API + webhook no mesmo container, porta 8050) ---
server {
    listen 80;
    listen [::]:80;
    server_name lembrazap.aletheia.ia.br;

    location / {
        proxy_pass http://127.0.0.1:8050;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300;
    }
}
```

> `proxy_pass http://127.0.0.1:8050` **sem barra no fim** — aqui não há prefixo para
> remover (o subdomínio já é a raiz). É o oposto do caso `/financeiro`.

```bash
nginx -t && systemctl reload nginx
curl -s http://lembrazap.aletheia.ia.br/healthz   # {"ok":true,"simulacao":false}
```

### 5.3 HTTPS com certbot (automático)

O certificado atual (`live/aletheia.ia.br/`) **não cobre** o subdomínio. Deixe o
certbot emitir e configurar sozinho:

```bash
certbot --nginx -d lembrazap.aletheia.ia.br
```

O certbot cria o certificado, adiciona o `listen 443 ssl` + as linhas
`ssl_certificate` e o redirect HTTP→HTTPS automaticamente (igual fez pro AletheIA).
Quando perguntar, escolha **redirecionar** HTTP para HTTPS.

Teste final de fora:

```bash
curl -s https://lembrazap.aletheia.ia.br/healthz
```

O painel fica em **`https://lembrazap.aletheia.ia.br/`**.

### 5.4 Alternativa: path `/lembrazap/` (não recomendada)

Dá para publicar em `aletheia.ia.br/lembrazap/` dentro do `server` 443 existente, mas
aí você **edita o bloco que já funciona** e precisa da barra no `proxy_pass`
(`proxy_pass http://127.0.0.1:8050/;` **com** barra, para remover o prefixo) — foi
esse tipo de detalhe que tornou o `/financeiro` penoso. O painel já é "ciente do
prefixo", então funcionaria; ainda assim, o subdomínio é mais seguro e limpo.

## 6. Teste de ponta a ponta com WhatsApp real

1. Abra o painel, crie a conta do piloto e **copie o token** (aparece uma vez).
2. Aba Conexão → Gerar QR Code → escaneie com o número do negócio.
3. Cadastre 2-3 clientes de teste (um deles sendo o **seu próprio número**).
4. Dispare uma reativação com corte pequeno (ex.: 30 dias).
5. No seu WhatsApp: responda `SIM` → deve chegar a resposta automática pedindo
   o horário. Responda `amanhã às 15:00` → deve chegar a confirmação de reserva
   e o compromisso aparece na aba Agenda com o selo "via IA".
6. Responda `SAIR` → o cliente some dos envios (opt-out) e aparece com o selo
   opt-out na aba Clientes.

Se o passo 5 não acontecer, veja o item 8 (webhook).

## 7. Rotina operacional

**Backup diário dos dados** (os JSON são o banco inteiro):

```bash
# /etc/cron.d/lembrazap-backup
15 3 * * * root tar -czf /root/backups/lembrazap-$(date +\%F).tar.gz -C /root/lembrazap dados \
  && find /root/backups -name 'lembrazap-*.tar.gz' -mtime +14 -delete
```

(Crie `/root/backups` antes. Idealmente envie esse tarball para fora da VPS —
o mesmo destino do backup do AletheIA.)

**Logs:** o compose já limita em 10 MB × 3 arquivos. Para acompanhar:
`docker compose logs -f --tail=100 lembrazap`.

**Atualizar o app:**

```bash
cd /root/lembrazap
rsync ... (de novo, do seu computador)   # ou git pull, se versionar
docker compose up -d --build            # rebuild + restart em ~30 s
```

**Rollback:** os dados não mudam entre versões (mesmo schema JSON); se uma
versão nova misbehavar, `git checkout`/recopiar a versão anterior e
`docker compose up -d --build` de novo. Por isso: **versione esta pasta num
git próprio** (`git init` + commit a cada entrega) — é o seu botão de desfazer.

## 8. Troubleshooting

| Sintoma | Causa provável / ação |
|---|---|
| `docker compose up` falha com "network not found" | passo 3 |
| QR não aparece no painel | `EVOLUTION_API_URL` errado; teste `curl -H "apikey: CHAVE" $EVOLUTION_API_URL/instance/fetchInstances` de dentro da rede |
| QR aparece mas não conecta | número já pareado em outro aparelho/instância; desconecte no WhatsApp e gere novo QR |
| Mensagens não saem | instância desconectada (aba Conexão mostra estado); reconecte |
| Respostas do cliente não chegam (SIM/SAIR ignorados) | webhook não configurado: confira `WEBHOOK_PUBLIC_URL` e teste `curl -X POST https://lembrazap.aletheia.ia.br/webhook/evolution/ID -d '{}' -H 'Content-Type: application/json'` (deve responder `{"ok":true,"acao":"ignorado"}`); se houver WAF no nginx, libere POST nesse path |
| Webhook chega mas não casa o cliente | o número que respondeu não está na base, ou o sufixo de 10 dígitos difere (DDI/DDD) |
| Painel abre mas API dá 401 | token errado/no navegador antigo: limpe o localStorage e entre de novo |
| `healthy` nunca fica | `docker compose logs` — normalmente `.env` ausente ou porta 8050 ocupada (`ss -tlnp \| grep 8050`) |

## 9. Checklist de segurança antes de vender

- [ ] Porta 8050 só em `127.0.0.1` (confira: `ss -tlnp | grep 8050`)
- [ ] DNS: registro A `lembrazap` → IP da VPS (`getent hosts lembrazap.aletheia.ia.br`)
- [ ] HTTPS: `certbot --nginx -d lembrazap.aletheia.ia.br` rodado e redirect 80→443 ativo
- [ ] `.env` com permissão `600` (`chmod 600 .env`)
- [ ] Backup cronado e **um restore testado** pelo menos uma vez
- [ ] Token de cada conta entregue por canal privado (é a senha do negócio)
- [ ] `MODO_SIMULACAO=0` em produção

## 10. Custos marginais deste deploy

Zero de infraestrutura (a VPS já está paga e ociosa). Com as chaves de IA
configuradas, cada interpretação de horário custa fração de centavo (modelo
pequeno, ~60 tokens); o grosso do custo de IA continua sendo do AletheIA, não
deste produto.
