FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OPS_MODE=offline
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md LICENSE ./
COPY opspilot ./opspilot
RUN pip install --no-cache-dir . && useradd --create-home app && mkdir /workspace && chown app:app /workspace
USER app
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "opspilot.api:app", "--host", "0.0.0.0", "--port", "8000"]
