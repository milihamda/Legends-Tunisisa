FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libjpeg62-turbo \
        zlib1g \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py welcome_card.py punishment_card.py level_up_card.py bot_all_in_one.py .env.example ./
COPY punshmentimg/ ./punshmentimg/
RUN mkdir -p data
# Bake levels into the image so redeploys restore the last committed snapshot
# (Render Free has no persistent disk — runtime saves are lost without this).
COPY data/levels_database.json data/levels_database.json

ENV PYTHONUNBUFFERED=1
EXPOSE 8080

CMD ["python", "bot.py"]
