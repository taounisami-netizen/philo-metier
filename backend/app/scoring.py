"""Calcul du profil à partir des réponses au questionnaire.

Principe (détaillé dans le README) :
- chaque option donne des points à un ou deux profils ;
- l'utilisateur peut cocher 1 à MAX_CHOIX options par question : les points de la
  question sont alors partagés à parts égales entre ses choix ;
- score(p) = points obtenus par p / points maximum que p pouvait obtenir ;
- le profil dominant est celui qui a le score le plus haut.

Aucun LLM ici : le calcul est déterministe, rapide et testable.
"""

from collections import Counter
from fractions import Fraction
from dataclasses import dataclass
from pathlib import Path
from typing import get_args

from .schemas import (
    AnalyseProfil,
    FichierProfils,
    FichierQuestions,
    Profil,
    ProfilId,
    Question,
    Reponse,
    ScoreProfil,
)

DOSSIER_GRILLE = Path(__file__).parent / "grille"

# En dessous de cet écart entre le 1er et le 2e score, on parle de profil « mixte ».
SEUIL_MIXTE = 0.10

# Un profil doit être mesuré par au moins ce nombre de questions.
MIN_QUESTIONS_PAR_PROFIL = 5

# Toutes les questions ont le même nombre d'options.
NB_OPTIONS = 5

# Nombre maximum d'options cochées par question. Au-delà, la réponse ne dit plus
# grand-chose : obliger à choisir révèle les priorités.
MAX_CHOIX = 2


class GrilleInvalide(ValueError):
    """La grille (profils.json / questions.json) ne respecte pas les règles."""


class ReponsesInvalides(ValueError):
    """Les réponses envoyées ne correspondent pas au questionnaire."""


@dataclass(frozen=True)
class Grille:
    profils: list[Profil]
    questions: list[Question]

    def profil(self, profil_id: str) -> Profil:
        for p in self.profils:
            if p.id == profil_id:
                return p
        raise KeyError(profil_id)

    @property
    def ids_profils(self) -> list[str]:
        return [p.id for p in self.profils]


# ---------------------------------------------------------------------------
# Chargement et vérification de la grille
# ---------------------------------------------------------------------------

def charger_grille(dossier: Path = DOSSIER_GRILLE) -> Grille:
    profils = FichierProfils.model_validate_json((dossier / "profils.json").read_text("utf-8"))
    questions = FichierQuestions.model_validate_json((dossier / "questions.json").read_text("utf-8"))
    grille = Grille(profils=profils.profils, questions=questions.questions)
    verifier_grille(grille)
    return grille


def verifier_grille(grille: Grille) -> None:
    """Vérifie les règles de construction. Lève GrilleInvalide sinon."""
    erreurs: list[str] = []

    # 1. Les profils du JSON = exactement les 7 profils déclarés dans schemas.ProfilId.
    ids = grille.ids_profils
    if len(ids) != len(set(ids)):
        erreurs.append("des ids de profils sont en double")
    if set(ids) != set(get_args(ProfilId)):
        erreurs.append(f"profils.json {sorted(ids)} != ProfilId {sorted(get_args(ProfilId))}")

    # 2. Ids de questions uniques, ids d'options uniques dans chaque question.
    ids_questions = [q.id for q in grille.questions]
    if len(ids_questions) != len(set(ids_questions)):
        erreurs.append("des ids de questions sont en double")

    nb_questions_par_profil: Counter[str] = Counter()
    for q in grille.questions:
        # Même nombre d'options partout : sinon le raisonnement sur l'équilibre ne tient plus.
        if len(q.options) != NB_OPTIONS:
            erreurs.append(f"{q.id} : {len(q.options)} options au lieu de {NB_OPTIONS}")
        ids_options = [o.id for o in q.options]
        if len(ids_options) != len(set(ids_options)):
            erreurs.append(f"{q.id} : ids d'options en double")

        # 3. Un profil n'apparaît que dans UNE option par question.
        #    C'est cette règle qui garantit l'équilibre (voir score_moyen_aleatoire).
        compte = Counter(profil for o in q.options for profil in o.poids)
        for profil, n in compte.items():
            if n > 1:
                erreurs.append(f"{q.id} : {profil} apparaît dans {n} options")
        nb_questions_par_profil.update(compte.keys())

    # 4. Chaque profil est mesuré par assez de questions.
    for profil in ids:
        n = nb_questions_par_profil[profil]
        if n < MIN_QUESTIONS_PAR_PROFIL:
            erreurs.append(f"{profil} n'est mesuré que par {n} question(s) (min {MIN_QUESTIONS_PAR_PROFIL})")

    if erreurs:
        raise GrilleInvalide("Grille invalide :\n- " + "\n- ".join(erreurs))


