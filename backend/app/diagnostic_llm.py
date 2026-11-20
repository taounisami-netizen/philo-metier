"""Diagnostic : pourquoi la réponse de Claude est-elle refusée ?

Fait UN appel à Claude avec un cas proche d'un vrai visiteur (problématique + moyens),
puis affiche ce qui s'est passé : raison de l'arrêt, nombre de jetons écrits, type de
réponse (outil ou texte) et, si la validation échoue, les champs en cause.
Coût : environ un centime. La clé n'est jamais affichée.

Usage (depuis backend/, .venv activé) :
    python -m app.diagnostic_llm
    python -m app.diagnostic_llm "je veux aller dans le domaine public"
"""

import os
import random
import sys
import time

from pydantic import ValidationError

from .generation import (CONSIGNES, JETONS_MAX, OUTIL_RESULTAT, _lire_reponse, message_utilisateur,
                         modele_claude, passages_pour)
from .main import _charger_env  # noqa: F401  (charge backend/.env)
from .rag import Recherche
from .schemas import Entree, Reponse, Situation, SortieLLM
from .scoring import calculer_profil, charger_grille


def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("Pas de ANTHROPIC_API_KEY dans backend/.env")
    probleme = sys.argv[1] if len(sys.argv) > 1 else "je veux aller dans le domaine public"
    grille = charger_grille()
    alea = random.Random(0)
    reponses = [Reponse(question_id=q.id, option_ids=[alea.choice(q.options).id]) for q in grille.questions]
    entree = Entree(
        poste_actuel="étudiant en informatique", statut="etudiant", job_voulu=None,
        situation=Situation(problematique=probleme, temps_hebdo="5_10h", budget="moins_1000",
                            delai="6_12_mois", diplome="bac_2", mobilite="region"),
    )
    analyse = calculer_profil(grille, reponses)
    passages = passages_pour(Recherche(), grille, analyse, reponses, entree=entree)

    import anthropic

    print(f"Modèle : {modele_claude()}  |  problématique : « {probleme} »")
    debut = time.perf_counter()
    reponse = anthropic.Anthropic().messages.create(
        model=modele_claude(), max_tokens=JETONS_MAX[0], system=CONSIGNES,
        messages=[{"role": "user", "content": message_utilisateur(grille, entree, analyse, reponses, passages)}],
        tools=[OUTIL_RESULTAT], tool_choice={"type": "auto"},
    )
    duree = time.perf_counter() - debut
    print(f"Raison de l'arrêt : {reponse.stop_reason}  |  jetons écrits : {reponse.usage.output_tokens} / {JETONS_MAX[0]}"
          f"  |  durée : {duree:.0f} s (le site abandonne à 110 s)")
    print(f"Blocs reçus : {[b.type for b in reponse.content]}")
    try:
        sortie = SortieLLM.model_validate(_lire_reponse(reponse))
        print("Validation : OK")
        print(f"  métier : {sortie.metier_principal.model_dump()}")
        print(f"  réponse à la problématique : {'présente' if sortie.reponse_problematique else 'ABSENTE'}")
    except (ValueError, ValidationError) as e:
        print(f"Validation : ÉCHEC → {type(e).__name__}")
        print(str(e)[:1500])


if __name__ == "__main__":
    main()
