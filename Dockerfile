FROM python:3.13.15-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore

WORKDIR /app

COPY requirements.lock ./requirements.lock
RUN python -m pip install --require-hashes --requirement requirements.lock \
    && groupadd --system devradar \
    && useradd --system --gid devradar --home-dir /nonexistent --shell /usr/sbin/nologin devradar

COPY --chown=devradar:devradar alembic.ini ./alembic.ini
COPY --chown=devradar:devradar migrations ./migrations
COPY --chown=devradar:devradar src ./src

USER devradar

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "devradar.main:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]
