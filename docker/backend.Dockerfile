FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/backend /app/config /app/data /app/logs /app/data/daily /app/data/realtime

RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple --upgrade pip

COPY requirements.txt ./backend/
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r ./backend/requirements.txt

COPY start.sh ./backend/
RUN chmod +x /app/backend/start.sh

EXPOSE 5000

CMD ["bash", "/app/backend/start.sh"]
