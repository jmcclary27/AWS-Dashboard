FROM node:22-alpine

WORKDIR /workspace

RUN corepack enable

ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}

COPY package.json pnpm-workspace.yaml /workspace/
COPY apps/web /workspace/apps/web

RUN pnpm install --no-frozen-lockfile

WORKDIR /workspace/apps/web

EXPOSE 3000

CMD ["pnpm", "dev", "--hostname", "0.0.0.0", "--port", "3000"]

