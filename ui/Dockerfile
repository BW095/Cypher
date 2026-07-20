# Cypher frontend — build the Vite React app, serve it with nginx (which also
# reverse-proxies /api to the backend, with SSE streaming support).
#
# Build context is the repo root:  docker build -f ui/Dockerfile .

# ---- build stage ----
FROM node:22-alpine AS build
WORKDIR /app
COPY ui/package.json ui/package-lock.json* ./
RUN npm ci
COPY ui/ ./
RUN npm run build

# ---- serve stage ----
FROM nginx:1.27-alpine
COPY ui/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
