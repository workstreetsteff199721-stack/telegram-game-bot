FROM python:3.10-slim

# Установка Java (OpenJDK 17) для сборки и подписи APK
RUN apt-get update && \
    apt-get install -y --no-install-recommends openjdk-17-jre-headless zip unzip && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копирование файлов бота
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Запуск бота
CMD ["python", "bot_cloud.py"]
