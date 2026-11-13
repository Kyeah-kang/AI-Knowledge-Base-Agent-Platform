# ---------- 阶段 1：构建静态文件 ----------
FROM node:24-alpine AS build
WORKDIR /app

# 先拷依赖清单，利用层缓存（改代码不用重装依赖）
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# 容器里走 nginx 同源反代，所以 API 前缀是相对路径
ARG VITE_API_BASE_URL=/api/v1
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN npm run build

# ---------- 阶段 2：nginx 托管 + 反代 ----------
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -qO- http://127.0.0.1/ >/dev/null 2>&1 || exit 1

CMD ["nginx", "-g", "daemon off;"]