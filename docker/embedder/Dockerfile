# syntax=docker/dockerfile:1
# Embeddings only. The model is baked at build time because the internal
# compose network has no outbound access for a runtime ollama pull.
FROM ollama/ollama:0.12.6 AS seed

ENV OLLAMA_HOST=127.0.0.1:11434
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && ollama serve & \
    pid=$!; \
    until curl -fsS "http://127.0.0.1:11434/api/tags" >/dev/null; do sleep 1; done; \
    ollama pull nomic-embed-text; \
    kill "$pid"; \
    wait "$pid" 2>/dev/null || true

FROM ollama/ollama:0.12.6

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=seed /root/.ollama /opt/ollama-seed
COPY docker/embedder/entrypoint.sh /entrypoint.sh
COPY docker/embedder/healthcheck.sh /healthcheck.sh
RUN chmod +x /entrypoint.sh /healthcheck.sh

ENV OLLAMA_HOST=0.0.0.0:11434
ENV OLLAMA_KEEP_ALIVE=-1
ENV OLLAMA_NUM_PARALLEL=1
ENV OLLAMA_MAX_LOADED_MODELS=1
ENV EMBED_MODEL=nomic-embed-text

EXPOSE 11434

HEALTHCHECK --interval=30s --timeout=30s --start-period=180s --retries=5 \
    CMD /healthcheck.sh

ENTRYPOINT ["/entrypoint.sh"]
