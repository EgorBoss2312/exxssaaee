# Frontend build
FROM node:20-alpine AS frontend
WORKDIR /fe
COPY frontend/package.json ./
RUN npm install
COPY frontend/ ./
# Если фронт на другом домене, чем API: --build-arg VITE_API_BASE_URL=https://api.example.com
ARG VITE_API_BASE_URL=
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

# API + статика
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir \
    --index-url https://download.pytorch.org/whl/cpu \
    torch==2.5.1+cpu
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY --from=frontend /fe/dist ./app/static

ENV PYTHONPATH=/app
ENV FRONTEND_DIST=/app/app/static
ENV UPLOAD_DIR=/app/data/uploads

RUN mkdir -p /app/data/uploads

EXPOSE 8000

# Render/Railway и др. задают PORT; локально и в compose — по умолчанию 8000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
