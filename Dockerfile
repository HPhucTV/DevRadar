FROM python:3.13.15-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PYTHONPATH=/app/src \
    HOME=/home/devradar \
    DEVRADAR_EMBEDDING_MODEL_PATH=/opt/devradar/models/multilingual-e5-small

WORKDIR /app

COPY requirements.lock ./requirements.lock
# Browser build and OS dependencies must match the pinned Playwright package.
# Source: https://playwright.dev/python/docs/browsers#install-system-dependencies
RUN python -m pip install --require-hashes --requirement requirements.lock \
    && python -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='intfloat/multilingual-e5-small', revision='614241f622f53c4eeff9890bdc4f31cfecc418b3', local_dir='/opt/devradar/models/multilingual-e5-small', allow_patterns=['config.json','special_tokens_map.json','tokenizer.json','tokenizer_config.json','onnx/model.onnx'])" \
    && python -m playwright install --with-deps --only-shell chromium \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system devradar \
    && useradd --system --gid devradar --create-home --home-dir /home/devradar \
        --shell /usr/sbin/nologin devradar \
    && chmod -R a+rX /ms-playwright

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
