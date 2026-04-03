FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ src/

RUN pip install --no-cache-dir .

EXPOSE 9559 8559

ENV SCITEX_OROCHI_HOST=0.0.0.0
ENV SCITEX_OROCHI_DASHBOARD_PORT=8559
ENV SCITEX_OROCHI_DB=/data/orochi.db

VOLUME /data

CMD ["scitex-orochi", "serve"]
