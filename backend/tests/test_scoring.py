import json
from collections import Counter
from pathlib import Path

import pytest

from app.schemas import Reponse, Resultat
from app.scoring import (
    MAX_CHOIX,
    NB_OPTIONS,
    Grille,
    GrilleInvalide,
    ReponsesInvalides,
    calculer_profil,
    charger_grille,
    points_max,
    score_moyen_aleatoire,
    verifier_grille,
)

EXEMPLE = Path(__file__).parent.parent / "app" / "exemples" / "resultat_exemple.json"


@pytest.fixture(scope="module")
def grille() -> Grille:
    return charger_grille()


def reponses_vers(grille: Grille, profil: str) -> list[Reponse]:
    """Pour chaque question, choisit l'option qui donne le plus de points à `profil`."""
    return [
        Reponse(question_id=q.id, option_ids=[max(q.options, key=lambda o: o.poids.get(profil, 0)).id])
        for q in grille.questions
    ]


# --- La grille --------------------------------------------------------------

def test_la_grille_se_charge(grille):
    assert len(grille.profils) == 7
    assert len(grille.questions) == 13


def test_aucun_profil_favorise_par_le_hasard(grille):
    # Un profil dans au plus une option par question => score moyen = 1/n exactement.
    for profil, moyenne in score_moyen_aleatoire(grille).items():
        assert moyenne == pytest.approx(1 / NB_OPTIONS), profil


@pytest.mark.parametrize("k", range(1, MAX_CHOIX + 1))
def test_moyenne_exacte_par_enumeration(grille, k):
    """Vérifie la formule sans faire confiance à la démonstration :
    on énumère tous les choix possibles de k options pour chaque question."""
    from fractions import Fraction
    from itertools import combinations

    maxi = points_max(grille)
    for p in grille.ids_profils:
        total = Fraction(0)
        for q in grille.questions:
            sous_ensembles = list(combinations(q.options, k))
            total += sum(
                sum(Fraction(o.poids.get(p, 0), k) for o in choix) for choix in sous_ensembles
            ) / len(sous_ensembles)
        assert total / maxi[p] == Fraction(1, NB_OPTIONS), p


def test_chaque_profil_mesure_par_assez_de_questions(grille):
    for p in grille.ids_profils:
        n = sum(any(p in o.poids for o in q.options) for q in grille.questions)
        assert n >= 8, (p, n)


def test_une_grille_desequilibree_est_refusee(grille):
    q = grille.questions[0].model_copy(deep=True)
    q.options[1].poids = {"stoique": 1}  # stoique apparaît alors dans les options a et b
    mauvaise = Grille(profils=grille.profils, questions=[q, *grille.questions[1:]])
    with pytest.raises(GrilleInvalide, match="stoique apparaît dans 2 options"):
        verifier_grille(mauvaise)


# --- Le calcul --------------------------------------------------------------

@pytest.mark.parametrize(
    "profil",
    ["stoique", "epicurien", "sceptique", "batisseur", "createur", "moraliste", "contemplatif"],
)
def test_chaque_profil_est_atteignable(grille, profil):
    analyse = calculer_profil(grille, reponses_vers(grille, profil))
    assert analyse.dominant == profil
    score = next(s for s in analyse.scores if s.profil_id == profil)
    assert score.points == score.points_max  # score parfait = 1
    assert score.score == 1.0


def test_meme_reponses_meme_resultat(grille):
    r = reponses_vers(grille, "sceptique")
    assert calculer_profil(grille, r) == calculer_profil(grille, r)


def test_scores_tries_et_ecart(grille):
    analyse = calculer_profil(grille, reponses_vers(grille, "moraliste"))
    valeurs = [s.score for s in analyse.scores]
    assert valeurs == sorted(valeurs, reverse=True)
    assert analyse.ecart == pytest.approx(valeurs[0] - valeurs[1], abs=1e-4)


def test_question_manquante(grille):
    r = reponses_vers(grille, "stoique")[:-1]
    with pytest.raises(ReponsesInvalides, match="sans réponse"):
        calculer_profil(grille, r)


def test_question_en_double(grille):
    r = reponses_vers(grille, "stoique")
    with pytest.raises(ReponsesInvalides, match="plusieurs fois"):
        calculer_profil(grille, [*r, r[0]])


def test_option_inconnue(grille):
    r = reponses_vers(grille, "stoique")
    r[0] = Reponse(question_id=r[0].question_id, option_ids=["z"])
    with pytest.raises(ReponsesInvalides, match="inconnue"):
        calculer_profil(grille, r)


# --- Réponses multiples -------------------------------------------------------

def test_deux_choix_partagent_les_points(grille):
    # q01 : a = stoique 2, c = moraliste 2, d = epicurien 2.
    # Référence : réponses « épicurien » (q01 = d). On remplace q01 par a + c :
    # stoique et moraliste gagnent chacun 2/2 = 1 point.
    r = reponses_vers(grille, "epicurien")
    r[0] = Reponse(question_id="q01", option_ids=["a", "c"])
    seul = calculer_profil(grille, reponses_vers(grille, "epicurien"))
    double = calculer_profil(grille, r)
    pts = lambda a, p: next(s.points for s in a.scores if s.profil_id == p)
    assert pts(double, "stoique") - pts(seul, "stoique") == 1
    assert pts(double, "moraliste") - pts(seul, "moraliste") == 1
    assert pts(seul, "epicurien") - pts(double, "epicurien") == 2


