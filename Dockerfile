FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    default-jdk \
    maven \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY cli/ ./cli/

RUN python -m pip install --no-cache-dir ./cli

ENTRYPOINT ["stitch"]
CMD ["--help"]
