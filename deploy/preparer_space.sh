#!/usr/bin/env bash
# Prépare le dossier à envoyer sur Hugging Face : deploy/build/space/
# Usage (depuis la racine du projet) : bash deploy/preparer_space.sh
set -euo pipefail
cd "$(dirname "$0")/.."

SORTIE=deploy/build/space
CORPUS=backend/corpus
for f in passages.jsonl vecteurs.npy index.json; do
  [ -f "$CORPUS/$f" ] || { echo "ERREUR : $CORPUS/$f manquant. Lance d'abord le pipeline d'ingestion."; exit 1; }
done

rm -rf "$SORTIE"
mkdir -p "$SORTIE/corpus"
cp deploy/huggingface/Dockerfile deploy/huggingface/README.md "$SORTIE/"
cp backend/requirements.txt backend/requirements-ingestion.txt "$SORTIE/"
cp -R backend/app backend/ingestion "$SORTIE/"
cp "$CORPUS/passages.jsonl" "$CORPUS/vecteurs.npy" "$CORPUS/index.json" "$SORTIE/corpus/"
find "$SORTIE" -name "__pycache__" -type d -prune -exec rm -rf {} +

# Garde-fou : aucun fichier de secrets ne doit partir.
if find "$SORTIE" -name ".env*" | grep -q .; then
  echo "ERREUR : un fichier .env se trouve dans $SORTIE. Rien n'a été envoyé."; exit 1
fi
if grep -rIl "sk-ant-" "$SORTIE" >/dev/null 2>&1; then
  echo "ERREUR : quelque chose qui ressemble à une clé Anthropic se trouve dans $SORTIE. Rien n'a été envoyé."; exit 1
fi

echo "Prêt à envoyer : $SORTIE ($(du -sh "$SORTIE" | cut -f1))"
