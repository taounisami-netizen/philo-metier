"""Passer le questionnaire dans le terminal (pour tester l'étape 1 sans site).

Lancement, depuis le dossier backend/ :
    python -m app.quiz_cli              # tu réponds toi-même
    python -m app.quiz_cli --hasard     # réponses tirées au hasard (démo)
"""

import argparse
import random
import unicodedata

from pydantic import ValidationError

from .schemas import Entree, Reponse, Statut
from .scoring import MAX_CHOIX, calculer_profil, charger_grille


def demander(invite: str, valides: list[str] | None = None, optionnel: bool = False) -> str:
    while True:
        valeur = input(invite).strip()
        if not valeur and optionnel:
            return ""
        if valides is None and valeur:
            return valeur
        if valides is not None and valeur.lower() in valides:
            return valeur.lower()
        print("  Réponse non valide, réessaie.")


def sans_accents(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texte) if unicodedata.category(c) != "Mn")


def demander_statut() -> Statut:
    """Affiche un menu numéroté ; accepte le numéro ou le nom, avec ou sans accents."""
    statuts = list(Statut)
    print("Ton statut :")
    for i, s in enumerate(statuts, start=1):
        print(f"  {i}) {s.libelle}")
    while True:
        saisie = sans_accents(input("Ton choix (numéro ou nom) : ").strip().lower())
        if saisie.isdigit() and 1 <= int(saisie) <= len(statuts):
            return statuts[int(saisie) - 1]
        for s in statuts:
            if saisie in (s.value, sans_accents(s.libelle.lower())):
                return s
        print("  Réponse non valide, réessaie.")


def demander_choix(valides: list[str]) -> list[str]:
    """Accepte « b », « b,d », « b d » ou « bd »."""
    while True:
        brut = input(f"Ton choix (1 à {MAX_CHOIX} lettres, ex. « b » ou « b,d ») : ").lower()
        lettres = [c for c in brut if c.isalpha()]
        if 1 <= len(lettres) <= MAX_CHOIX and len(set(lettres)) == len(lettres) and all(l in valides for l in lettres):
            return lettres
        print("  Réponse non valide, réessaie.")


def barre(score: float, largeur: int = 20) -> str:
    plein = round(score * largeur)
    return "█" * plein + "·" * (largeur - plein)


def main() -> None:
    parser = argparse.ArgumentParser(description="Questionnaire philo → profil")
    parser.add_argument("--hasard", action="store_true", help="répondre au hasard")
    args = parser.parse_args()

    grille = charger_grille()

    if args.hasard:
        entree = Entree(poste_actuel="Étudiant en informatique", statut=Statut.ETUDIANT)
    else:
        print("\n=== Avant de commencer ===")
        while True:
            try:
                entree = Entree(
                    poste_actuel=demander("Ton poste actuel : "),
                    statut=demander_statut(),
                    job_voulu=demander("Le métier que tu voudrais faire (Entrée pour passer) : ", optionnel=True),
                )
                break
            except ValidationError as e:
                print(f"  Saisie invalide : {e.errors()[0]['msg']}")

    reponses: list[Reponse] = []
    for i, q in enumerate(grille.questions, start=1):
        if args.hasard:
            k = random.randint(1, MAX_CHOIX)
            choix = [o.id for o in random.sample(q.options, k)]
        else:
            print(f"\n[{i}/{len(grille.questions)}] {q.theme.upper()}")
            print(q.texte)
            for o in q.options:
                print(f"  {o.id}) {o.texte}")
            choix = demander_choix([o.id for o in q.options])
        texte_libre = None
        if q.relance and not args.hasard:
            texte_libre = input(f"{q.relance}\n(facultatif, Entrée pour passer) : ")
        reponses.append(Reponse(question_id=q.id, option_ids=choix, texte_libre=texte_libre))

    analyse = calculer_profil(grille, reponses)
    dominant = grille.profil(analyse.dominant)
    secondaire = grille.profil(analyse.secondaire)

    print("\n=== Tes scores ===")
    for s in analyse.scores:
        nom = grille.profil(s.profil_id).nom
        print(f"  {nom:<24} {barre(s.score)} {s.score:.2f}  ({s.points:g}/{s.points_max})")

    print(f"\nProfil dominant : {dominant.nom} — {dominant.trait_dominant}")
    if analyse.mixte:
        print(f"Profil mixte : très proche du profil « {secondaire.nom} » (écart {analyse.ecart:.2f})")
    print(f"Philosophes : {', '.join(dominant.philosophes)}")
    print(f"Métiers candidats : {', '.join(dominant.metiers)}")
    print(f"Livre à lire : {dominant.livres[0].titre} ({dominant.livres[0].auteur})")

    # Les idées des philosophes qui ont résonné avec tes réponses au profil dominant.
    echos = []
    for r in reponses:
        q = next(q for q in grille.questions if q.id == r.question_id)
        for o in q.options:
            if o.id in r.option_ids and analyse.dominant in o.poids:
                echos.append(o.echo)
    if echos:
        print("\nCe qui, dans tes réponses, fait écho à ce profil :")
        for e in echos[:4]:
            print(f"  • {e.philosophe} — {e.idee}")
    libres = [(r.question_id, r.texte_libre) for r in reponses if r.texte_libre]
    if libres:
        print("\nTes réponses libres (gardées pour l'analyse du LLM à l'étape 4) :")
        for qid, texte in libres:
            print(f"  [{qid}] {texte}")

    print(f"\n(Poste actuel : {entree.poste_actuel} — {entree.statut.libelle} — le choix du métier précis se fera par le LLM à l'étape 4.)")


if __name__ == "__main__":
    main()
