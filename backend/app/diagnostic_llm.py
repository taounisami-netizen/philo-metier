"""Diagnostic : le résultat calculé, puis la rédaction par Claude, sur un cas réaliste.

Affiche d'abord ce que le calcul choisit (métiers, voies d'accès, citation, livre), puis fait
UN appel à Claude et affiche : raison de l'arrêt, jetons écrits, durée, et le texte rédigé.
Si la validation échoue, les champs en cause. Coût : environ un centime. La clé n'est jamais affichée.

Usage (depuis backend/, .venv activé) :
    python -m app.diagnostic_llm
    python -m app.diagnostic_llm "je veux aller dans le domaine public"
"""

import os
import random
import sys
import time

from pydantic import ValidationError

from .generation import (CONSIGNES, JETONS_MAX, OUTIL_RESULTAT, _lire_reponse, _verifier, graine,
                         message_utilisateur, modele_claude, passages_pour, sortie_calculee)
from .main import _charger_env  # noqa: F401  (charge backend/.env)
from .orientation import Orientation
from .rag import Recherche
from .schemas import DemandeResultat, Redaction
from .scoring import calculer_profil, charger_grille


def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("Pas de ANTHROPIC_API_KEY dans backend/.env")
    probleme = sys.argv[1] if len(sys.argv) > 1 else "je veux aller dans le domaine public"
    grille = charger_grille()
    alea_reponses = random.Random(0)
    demande = DemandeResultat(
        entree={"poste_actuel": "étudiant en informatique", "statut": "etudiant", "job_voulu": None,
                "situation": {"problematique": probleme, "temps_hebdo": "temps_plein", "budget": "moins_1000",
                              "delai": "6_12_mois", "diplome": "bac_2", "mobilite": "region"}},
        reponses=[{"question_id": q.id, "option_ids": [alea_reponses.choice(q.options).id]} for q in grille.questions],
    )
    recherche = Recherche()
    analyse = calculer_profil(grille, demande.reponses)
    alea = random.Random(graine(demande))
    passages = passages_pour(recherche, grille, analyse, demande.reponses, alea=alea, entree=demande.entree)
    debut = time.perf_counter()
    choix = Orientation(encodeur=recherche.modele).orienter(analyse, demande.entree)
    sortie = sortie_calculee(grille, demande.entree, analyse, passages, choix, alea)
    print(f"CALCUL ({(time.perf_counter() - debut) * 1000:.0f} ms, vecteurs des métiers compris)")
    print(f"  profil : {analyse.dominant} puis {analyse.secondaire}")
    for m in [sortie.metier_principal, *sortie.metiers_alternatifs]:
        print(f"  - {m.titre} : {m.acces.voie} ({m.acces.duree}, {m.acces.cout})")
    if choix.assouplissements:
        print(f"  assoupli : {', '.join(choix.libelles_assouplissements)}")
    print(f"  citation : {sortie.citation.auteur}, {sortie.citation.livre}  |  livre : {sortie.livre_a_lire.titre}")

    import anthropic

    contenu = message_utilisateur(grille, demande.entree, analyse, demande.reponses, sortie, choix, passages[0])
    print(f"\nRÉDACTION  |  modèle : {modele_claude()}  |  problématique : « {probleme} »")
    debut = time.perf_counter()
    reponse = anthropic.Anthropic().messages.create(
        model=modele_claude(), max_tokens=JETONS_MAX[0], system=CONSIGNES,
        messages=[{"role": "user", "content": contenu}],
        tools=[OUTIL_RESULTAT], tool_choice={"type": "auto"},
    )
    duree = time.perf_counter() - debut
    print(f"Raison de l'arrêt : {reponse.stop_reason}  |  jetons écrits : {reponse.usage.output_tokens} / {JETONS_MAX[0]}"
          f"  |  durée : {duree:.0f} s (le site abandonne à 110 s)")
    print(f"Blocs reçus : {[b.type for b in reponse.content]}")
    try:
        redaction = _verifier(Redaction.model_validate(_lire_reponse(reponse)), demande.entree)
        print("Validation : OK")
        print(f"  métier principal : {redaction.pourquoi_metier_principal}")
        print(f"  réponse à la problématique : {'présente' if redaction.reponse_problematique else 'ABSENTE'}")
    except (ValueError, ValidationError) as e:
        print(f"Validation : ÉCHEC → {type(e).__name__}")
        print(str(e)[:1500])


if __name__ == "__main__":
    main()
