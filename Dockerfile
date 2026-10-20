FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY python_app/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY python_app/ /app/
RUN mkdir -p /app/var/media

EXPOSE 8020
CMD ["python", "manage.py", "runserver", "0.0.0.0:8020"]
