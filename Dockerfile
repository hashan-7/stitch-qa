FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    default-jdk \
    maven \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY cli/ ./cli/

RUN pip install --no-cache-dir -e ./cli

ENTRYPOINT ["stitch"]
CMD ["--help"]