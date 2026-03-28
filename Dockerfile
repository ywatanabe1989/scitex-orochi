FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
COPY orochi/ orochi/

RUN pip install --no-cache-dir .

EXPOSE 9559 8559

ENV OROCHI_HOST=0.0.0.0
ENV OROCHI_DASHBOARD_PORT=8559
ENV OROCHI_DB=/data/orochi.db

VOLUME /data

CMD ["python", "-m", "orochi.server"]
