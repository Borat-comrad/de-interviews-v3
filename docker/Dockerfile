FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY etl etl
COPY ml ml
COPY sql sql
COPY tests tests
RUN useradd --uid 10001 --create-home pipeline
USER pipeline
CMD ["python", "-m", "etl.pipeline"]
