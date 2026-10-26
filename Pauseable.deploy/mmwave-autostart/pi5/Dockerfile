FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
COPY Pauseable.deploy/mmwave-autostart/pi5/runtime-requirements.txt /tmp/runtime-requirements.txt
RUN python -m pip install --no-cache-dir -r /tmp/runtime-requirements.txt
WORKDIR /app
COPY Pauseable.ai/mmwave/src/ /app/Pauseable.ai/mmwave/src/
COPY Pauseable.edge/mmwave-relay/ /app/Pauseable.edge/mmwave-relay/
COPY Pauseable.contracts/ /app/Pauseable.contracts/
WORKDIR /app/Pauseable.ai/mmwave/src
CMD ["sh", "-c", "exec python -u publish_wandering.py --stdin --silence-timeout-seconds 0.4 --db /var/lib/pauseable-wandering/wandering-publisher.sqlite3 --sample-ms 200 --max-gap-ms 300 --stale-after-ms 300 --window-ms 30000 --step-ms 10000 < /run/pauseable-wandering-input.fifo"]
