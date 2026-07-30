FROM python:3.13-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir --pre -r requirements.txt

COPY . .
EXPOSE 8088
CMD ["python", "main.py"]
