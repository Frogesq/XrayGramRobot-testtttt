FROM python:3.11-slim

# Отключаем буферизацию вывода Python (чтобы логи сразу шли в консоль)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Устанавливаем ffmpeg и системные утилиты
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Сначала копируем только requirements.txt — так кэшируется слой pip install
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Копируем остальные файлы проекта
COPY . .

# Создаём папки, которые бот использует при старте
RUN mkdir -p downloads mini_app

# Порт для Mini App сервера (aiohttp)
EXPOSE 3000

# Запуск бота
CMD ["python", "main.py"]
