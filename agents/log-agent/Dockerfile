FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_PREFER_BINARY=1 \
    HF_HOME=/opt/huggingface \
    MODEL_CACHE_DIR=/opt/huggingface/hub \
    HF_MODEL_REPO=Qwen/Qwen3-1.7B-GGUF \
    HF_MODEL_FILE=Qwen3-1.7B-Q5_K_M.gguf \
    HF_MODEL_REVISION=cd3d34a469f89b12676edce7d272750201959466 \
    HF_MODEL=Qwen/Qwen3-1.7B-GGUF:Q5_K_M \
    HF_LOCAL_FILES_ONLY=true \
    MODEL_QUANTIZATION=Q5_K_M \
    LLM_POLICY=FAILURES_ONLY \
    MODEL_MAX_INPUT_TOKENS=2048 \
    MODEL_MAX_NEW_TOKENS=64 \
    MODEL_MAX_GENERATION_SECONDS=105 \
    MODEL_FAILURE_COOLDOWN_SECONDS=180 \
    MODEL_CONTEXT_TOKENS=4096 \
    MODEL_BATCH_TOKENS=512 \
    MODEL_THREADS=2 \
    MODEL_THREADS_BATCH=2 \
    MODEL_TEMPERATURE=0.7 \
    MODEL_TOP_P=0.8 \
    MODEL_TOP_K=20 \
    MODEL_MIN_P=0 \
    MODEL_PRESENCE_PENALTY=1.0 \
    MODEL_REPEAT_PENALTY=1.0 \
    MODEL_SEED=17 \
    MODEL_USE_MMAP=true \
    LLM_MAX_FAILURES=8 \
    OMP_NUM_THREADS=2

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

RUN mkdir -p /opt/huggingface \
    && python -c "import os; from huggingface_hub import hf_hub_download; hf_hub_download(repo_id=os.environ['HF_MODEL_REPO'], filename=os.environ['HF_MODEL_FILE'], revision=os.environ['HF_MODEL_REVISION'], cache_dir=os.environ['MODEL_CACHE_DIR'])"

COPY *.py ./

RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app /opt/huggingface

USER appuser

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/ready', timeout=3)"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1", "--timeout-keep-alive", "30"]
