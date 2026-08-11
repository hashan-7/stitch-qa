FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV CMAKE_ARGS="-DGGML_BLAS=ON -DGGML_BLAS_VENDOR=OpenBLAS -DGGML_CCACHE=OFF"
ENV FORCE_CMAKE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    libopenblas-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 user

USER user

ENV HOME=/home/user
ENV PATH=/home/user/.local/bin:$PATH
ENV HF_HOME=/home/user/.cache/huggingface
ENV MODEL_CACHE_DIR=/home/user/.cache/huggingface/hub

WORKDIR /home/user/app

COPY --chown=user:user requirements.txt .

RUN python -m pip install --user --no-cache-dir --upgrade pip && \
    python -m pip install --user --no-cache-dir -r requirements.txt

COPY --chown=user:user app.py .

EXPOSE 7860

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]