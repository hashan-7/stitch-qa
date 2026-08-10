FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TOKENIZERS_PARALLELISM=false \
    HF_HOME=/tmp/huggingface \
    HF_MODEL=Qwen/Qwen3-1.7B \
    LLM_POLICY=FAILURES_ONLY \
    MODEL_MAX_INPUT_TOKENS=3072 \
    MODEL_MAX_NEW_TOKENS=512 \
    MODEL_MAX_GENERATION_SECONDS=80 \
    MODEL_DTYPE=float32 \
    MODEL_TEMPERATURE=0.7 \
    MODEL_TOP_P=0.8 \
    MODEL_TOP_K=20 \
    MODEL_REPETITION_PENALTY=1.05 \
    MODEL_SEED=17 \
    LLM_MAX_GROUPS=2 \
    TORCH_NUM_THREADS=2 \
    OMP_NUM_THREADS=2 \
    MKL_NUM_THREADS=2

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

COPY *.py ./

RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /tmp/huggingface \
    && chown -R appuser:appuser /app /tmp/huggingface

USER appuser

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/ready', timeout=3)"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1", "--timeout-keep-alive", "30"]
