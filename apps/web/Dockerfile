FROM node:22-alpine AS base

WORKDIR /workspace

RUN npm install --global pnpm@9.15.0

FROM base AS dependencies

COPY package.json pnpm-workspace.yaml pnpm-lock.yaml /workspace/
COPY apps/web/package.json /workspace/apps/web/package.json

RUN pnpm install --frozen-lockfile

FROM base AS builder

ARG NEXT_PUBLIC_API_BASE_URL=/api/v1
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}

# This value gates the browser auth shell and is therefore intentionally a
# build argument rather than a runtime-only container setting.
ARG NEXT_PUBLIC_AUTH_ENABLED=false
ENV NEXT_PUBLIC_AUTH_ENABLED=${NEXT_PUBLIC_AUTH_ENABLED}

COPY --from=dependencies /workspace/node_modules /workspace/node_modules
COPY --from=dependencies /workspace/apps/web/node_modules /workspace/apps/web/node_modules
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml /workspace/
COPY apps/web /workspace/apps/web

RUN pnpm --filter web build

FROM node:22-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV HOSTNAME=0.0.0.0
ENV PORT=3000

RUN addgroup --system --gid 10001 nodejs \
    && adduser --system --uid 10001 nextjs

COPY --from=builder --chown=nextjs:nodejs /workspace/apps/web/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /workspace/apps/web/.next/static ./apps/web/.next/static

EXPOSE 3000

USER nextjs

WORKDIR /app/apps/web

CMD ["node", "server.js"]
