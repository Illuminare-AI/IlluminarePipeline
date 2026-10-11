FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.cache/huggingface SENTENCE_TRANSFORMERS_HOME=/app/.cache/huggingface
WORKDIR /app

# Extras baked into the image. "db" adds the Postgres store (SQLAlchemy, asyncpg,
# sentence-transformers). CPU-only torch keeps that around 1 GB instead of the CUDA default.
# Build with --build-arg EXTRAS= for the slim in-memory-only image.
ARG EXTRAS=db
COPY pyproject.toml ./
COPY src ./src
RUN if echo "$EXTRAS" | grep -q db; then pip install torch --index-url https://download.pytorch.org/whl/cpu; fi \
 && pip install ".${EXTRAS:+[$EXTRAS]}"
# Pre-download the embedding model so a cold start does not fetch it from Hugging Face.
RUN if echo "$EXTRAS" | grep -q db; then python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"; fi

EXPOSE 8000
# Cloud Run and similar platforms inject PORT; local compose keeps 8000.
CMD ["sh", "-c", "exec uvicorn factcheck.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
