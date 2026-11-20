"""Étape 2.4 — Transformer chaque passage en vecteur (embedding).

Un modèle d'embeddings associe à chaque texte un vecteur de d nombres (d = 384 pour
multilingual-e5-small). Deux textes de sens proche ont des vecteurs proches, même
s'ils n'emploient pas les mêmes mots (« ce qui dépend de nous » ≈ « ce que je contrôle »).

Le modèle e5 attend un préfixe : « passage: » pour les textes du corpus, « query: »
pour les questions. Les vecteurs sont normalisés (norme 1), ce qui simplifie la
recherche (voir rechercher.py).

Le modèle (~470 Mo) est téléchargé automatiquement au premier lancement, puis gardé
en cache. Sur un Mac Apple Silicon, le calcul utilise la puce graphique (MPS).

Usage (depuis backend/) :
    python -m ingestion.vectoriser       → corpus/vecteurs.npy + corpus/index.json
"""

import json
from pathlib import Path

import numpy as np

DOSSIER_CORPUS = Path(__file__).parent.parent / "corpus"
MODELE = "intfloat/multilingual-e5-small"
PREFIXE_PASSAGE = "passage: "
PREFIXE_QUESTION = "query: "


def charger_modele(nom: str = MODELE):
    from sentence_transformers import SentenceTransformer  # import lent : seulement si besoin
    return SentenceTransformer(nom)


def charger_passages() -> list[dict]:
    chemin = DOSSIER_CORPUS / "passages.jsonl"
    if not chemin.exists():
        raise SystemExit("corpus/passages.jsonl absent : lance d'abord python -m ingestion.decouper")
    with chemin.open(encoding="utf-8") as f:
        return [json.loads(ligne) for ligne in f]


def main() -> None:
    passages = charger_passages()
    print(f"{len(passages)} passages à vectoriser avec {MODELE}…")
    modele = charger_modele()
    textes = [PREFIXE_PASSAGE + p["texte"] for p in passages]
    vecteurs = modele.encode(textes, batch_size=32, normalize_embeddings=True, show_progress_bar=True)
    vecteurs = np.asarray(vecteurs, dtype=np.float32)

    np.save(DOSSIER_CORPUS / "vecteurs.npy", vecteurs)
    index = {
        "modele": MODELE,
        "dimension": int(vecteurs.shape[1]),
        "nb_passages": len(passages),
        "ids": [p["id"] for p in passages],  # la ligne i de vecteurs.npy correspond à ids[i]
    }
    (DOSSIER_CORPUS / "index.json").write_text(json.dumps(index, ensure_ascii=False), "utf-8")
    print(f"→ vecteurs.npy : matrice {vecteurs.shape[0]} × {vecteurs.shape[1]}")


if __name__ == "__main__":
    main()
