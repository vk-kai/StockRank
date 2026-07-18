FROM python:3.11-slim

WORKDIR /app

RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates \
        chromium \
        curl \
        fonts-liberation \
        fonts-noto-cjk \
        tzdata \
        xauth \
        xvfb \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=Asia/Shanghai
ENV THS_BROWSER_PATH=/usr/bin/chromium
# 让 Python/pip 输出不缓冲：配合 `docker build --progress=plain` 可实时看到 pip 下载进度
ENV PYTHONUNBUFFERED=1

RUN mkdir -p /app/backend /app/config /app/data /app/logs /app/data/daily /app/data/realtime

RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ --upgrade pip

# 重型稳定依赖单独一层：后续加小依赖（改 requirements.txt）时这层缓存命中，不重装 akshare/pandas/numpy
COPY requirements-base.txt ./backend/
RUN pip install --no-cache-dir --progress-bar on \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    -r ./backend/requirements-base.txt

# 易变依赖（新功能小包，如 OTP 的 pyotp/qrcode）：base 缓存命中时这里通常秒级完成
COPY requirements.txt ./backend/
RUN pip install --no-cache-dir --progress-bar on \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    -r ./backend/requirements.txt

COPY start.sh ./backend/
RUN chmod +x /app/backend/start.sh

EXPOSE 5000

CMD ["bash", "/app/backend/start.sh"]
