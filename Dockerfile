# RAG فارسی — ایمیج سرور
# ساخت سبک (OpenAI/Ollama):            docker build -t rag-fa .
# همراه مدل‌های لوکال HuggingFace (CPU): docker build --build-arg INSTALL_HF=true -t rag-fa .
FROM python:3.12-slim

ARG INSTALL_HF=false
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TIKTOKEN_CACHE_DIR=/opt/tiktoken \
    HF_HOME=/app/data/hf-cache \
    DATA_DIR=/app/data \
    HOST=0.0.0.0 \
    PORT=8000

# Tesseract با زبان فارسی برای OCR صفحات اسکن‌شده
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-fas curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements-hf.txt ./
RUN pip install -r requirements.txt \
 && if [ "$INSTALL_HF" = "true" ]; then \
      pip install torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu \
      && pip install -r requirements-hf.txt; \
    fi \
 # توکنایزر را در زمان build دانلود می‌کنیم تا سرور به اینترنت وابسته نباشد
 && python -c "import tiktoken; tiktoken.get_encoding('o200k_base')"

COPY app ./app
COPY web ./web
COPY sample_data ./sample_data

RUN useradd --create-home --uid 1000 rag && mkdir -p /app/data && chown -R rag:rag /app /opt/tiktoken
USER rag

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

# یک worker: کارهای پس‌زمینه و کش BM25 درون فرایند نگه داشته می‌شوند
CMD ["sh", "-c", "uvicorn app.main:app --host $HOST --port $PORT --proxy-headers --forwarded-allow-ips='*'"]
