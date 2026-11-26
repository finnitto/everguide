FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --timeout 300 --retries 5 -r requirements.txt
RUN groupadd --gid 10001 everguide && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin everguide && mkdir -p /var/lib/everguide/cache && chown -R 10001:10001 /var/lib/everguide
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini .
EXPOSE 8000
