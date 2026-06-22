# M2 — Classificação (NLP). Imagem do serviço FastAPI + consumidor RabbitMQ.
FROM python:3.12-slim

# Logs sem buffer e sem .pyc
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    # cache do HuggingFace num diretório que dá p/ montar como volume
    HF_HOME=/cache/huggingface

WORKDIR /app

# Dependências primeiro (camada cacheável)
COPY requirements.txt .
RUN pip install -r requirements.txt

# Código + artefato do modelo
COPY embedding_transformer.py modelo_denuncias.joblib ./
COPY app ./app

EXPOSE 8000

# 1 worker: o modelo é pesado e o consumidor RabbitMQ deve existir uma vez por
# processo. Para escalar, suba MAIS CONTAINERS (--scale m2=N), não mais workers.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]