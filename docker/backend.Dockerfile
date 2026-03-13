FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 创建必要的目录结构
RUN mkdir -p /app/backend /app/data /app/logs /app/data/daily /app/data/realtime

# 升级pip并设置清华PyPI镜像
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple --upgrade pip

# 复制 requirements.txt 并安装依赖
COPY requirements.txt ./backend/
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r ./backend/requirements.txt

# 复制 start.sh 并添加执行权限
COPY start.sh ./backend/
RUN chmod +x /app/backend/start.sh

EXPOSE 5000

CMD ["bash", "/app/backend/start.sh"]