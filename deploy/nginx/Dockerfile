FROM node:22-alpine AS web-build

WORKDIR /src
RUN corepack enable
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm build

FROM nginx:stable-alpine
COPY --from=web-build /src/dist/ /usr/share/nginx/html/
COPY deploy/nginx/rate-limits.conf /etc/nginx/conf.d/00-rate-limits.conf
COPY deploy/nginx/default.conf.template /etc/nginx/templates/default.conf.template
EXPOSE 80 443
