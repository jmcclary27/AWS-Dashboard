FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV HOME=/home/app

WORKDIR /app

COPY apps/api /app

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir . && \
    addgroup --system --gid 10001 app && \
    adduser --system --uid 10001 --ingroup app --home /home/app app && \
    chown -R app:app /app /home/app

USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