# ---------------------------------------------------------------------------
# Calcul
# ---------------------------------------------------------------------------

def points_max(grille: Grille) -> dict[str, int]:
    """M(p) = somme, sur toutes les questions, du meilleur poids possible pour p."""
    return {
        p: sum(max(o.poids.get(p, 0) for o in q.options) for q in grille.questions)
        for p in grille.ids_profils
    }


def score_moyen_aleatoire(grille: Grille) -> dict[str, float]:
    """Score moyen de chaque profil si quelqu'un répond au hasard.

    Par linéarité de l'espérance, quel que soit le nombre k d'options cochées
    (chaque option ayant la probabilité k/n d'être cochée et rapportant w/k) :
        E[score(p)] = ( somme_q  moyenne_o w(q, o, p) ) / M(p)
    Si p n'apparaît que dans une option par question, cela vaut exactement 1/n,
    soit 0,20 avec 5 options : aucun profil n'est favorisé par le questionnaire.
    """
    maxi = points_max(grille)
    return {
        p: float(
            sum(Fraction(sum(o.poids.get(p, 0) for o in q.options), len(q.options)) for q in grille.questions)
            / maxi[p]
        )
        for p in grille.ids_profils
    }


def calculer_profil(grille: Grille, reponses: list[Reponse]) -> AnalyseProfil:
    questions = {q.id: q for q in grille.questions}

    # Validation : chaque question a exactement une réponse, avec une option existante.
    ids_repondus = [r.question_id for r in reponses]
    inconnues = set(ids_repondus) - questions.keys()
    if inconnues:
        raise ReponsesInvalides(f"questions inconnues : {sorted(inconnues)}")
    doublons = [qid for qid, n in Counter(ids_repondus).items() if n > 1]
    if doublons:
        raise ReponsesInvalides(f"questions répondues plusieurs fois : {sorted(doublons)}")
    manquantes = questions.keys() - set(ids_repondus)
    if manquantes:
        raise ReponsesInvalides(f"questions sans réponse : {sorted(manquantes)}")

    # Addition des points. Si k options sont cochées, chacune rapporte poids / k.
    # On calcule en fractions exactes (1/2, 1/3…) pour éviter les erreurs d'arrondi.
    points: dict[str, Fraction] = {p: Fraction(0) for p in grille.ids_profils}
    for r in reponses:
        options = {o.id: o for o in questions[r.question_id].options}
        choix = r.option_ids
        if len(choix) > MAX_CHOIX:
            raise ReponsesInvalides(f"{r.question_id} : {len(choix)} options cochées (max {MAX_CHOIX})")
        if len(choix) != len(set(choix)):
            raise ReponsesInvalides(f"{r.question_id} : la même option est cochée deux fois")
        for option_id in choix:
            if option_id not in options:
                raise ReponsesInvalides(f"{r.question_id} : option « {option_id} » inconnue")
            for profil, poids in options[option_id].poids.items():
                points[profil] += Fraction(poids, len(choix))

    # Normalisation : score(p) = points(p) / M(p), entre 0 et 1.
    maxi = points_max(grille)
    scores = [
        ScoreProfil(
            profil_id=p,
            points=round(float(points[p]), 4),
            points_max=maxi[p],
            score=round(float(points[p] / maxi[p]), 4),
        )
        for p in grille.ids_profils
    ]
    # Tri décroissant. sorted() est stable : en cas d'égalité, l'ordre de profils.json
    # départage, donc le résultat reste déterministe.
    scores.sort(key=lambda s: s.score, reverse=True)

    premier, second = scores[0], scores[1]
    ecart = round(premier.score - second.score, 4)
    return AnalyseProfil(
        scores=scores,
        dominant=premier.profil_id,
        secondaire=second.profil_id,
        ecart=ecart,
        mixte=ecart < SEUIL_MIXTE,
    )
