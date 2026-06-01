FROM python:3.11-slim

WORKDIR /app

RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        chromium \
        curl \
        fonts-liberation \
        fonts-noto-cjk \
        nodejs \
        xvfb \
    && rm -rf /var/lib/apt/lists/*

ENV THS_BROWSER_PATH=/usr/bin/chromium

RUN mkdir -p /app/backend /app/config /app/data /app/logs /app/data/daily /app/data/realtime

RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple --upgrade pip

COPY requirements.txt ./backend/
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r ./backend/requirements.txt

COPY start.sh ./backend/
RUN chmod +x /app/backend/start.sh

EXPOSE 5000

CMD ["bash", "/app/backend/start.sh"]
