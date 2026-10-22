FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OPS_STATE_DIR=/app/var
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY pyproject.toml README.md LICENSE ./
COPY opspilot ./opspilot
COPY data ./data
RUN pip install --no-cache-dir --no-deps . \
    && mkdir var \
    && useradd --create-home app \
    && chown -R app:app /app
USER app
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "opspilot.api:app", "--host", "0.0.0.0", "--port", "8000"]
