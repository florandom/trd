FROM python:3.13.16-slim-bookworm@sha256:5024f48ba9441d4b13a95d3945abc6365538e3a31109833367a1923523c6efed AS build
WORKDIR /app
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
RUN pip install --no-cache-dir uv==0.12.22
COPY pyproject.toml uv.lock ./
COPY backend ./backend
COPY apps/__init__.py ./apps/__init__.py
COPY apps/api ./apps/api
COPY apps/worker ./apps/worker
COPY apps/telegram ./apps/telegram
COPY apps/simulator ./apps/simulator
RUN uv sync --frozen --no-dev --no-editable --python /usr/local/bin/python

FROM python:3.13.16-slim-bookworm@sha256:5024f48ba9441d4b13a95d3945abc6365538e3a31109833367a1923523c6efed
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN groupadd --gid 10001 trd && useradd --uid 10001 --gid trd --no-create-home trd \
    && mkdir -p /var/trd/data /var/trd/logs && chown -R trd:trd /var/trd
COPY --from=build /app/.venv /app/.venv
COPY backend ./backend
COPY apps/__init__.py ./apps/__init__.py
COPY apps/api ./apps/api
COPY apps/worker ./apps/worker
COPY apps/telegram ./apps/telegram
COPY apps/simulator ./apps/simulator
COPY migrations ./migrations
COPY alembic.ini ./
COPY infra/__init__.py ./infra/__init__.py
COPY infra/scripts ./infra/scripts
USER trd
ENTRYPOINT ["python", "infra/scripts/container.py"]
CMD ["api"]
