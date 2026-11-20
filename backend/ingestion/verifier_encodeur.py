"""Vérifier l'encodeur ONNX avant de le mettre en ligne.

1. Mémoire : charge l'API comme en ligne (corpus + modèle + Claude), fait une recherche,
   et mesure le pic de mémoire. L'hébergement gratuit offre 512 Mo.
2. Vitesse : temps pour encoder une question.
3. Fidélité : sur un échantillon de passages, compare les vecteurs ONNX aux vecteurs
   actuels de corpus/vecteurs.npy (cosinus moyen, attendu > 0,97 si ces vecteurs viennent
   de sentence-transformers ; = 1 s'ils viennent déjà de l'encodeur ONNX).
   Ce test encode 200 longs passages d'un coup : il prend beaucoup plus de mémoire que le
   serveur, qui n'encode qu'une question courte à la fois. On le fait donc en dernier.

Usage (depuis backend/) :
    python -m ingestion.verifier_encodeur
"""

import random
import resource
import sys
import time

import numpy as np


def memoire_max_mo() -> float:
    pic = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return pic / 1e6 if sys.platform == "darwin" else pic / 1e3  # macOS : octets, Linux : Ko


def comparer_decoupeurs(recherche) -> None:
    """SentencePiece doit donner les mêmes jetons que tokenizer.json (s'il a été téléchargé)."""
    from app.encodeur import DOSSIER_MODELE, LONGUEUR_MAX
    from ingestion.vectoriser import PREFIXE_PASSAGE

    if not (DOSSIER_MODELE / "tokenizer.json").exists():
        print("Découpeurs : tokenizer.json absent, comparaison sautée")
        return
    from tokenizers import Tokenizer

    reference = Tokenizer.from_file(str(DOSSIER_MODELE / "tokenizer.json"))
    reference.enable_truncation(max_length=LONGUEUR_MAX)
    textes = [PREFIXE_PASSAGE + p["texte"] for p in random.Random(1).sample(recherche.passages, 500)]
    identiques = sum(recherche.modele.jetons(t) == reference.encode(t).ids for t in textes)
    print(f"Découpeurs : {identiques}/{len(textes)} passages découpés à l'identique")


def main() -> None:
    import app.main  # noqa: F401  (charge FastAPI, Anthropic… comme le serveur)
    from app.rag import PREFIXE_QUESTION, Recherche
    from ingestion.vectoriser import PREFIXE_PASSAGE

    debut = time.perf_counter()
    recherche = Recherche()
    print(f"Chargement corpus + modèle : {time.perf_counter() - debut:.1f} s")

    debut = time.perf_counter()
    recherche.modele.encoder([PREFIXE_QUESTION + "je veux changer de métier sans perdre mes années d'études"])
    print(f"Encodage d'une question : {(time.perf_counter() - debut) * 1000:.0f} ms")

    print("Exemple : « accepter ce qui ne dépend pas de nous » (profil stoïque)")
    for p in recherche.chercher("accepter ce qui ne dépend pas de nous", ["stoique"], k=3):
        print(f"  {p['similarite']:.3f}  {p['auteur']} — {p['texte'][:80]}…")

    pic = memoire_max_mo()  # mesuré AVANT le test de fidélité, qui est bien plus gourmand que le serveur
    if sys.platform == "darwin":  # macOS compte la mémoire plus large : la mesure qui compte est celle sous Linux
        print(f"Mémoire maximale du serveur : {pic:.0f} Mo sur macOS (sous Linux, comme sur Render : ~350 Mo)")
    else:
        print(f"Mémoire maximale du serveur : {pic:.0f} Mo  → {'OK pour 512 Mo' if pic < 420 else 'TROP proche de 512 Mo'}")

    comparer_decoupeurs(recherche)

    echantillon = random.Random(0).sample(range(len(recherche.passages)), 200)
    nouveaux = recherche.modele.encoder([PREFIXE_PASSAGE + recherche.passages[i]["texte"] for i in echantillon])
    cosinus = np.sum(nouveaux * recherche.vecteurs[echantillon], axis=1)
    print(f"Fidélité sur 200 passages : cosinus moyen {cosinus.mean():.4f}, minimum {cosinus.min():.4f}")


if __name__ == "__main__":
    main()
