# =============================================================================
#  Build do painel (frontend) — etapa única, sem runtime.
#
#  Por que existe: o Vite 8 exige Node ^20.19 || >=22.12, e a VPS de produção
#  tem Node 18. Como o OpenResty já é o servidor do site e serve os arquivos
#  estáticos, não faz sentido subir um container de frontend para isso — basta
#  extrair o `dist`.
#
#  Uso (na VPS, sem Node instalado):
#    docker build -f frontend/Dockerfile \
#      --output type=local,dest=frontend/dist frontend/
#    cp -r frontend/dist/* /www/sites/lembrazap.aletheia.ia.br/index/
#
#  O `FROM scratch` final existe para que o --output funcione: sem um estágio
#  final não há artefato a extrair.
# =============================================================================

FROM node:22-alpine AS build
WORKDIR /app

# package-lock.json primeiro: a camada de npm ci só é invalidada quando as
# dependências mudam, não a cada alteração de código.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM scratch AS dist
COPY --from=build /app/dist/ /