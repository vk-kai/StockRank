FROM node:20-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm install -i https://registry.npmmirror.com

COPY . .
RUN npm run build

# 输出构建结果，供Nginx使用
FROM scratch

COPY --from=builder /app/dist /dist
