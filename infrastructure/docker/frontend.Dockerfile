# Next.js frontend (standalone server). Build context: frontend/
# BACKEND_URL is where /api/* is proxied; Next resolves rewrites at build time, so it is a build arg.
FROM node:24-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY . .
ARG BACKEND_URL=http://backend:8080
ENV BACKEND_URL=$BACKEND_URL NEXT_TELEMETRY_DISABLED=1
# public/ may be empty, and git does not track empty directories (clean checkouts, CI)
RUN mkdir -p public && node node_modules/next/dist/bin/next build

FROM node:24-alpine
# The server only needs node; the bundled npm, npx and corepack carry their own CVEs (docs/ci.md).
RUN rm -rf /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/corepack \
    /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/corepack
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
WORKDIR /app
COPY --from=build --chown=node:node /src/.next/standalone ./
COPY --from=build --chown=node:node /src/.next/static ./.next/static
COPY --from=build --chown=node:node /src/public ./public
USER node
EXPOSE 3000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=6 \
    CMD node -e "fetch('http://localhost:3000/').then(r => process.exit(r.ok ? 0 : 1), () => process.exit(1))"
CMD ["node", "server.js"]
