"""Tester la recherche dans le corpus (avant de brancher le LLM).

Principe : la question est transformée en vecteur q (même modèle que les passages),
puis on calcule sa similarité avec chaque passage p_i :

    cos(q, p_i) = (q · p_i) / (‖q‖ · ‖p_i‖)

Tous les vecteurs étant normalisés (‖q‖ = ‖p_i‖ = 1), la similarité se réduit au
produit scalaire q · p_i. Pour N passages rangés dans une matrice P (N × d), les N
similarités s'obtiennent d'un coup : s = P q. On garde les k plus grandes.

Usage (depuis backend/) :
    python -m ingestion.rechercher "accepter ce qui ne dépend pas de nous"
    python -m ingestion.rechercher "le devoir de dire la vérité" --profil moraliste -k 3
"""

import argparse
from pathlib import Path

import numpy as np

from .vectoriser import DOSSIER_CORPUS, PREFIXE_QUESTION, charger_modele, charger_passages


def top_k(similarites: np.ndarray, k: int) -> np.ndarray:
    """Indices des k plus grandes valeurs, de la plus grande à la plus petite."""
    k = min(k, len(similarites))
    if k == 0:
        return np.array([], dtype=int)
    candidats = np.argpartition(-similarites, k - 1)[:k]  # O(N) au lieu d'un tri complet O(N log N)
    return candidats[np.argsort(-similarites[candidats])]


def rechercher(question: str, k: int = 5, profil: str | None = None, auteur: str | None = None,
               modele=None, passages=None, vecteurs=None) -> list[tuple[float, dict]]:
    passages = passages if passages is not None else charger_passages()
    vecteurs = vecteurs if vecteurs is not None else np.load(DOSSIER_CORPUS / "vecteurs.npy")
    modele = modele or charger_modele()

    q = modele.encoder([PREFIXE_QUESTION + question])[0]
    similarites = vecteurs @ q  # s_i = p_i · q

    # Filtre : on met à -inf les passages qui ne correspondent pas.
    masque = np.ones(len(passages), dtype=bool)
    if profil:
        masque &= np.array([profil in p["profils"] for p in passages])
    if auteur:
        masque &= np.array([p["auteur"].lower() == auteur.lower() for p in passages])
    similarites = np.where(masque, similarites, -np.inf)

    indices = [i for i in top_k(similarites, k) if np.isfinite(similarites[i])]
    return [(float(similarites[i]), passages[i]) for i in indices]


def main() -> None:
    parser = argparse.ArgumentParser(description="Recherche sémantique dans le corpus.")
    parser.add_argument("question")
    parser.add_argument("-k", type=int, default=5, help="nombre de passages (défaut 5)")
    parser.add_argument("--profil", help="ex. stoique, moraliste…")
    parser.add_argument("--auteur", help="ex. Kant, Épictète…")
    args = parser.parse_args()

    resultats = rechercher(args.question, k=args.k, profil=args.profil, auteur=args.auteur)
    for rang, (score, p) in enumerate(resultats, start=1):
        extrait = p["texte"].replace("\n", " ")
        extrait = extrait[:400] + ("…" if len(extrait) > 400 else "")
        print(f"\n#{rang}  similarité {score:.3f}  —  {p['auteur']}, {p['livre']}")
        print(f"    {p['section']}")
        print(f"    {extrait}")


if __name__ == "__main__":
    main()
