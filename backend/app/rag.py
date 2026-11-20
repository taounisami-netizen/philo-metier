"""Recherche dans le corpus, côté API.

Le modèle d'embeddings et les vecteurs sont chargés UNE fois au démarrage du serveur
(quelques secondes), puis chaque recherche ne coûte qu'un produit matrice-vecteur.
Le calcul est expliqué dans ingestion/rechercher.py et dans le README.
"""

import json
from pathlib import Path

import numpy as np

from ingestion.rechercher import top_k

DOSSIER_CORPUS = Path(__file__).parent.parent / "corpus"
PREFIXE_QUESTION = "query: "


class CorpusIntrouvable(RuntimeError):
    pass


class Recherche:
    def __init__(self, dossier: Path = DOSSIER_CORPUS):
        fichiers = [dossier / "passages.jsonl", dossier / "vecteurs.npy", dossier / "index.json"]
        manquants = [f.name for f in fichiers if not f.exists()]
        if manquants:
            raise CorpusIntrouvable(
                f"Fichiers manquants dans corpus/ : {', '.join(manquants)}. "
                "Lance le pipeline d'ingestion (voir README, étape 2)."
            )
        with (dossier / "passages.jsonl").open(encoding="utf-8") as f:
            self.passages = [json.loads(ligne) for ligne in f]
        self.vecteurs = np.load(dossier / "vecteurs.npy")
        index = json.loads((dossier / "index.json").read_text("utf-8"))
        if len(self.passages) != self.vecteurs.shape[0]:
            raise CorpusIntrouvable("passages.jsonl et vecteurs.npy ne correspondent pas : relance ingestion.vectoriser")

        from sentence_transformers import SentenceTransformer  # import lent
        self.modele = SentenceTransformer(index["modele"])
        self._profils = [set(p["profils"]) for p in self.passages]

    def vecteur(self, texte: str) -> np.ndarray:
        return self.modele.encode([PREFIXE_QUESTION + texte], normalize_embeddings=True)[0]

    def chercher(self, question: str, profils: list[str], k: int = 4) -> list[dict]:
        """Les k passages les plus proches de la question, chez les auteurs des profils donnés."""
        similarites = self.vecteurs @ self.vecteur(question)
        masque = np.array([bool(ps & set(profils)) for ps in self._profils])
        similarites = np.where(masque, similarites, -np.inf)
        return [
            self.passages[i] | {"similarite": round(float(similarites[i]), 4)}
            for i in top_k(similarites, k) if np.isfinite(similarites[i])
        ]
