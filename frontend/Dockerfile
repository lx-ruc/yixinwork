# 前端镜像：Vite 构建 → nginx 托管（同源反代 /api，SSE 不缓冲）
ARG REGISTRY=""
FROM ${REGISTRY}node:22-alpine AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm config set registry https://registry.npmmirror.com && npm ci

COPY . .
RUN npm run build

FROM ${REGISTRY}nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
