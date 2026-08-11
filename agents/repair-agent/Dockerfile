FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/huggingface \
    MODEL_CACHE_DIR=/opt/huggingface/hub \
    HF_MODEL_REPO=ibm-granite/granite-4.0-1b-GGUF \
    HF_MODEL_FILE=granite-4.0-1b-Q4_K_M.gguf \
    HF_MODEL_REVISION=b27c2fe3f211b7f44e80fa620177aea371099aaa \
    MODEL_QUANTIZATION=Q4_K_M \
    HF_MODEL=ibm-granite/granite-4.0-1b-GGUF:Q4_K_M \
    HF_LOCAL_FILES_ONLY=true \
    LLM_ENABLED=true \
    MODEL_CONTEXT_TOKENS=4096 \
    MODEL_BATCH_TOKENS=512 \
    MODEL_MAX_INPUT_TOKENS=2800 \
    MODEL_MAX_NEW_TOKENS=256 \
    MODEL_MAX_GENERATION_SECONDS=90 \
    MODEL_THREADS=2 \
    MODEL_THREADS_BATCH=2 \
    MODEL_TEMPERATURE=0.1 \
    MODEL_TOP_P=0.9 \
    MODEL_PROMPT_CACHE_MB=256 \
    MODEL_SEED=17 \
    MODEL_USE_MMAP=true \
    OMP_NUM_THREADS=2

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m pip install --upgrade pip \
    && python -m pip install --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu -r requirements.txt

RUN mkdir -p /opt/huggingface \
    && python -c "import os; from huggingface_hub import hf_hub_download; hf_hub_download(repo_id=os.environ['HF_MODEL_REPO'], filename=os.environ['HF_MODEL_FILE'], revision=os.environ['HF_MODEL_REVISION'], cache_dir=os.environ['MODEL_CACHE_DIR'])"

COPY app.py .

RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app /opt/huggingface

USER appuser

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/ready', timeout=3)"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1", "--timeout-keep-alive", "30"]
