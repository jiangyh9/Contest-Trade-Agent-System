FROM python:3.10-slim

WORKDIR /app

# 安装编译依赖（akshare 等包可能需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc && \
    rm -rf /var/lib/apt/lists/*

# 复制项目代码
COPY . /app

# 安装原项目依赖 + FastAPI/Uvicorn
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir fastapi uvicorn

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
