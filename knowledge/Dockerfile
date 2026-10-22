FROM python:3.12-slim
WORKDIR /app
COPY knowledge/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY knowledge /app/knowledge
ENV PYTHONUNBUFFERED=1 TOKENIZERS_PARALLELISM=false
EXPOSE 8010
CMD ["uvicorn", "knowledge.server:app", "--host", "0.0.0.0", "--port", "8010"]
