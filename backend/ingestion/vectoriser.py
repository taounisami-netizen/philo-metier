"""Étape 2.4 — Transformer chaque passage en vecteur (embedding).

Un modèle d'embeddings associe à chaque texte un vecteur de d nombres (d = 384 pour
multilingual-e5-small). Deux textes de sens proche ont des vecteurs proches, même
s'ils n'emploient pas les mêmes mots (« ce qui dépend de nous » ≈ « ce que je contrôle »).

Le modèle e5 attend un préfixe : « passage: » pour les textes du corpus, « query: »
pour les questions. Les vecteurs sont normalisés (norme 1), ce qui simplifie la
recherche (voir rechercher.py).

Le modèle tourne au format ONNX quantifié (voir app/encodeur.py) : le même code sert ici
et dans l'API, donc les passages et les questions sont encodés exactement de la même façon.

Usage (depuis backend/) :
    python -m app.encodeur --telecharger   → modele/ (une seule fois, ~120 Mo)
    python -m ingestion.vectoriser          → corpus/vecteurs.npy + corpus/index.json
"""

import json
from pathlib import Path

import numpy as np

DOSSIER_CORPUS = Path(__file__).parent.parent / "corpus"
PREFIXE_PASSAGE = "passage: "
PREFIXE_QUESTION = "query: "


def charger_modele():
    from app.encodeur import Encodeur
    return Encodeur()


def charger_passages() -> list[dict]:
    chemin = DOSSIER_CORPUS / "passages.jsonl"
    if not chemin.exists():
        raise SystemExit("corpus/passages.jsonl absent : lance d'abord python -m ingestion.decouper")
    with chemin.open(encoding="utf-8") as f:
        return [json.loads(ligne) for ligne in f]


def main() -> None:
    passages = charger_passages()
    from app.encodeur import NOM_MODELE
    print(f"{len(passages)} passages à vectoriser avec {NOM_MODELE}…")
    modele = charger_modele()
    textes = [PREFIXE_PASSAGE + p["texte"] for p in passages]
    vecteurs = modele.encoder(textes, progression=True)

    np.save(DOSSIER_CORPUS / "vecteurs.npy", vecteurs)
    index = {
        "modele": NOM_MODELE,
        "dimension": int(vecteurs.shape[1]),
        "nb_passages": len(passages),
        "ids": [p["id"] for p in passages],  # la ligne i de vecteurs.npy correspond à ids[i]
    }
    (DOSSIER_CORPUS / "index.json").write_text(json.dumps(index, ensure_ascii=False), "utf-8")
    print(f"→ vecteurs.npy : matrice {vecteurs.shape[0]} × {vecteurs.shape[1]}")


if __name__ == "__main__":
    main()
