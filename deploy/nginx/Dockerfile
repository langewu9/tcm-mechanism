FROM node:22-alpine AS web-build

WORKDIR /src
RUN corepack enable
COPY web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
# Vite publicDir is ../public, not web/public. Include brand and demo assets.
COPY public/ /public/
RUN pnpm build:delivery

FROM nginx:stable-alpine
COPY --from=web-build /src/dist/ /usr/share/nginx/html/
COPY deploy/nginx/rate-limits.conf /etc/nginx/conf.d/00-rate-limits.conf
COPY deploy/nginx/proxy-api.conf /etc/nginx/snippets/proxy-api.conf
COPY deploy/nginx/security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY deploy/nginx/default.conf.template /etc/nginx/templates/default.conf.template
EXPOSE 80 443
