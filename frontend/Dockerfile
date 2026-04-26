# syntax=docker/dockerfile:1.7
#
# Multi-stage Dockerfile for the frontend.
#
#   `dev`  — Vite dev server with HMR. Used by docker-compose.yml.
#   `prod` — Built static bundle served by nginx.

# ---------- Base ----------
FROM node:20-alpine AS base
WORKDIR /app
ENV CI=true

# ---------- Dependency install ----------
FROM base AS deps
COPY package.json package-lock.json* ./
# `npm ci` if the lockfile is committed (preferred); fall back to install otherwise.
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

# ---------- Dev image ----------
FROM base AS dev
ENV NODE_ENV=development
COPY --from=deps /app/node_modules ./node_modules
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

# ---------- Builder ----------
FROM base AS builder
ENV NODE_ENV=production
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

# ---------- Prod image: nginx ----------
FROM nginx:1.27-alpine AS prod
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
