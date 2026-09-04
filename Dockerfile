FROM eclipse-temurin:17-jre-jammy

# Установка Python и необходимых утилит
RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 python3-pip zip unzip && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY . .

# Создание простого веб-сервера для health check Render и запуск бота
CMD ["python3", "bot_cloud.py"]
