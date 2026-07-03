FROM node:20-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm install -i https://registry.npmmirror.com

COPY . .
# 小内存服务器（<2GB）构建优化：限制 Node 内存上限避免进入 swap
ENV NODE_OPTIONS="--max-old-space-size=1536"
RUN npm run build

# 输出构建结果，供Nginx使用
FROM scratch

COPY --from=builder /app/dist /dist
