# Image de l'API pour un « Space » Docker de Hugging Face.
# Construite à partir du dossier préparé par deploy/preparer_space.sh.
FROM python:3.12-slim

# Hugging Face lance le conteneur avec l'utilisateur 1000 : on travaille dans son dossier.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    HF_HOME=/home/user/.cache/huggingface \
    PYTHONUNBUFFERED=1 \
    PRODUCTION=1
WORKDIR /home/user/app

# 1. Dépendances. PyTorch en version CPU : bien plus léger, et le serveur n'a pas de carte graphique.
COPY --chown=user requirements.txt requirements-ingestion.txt ./
RUN pip install --no-cache-dir --user torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir --user -r requirements-ingestion.txt

# 2. Le modèle d'embeddings est téléchargé pendant la construction, pas à chaque démarrage.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/multilingual-e5-small')"

# 3. Le code et le corpus (textes du domaine public + vecteurs). Aucun secret ici :
#    la clé Anthropic et CLE_INTERNE sont des « secrets » du Space, lus au démarrage.
COPY --chown=user app ./app
COPY --chown=user ingestion ./ingestion
COPY --chown=user corpus ./corpus

EXPOSE 7860
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