def test_trop_de_choix(grille):
    r = reponses_vers(grille, "stoique")
    r[0] = Reponse(question_id="q01", option_ids=["a", "b", "c"][: MAX_CHOIX + 1])
    with pytest.raises(ReponsesInvalides, match="max"):
        calculer_profil(grille, r)


def test_meme_option_cochee_deux_fois(grille):
    r = reponses_vers(grille, "stoique")
    r[0] = Reponse(question_id="q01", option_ids=["a", "a"])
    with pytest.raises(ReponsesInvalides, match="deux fois"):
        calculer_profil(grille, r)


def test_reponse_vide_refusee():
    with pytest.raises(ValueError):
        Reponse(question_id="q01", option_ids=[])


# --- Le format du résultat ----------------------------------------------------

def test_exemple_de_resultat_valide(grille):
    resultat = Resultat.model_validate_json(EXEMPLE.read_text("utf-8"))
    # Les points max de l'exemple doivent correspondre à la vraie grille.
    maxi = points_max(grille)
    for s in resultat.profil.scores:
        assert s.points_max == maxi[s.profil_id]


def test_ecart_job_voulu_obligatoire_si_job_voulu():
    data = json.loads(EXEMPLE.read_text("utf-8"))
    data["sortie"]["ecart_job_voulu"] = None
    with pytest.raises(ValueError, match="ecart_job_voulu est obligatoire"):
        Resultat.model_validate(data)


# --- Statuts ------------------------------------------------------------------

def test_chaque_statut_a_un_libelle():
    from app.schemas import Statut
    for s in Statut:
        assert s.libelle and s.libelle[0].isupper(), s
    assert Statut.ETUDIANT.libelle == "Étudiant"


# --- Réponses libres ----------------------------------------------------------

def test_texte_libre_ne_change_pas_le_score(grille):
    r = reponses_vers(grille, "sceptique")
    avec = [x.model_copy(update={"texte_libre": "Je lui parlerais d'abord en privé."}) for x in r]
    assert calculer_profil(grille, r) == calculer_profil(grille, avec)


def test_texte_libre_vide_devient_none():
    assert Reponse(question_id="q04", option_ids=["a"], texte_libre="   ").texte_libre is None


# ---------------------------------------------------------------------------
# Équité du profil dominant
# ---------------------------------------------------------------------------

def _reponses_au_hasard(grille: Grille, rng, max_choix: int) -> list[Reponse]:
    return [
        Reponse(
            question_id=q.id,
            option_ids=rng.sample([o.id for o in q.options], rng.randint(1, max_choix)),
            texte_libre=None,
        )
        for q in grille.questions
    ]


def _egalite_parfaite(grille: Grille, profils: tuple[str, str]) -> list[Reponse]:
    """Des réponses où deux profils finissent exactement à égalité en tête."""
    import random

    rng = random.Random(0)
    while True:
        rep = _reponses_au_hasard(grille, rng, 1)
        a = calculer_profil(grille, rep)
        tete = {s.profil_id for s in a.scores if s.score == a.scores[0].score}
        if tete == set(profils):
            return rep


@pytest.mark.parametrize("max_choix", [1, 2])
def test_aucun_profil_ne_sort_en_tete_trop_souvent(grille, max_choix):
    """Au hasard, chaque profil doit sortir dominant entre 12 % et 17 % du temps (1/7 = 14,3 %).

    Avant le départage neutre, le stoïque gagnait toutes ses égalités (ordre de profils.json)
    et le sceptique montait à 17,4 %, le créateur descendait à 11,2 %.
    """
    import random

    rng, n = random.Random(2026), 8000
    compte = Counter(calculer_profil(grille, _reponses_au_hasard(grille, rng, max_choix)).dominant for _ in range(n))
    for profil in grille.ids_profils:
        assert 0.12 <= compte[profil] / n <= 0.17, (profil, compte[profil] / n)


def test_une_egalite_ne_favorise_pas_l_ordre_du_fichier(grille):
    """Quand deux profils sont à égalité en tête, celui écrit en premier dans profils.json
    ne doit gagner qu'environ une fois sur deux (avant : à chaque fois)."""
    import random

    rang = {p: i for i, p in enumerate(grille.ids_profils)}
    rng = random.Random(1)
    gagne, total = 0, 0
    for _ in range(4000):
        a = calculer_profil(grille, _reponses_au_hasard(grille, rng, 1))
        tete = [s.profil_id for s in a.scores if s.score == a.scores[0].score]
        if len(tete) == 2:
            total += 1
            gagne += a.dominant == min(tete, key=rang.get)
    assert total >= 200
    assert 0.4 <= gagne / total <= 0.6, (gagne, total)


def test_departage_deterministe_et_independant_de_l_ordre(grille):
    rep = _egalite_parfaite(grille, ("stoique", "epicurien"))
    a = calculer_profil(grille, rep)
    b = calculer_profil(grille, list(reversed(rep)))
    assert a.dominant == b.dominant and a.secondaire == b.secondaire
    assert a.ecart == 0 and a.mixte
