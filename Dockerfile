FROM python:3.11-slim

WORKDIR /app

# 依赖先装（利用 Docker 层缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    --timeout 120 --retries 5 \
    -r requirements.txt

COPY . .

# 初始化数据库并写入演示数据
RUN python models.py && python seed_data.py

EXPOSE 5000

# 环境变量（运行时通过 -e 传入真实 key）
ENV AI_PROVIDER=anthropic
ENV AI_MODEL=claude-haiku-4-5-20251001

CMD ["python", "app.py"]
