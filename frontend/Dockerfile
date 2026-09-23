FROM python:3.10-slim

WORKDIR /app

# 复制项目代码
COPY . /app

# 安装最小依赖：streamlit + requests
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir streamlit requests

EXPOSE 8501

CMD ["streamlit", "run", "frontend/app.py", "--server.port=8501", "--server.address=0.0.0.0"]
