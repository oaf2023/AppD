# MonedasAR Web (Next.js) - imagen multi-stage, standalone, non-root.
# Build desde la raíz del monorepo: docker build -f apps/web/Dockerfile -t platform/web:dev .
FROM node:22-alpine AS build

ENV NEXT_TELEMETRY_DISABLED=1

WORKDIR /repo

COPY package.json package-lock.json tsconfig.base.json ./
COPY apps/web ./apps/web

RUN npm ci
RUN npm --workspace apps/web run build

FROM node:22-alpine AS runner

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

WORKDIR /app

RUN addgroup -S -g 1001 nodejs && adduser -S -u 1001 -G nodejs nextjs

COPY --from=build --chown=nextjs:nodejs /repo/apps/web/.next/standalone ./
COPY --from=build --chown=nextjs:nodejs /repo/apps/web/.next/static ./apps/web/.next/static
COPY --from=build --chown=nextjs:nodejs /repo/apps/web/public ./apps/web/public

USER nextjs
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD node -e "fetch('http://127.0.0.1:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "apps/web/server.js"]
