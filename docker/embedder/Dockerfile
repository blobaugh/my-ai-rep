# syntax=docker/dockerfile:1
# Official Ollama image (linux/amd64 on the droplet). Model files live in a volume.
FROM ollama/ollama:0.12.6

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
COPY docker/embedder/entrypoint.sh /entrypoint.sh
COPY docker/embedder/healthcheck.sh /healthcheck.sh
RUN chmod +x /entrypoint.sh /healthcheck.sh

ENV OLLAMA_HOST=0.0.0.0:11434
ENV OLLAMA_KEEP_ALIVE=-1
ENV OLLAMA_NUM_PARALLEL=1
ENV OLLAMA_MAX_LOADED_MODELS=1
ENV EMBED_MODEL=nomic-embed-text

EXPOSE 11434

HEALTHCHECK --interval=30s --timeout=15s --start-period=120s --retries=5 \
    CMD /healthcheck.sh

ENTRYPOINT ["/entrypoint.sh"]
