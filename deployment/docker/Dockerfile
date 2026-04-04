FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ src/
COPY hub/ hub/
COPY orochi/ orochi/
COPY manage.py ./

RUN pip install --no-cache-dir .

EXPOSE 8559

ENV DJANGO_SETTINGS_MODULE=orochi.settings
ENV DJANGO_ALLOWED_HOSTS=*
ENV OROCHI_DB_PATH=/data/db.sqlite3

COPY deployment/docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

VOLUME /data

ENTRYPOINT ["/app/entrypoint.sh"]
