# Build stage: install the locked dependencies and build the static bundle.
FROM node:22-alpine AS build

WORKDIR /dashboard
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

# Runtime stage: nginx serves the bundle and forwards /api to the API container.
FROM nginx:1.29-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /dashboard/dist /usr/share/nginx/html

EXPOSE 80
