FROM python:3.10-slim

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend /app/backend
COPY frontend /app/frontend

ENV TCM_LEGACY_ROOT=/data/latest
ENV TCM_CHEMBL_DB=/data/chembl_36.db

EXPOSE 8010
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8010"]

