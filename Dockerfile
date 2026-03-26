FROM python:3.12-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim

WORKDIR /app
COPY --from=builder /install /usr/local
COPY main.py .
COPY newsfeed/ newsfeed/

RUN useradd --system --no-create-home appuser
USER appuser

CMD ["python", "main.py"]
