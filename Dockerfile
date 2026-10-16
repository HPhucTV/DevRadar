FROM python:3.14-slim-trixie@sha256:ce40764625a4ff50df3548277632e7f96c4e77fe75fa848aae9885476e7df5a4

ARG DEVRADAR_INSTALL_BROWSER=false

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PYTHONPATH=/app/src \
    HOME=/home/devradar \
    DEVRADAR_EMBEDDING_MODEL_PATH=/opt/devradar/models/multilingual-minilm

WORKDIR /app

COPY requirements.lock ./requirements.lock
# Browser build and OS dependencies must match the pinned Playwright package.
# Source: https://playwright.dev/python/docs/browsers#install-system-dependencies
RUN python -m pip install --require-hashes --requirement requirements.lock \
    && python -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q', revision='faf4aa4225822f3bc6376869cb1164e8e3feedd0', local_dir='/opt/devradar/models/multilingual-minilm', allow_patterns=['config.json','special_tokens_map.json','tokenizer.json','tokenizer_config.json','model_optimized.onnx'])" \
    && if [ "$DEVRADAR_INSTALL_BROWSER" = "true" ]; then \
        python -m playwright install --with-deps --only-shell chromium; \
    fi \
    && apt-get update \
    && apt-get -y dist-upgrade \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system devradar \
    && useradd --system --gid devradar --create-home --home-dir /home/devradar \
        --shell /usr/sbin/nologin devradar \
    && if [ "$DEVRADAR_INSTALL_BROWSER" = "true" ]; then \
        chmod -R a+rX /ms-playwright; \
    fi \
    && rm -rf /usr/local/lib/python3.13/site-packages/pip* /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.13

# Official Linux ONNX Runtime builds enable telemetry by default. Keep local
# embedding inference network-silent and avoid persistent identifiers.
# Source: https://github.com/microsoft/onnxruntime/blob/main/docs/Privacy.md#disabling-telemetry
ENV ORT_DISABLE_TELEMETRY=1

COPY --chown=devradar:devradar alembic.ini ./alembic.ini
COPY --chown=devradar:devradar migrations ./migrations
COPY --chown=devradar:devradar src ./src

USER devradar

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "devradar.main:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]
