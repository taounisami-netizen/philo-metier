# API philo-metier pour Render (plan gratuit : 512 Mo de mémoire, 0,1 processeur).
# Construit depuis backend/ :  docker build -t philo-metier-api backend
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PRODUCTION=1 \
    ONNX_THREADS=1 \
    MODELE_DIR=/srv/modele

WORKDIR /srv

# 1. Dépendances (sans PyTorch : l'encodeur tourne avec onnxruntime).
COPY requirements.txt ./
RUN pip install -r requirements.txt

# 2. Modèle d'embeddings (~120 Mo), téléchargé une fois pendant la construction.
COPY app/__init__.py app/encodeur.py ./app/
RUN python -m app.encodeur --telecharger

# 3. Code et corpus (passages + vecteurs déjà calculés).
COPY app ./app
COPY ingestion ./ingestion
COPY corpus/passages.jsonl corpus/vecteurs.npy corpus/index.json ./corpus/

# Le serveur ne tourne pas en administrateur.
RUN useradd --create-home --uid 1000 api
USER api

# Render choisit le port avec la variable PORT (10000 par défaut).
EXPOSE 10000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
