FROM python:3.13.15-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PYTHONPATH=/app/src \
    HOME=/home/devradar

WORKDIR /app

COPY requirements.lock ./requirements.lock
# Browser build and OS dependencies must match the pinned Playwright package.
# Source: https://playwright.dev/python/docs/browsers#install-system-dependencies
RUN python -m pip install --require-hashes --requirement requirements.lock \
    && python -m playwright install --with-deps --only-shell chromium \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system devradar \
    && useradd --system --gid devradar --create-home --home-dir /home/devradar \
        --shell /usr/sbin/nologin devradar \
    && chmod -R a+rX /ms-playwright

COPY --chown=devradar:devradar alembic.ini ./alembic.ini
COPY --chown=devradar:devradar migrations ./migrations
COPY --chown=devradar:devradar src ./src

USER devradar

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "devradar.main:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]
