FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --home /app app

COPY shared/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY shared/voiceagent_core /app/voiceagent_core
COPY shared/static /app/static
COPY config /app/config
COPY examples/foundry-voice-agent/src/ /app/

ENV AGENT_PROFILE_PATH=/app/config/agent-profile.json \
    STATIC_DIR=/app/static \
    PORT=8000

RUN chown -R app:app /app
USER app

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*", "--ws-ping-interval", "20"]
