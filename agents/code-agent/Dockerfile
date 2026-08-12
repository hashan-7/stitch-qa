FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PIP_NO_CACHE_DIR=1
ENV MODEL_CONTEXT_TOKENS=4096
ENV MODEL_BATCH_TOKENS=128
ENV MODEL_MAX_INPUT_TOKENS=3000
ENV SOURCE_MODEL_MAX_NEW_TOKENS=320
ENV REPAIR_MODEL_MAX_NEW_TOKENS=320
ENV REPAIR_MODEL_MAX_INPUT_TOKENS=2200
ENV MODEL_THREADS=2
ENV MODEL_THREADS_BATCH=2
ENV MODEL_USE_MMAP=true
ENV HF_MODEL_REPO=Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF
ENV HF_MODEL_FILE=qwen2.5-coder-1.5b-instruct-q4_k_m.gguf
ENV HF_MODEL_REVISION=f86cb2c1fa58255f8052cc32aeede1b7482d4361
ENV HF_LOCAL_FILES_ONLY=true
ENV MODEL_QUANTIZATION=Q4_K_M

RUN useradd -m -u 1000 user && \
    mkdir -p /home/user/app /home/user/.cache/huggingface/hub && \
    chown -R user:user /home/user

USER user

ENV HOME=/home/user
ENV PATH=/home/user/.local/bin:$PATH
ENV HF_HOME=/home/user/.cache/huggingface
ENV MODEL_CACHE_DIR=/home/user/.cache/huggingface/hub

WORKDIR /home/user/app

COPY --chown=user:user requirements.txt .
RUN python -m pip install --user --upgrade pip && \
    python -m pip install --user \
    --prefer-binary \
    --only-binary=llama-cpp-python \
    --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu \
    -r requirements.txt

RUN python -c "import os; from huggingface_hub import hf_hub_download; hf_hub_download(repo_id=os.environ['HF_MODEL_REPO'], filename=os.environ['HF_MODEL_FILE'], revision=os.environ['HF_MODEL_REVISION'], cache_dir=os.environ['MODEL_CACHE_DIR'])"

COPY --chown=user:user app.py .

EXPOSE 7860

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
