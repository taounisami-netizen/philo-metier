"""Orientation : le métier choisi par le calcul (orientation.py, grille/metiers.json)."""

import numpy as np
import pytest

from app.orientation import (
    BONUS_VOULU,
    CONTRAINTES,
    Orientation,
    Voie,
    charger_metiers,
    libelle_duree,
    meilleure_voie,
    voie_possible,
)
from app.schemas import AnalyseProfil, Entree, ScoreProfil, Situation

PROFILS = ["stoique", "epicurien", "sceptique", "batisseur", "createur", "moraliste", "contemplatif"]
METIERS = charger_metiers()


def analyse(dominant, secondaire, haut=0.44, moyen=0.25, bas=0.12):
    scores = {p: bas for p in PROFILS} | {dominant: haut, secondaire: moyen}
    ordre = sorted(PROFILS, key=lambda p: -scores[p])
    return AnalyseProfil(scores=[ScoreProfil(profil_id=p, points=1, points_max=10, score=scores[p]) for p in ordre],
                         dominant=dominant, secondaire=secondaire, ecart=haut - moyen, mixte=False)


def entree(poste="Étudiant", job_voulu=None, **moyens):
    situation = Situation(problematique="Changer de voie", **moyens) if moyens else None
    return Entree(poste_actuel=poste, statut="etudiant", job_voulu=job_voulu, situation=situation)


# --- Le tableau ----------------------------------------------------------------------------

def test_chaque_profil_a_au_moins_huit_metiers():
    for p in PROFILS:
        assert sum(m.profil_principal == p for m in METIERS) >= 8, p


def test_chaque_profil_a_un_metier_accessible_sans_diplome_ni_argent():
    """Sinon, une personne aux moyens serrés serait toujours envoyée vers un autre profil."""
    for p in PROFILS:
        assert any(m.profil_principal == p and any(v.niveau_requis == "sans" and v.cout == "finance" for v in m.voies)
                   for m in METIERS), p


def test_les_titres_sont_uniques():
    titres = [m.titre for m in METIERS]
    assert len(titres) == len(set(titres))


# --- Les voies d'accès ---------------------------------------------------------------------

VOIE = Voie(nom="Titre pro", niveau_requis="bac", duree_mois=9, cout="1000_5000", rythme="temps_plein")


@pytest.mark.parametrize("contraintes, attendu", [
    ({}, True),
    ({"diplome": "bac_2"}, True),
    ({"diplome": "cap_bep"}, False),        # il faut le bac
    ({"budget": "1000_5000"}, True),
    ({"budget": "moins_1000"}, False),      # trop cher
    ({"delai": "6_12_mois"}, True),
    ({"delai": "moins_6_mois"}, False),     # trop long
    ({"temps_hebdo": "temps_plein"}, True),
    ({"temps_hebdo": "10_20h"}, False),     # formation à temps plein
])
def test_voie_possible(contraintes, attendu):
    assert voie_possible(VOIE, contraintes) is attendu


def test_alternance_et_temps_partiel():
    alternance = VOIE.model_copy(update={"rythme": "alternance", "cout": "finance"})
    partiel = VOIE.model_copy(update={"rythme": "temps_partiel"})
    assert voie_possible(alternance, {"budget": "aucun"}) and not voie_possible(alternance, {"temps_hebdo": "10_20h"})
    assert voie_possible(partiel, {"temps_hebdo": "5_10h"}) and not voie_possible(partiel, {"temps_hebdo": "moins_5h"})


def test_la_voie_la_plus_accessible_est_retenue():
    pilote = next(m for m in METIERS if m.id == "pilote-de-ligne")
    assert meilleure_voie(pilote, {}).cout == "finance"                       # l'ENAC plutôt que l'école privée
    assert meilleure_voie(pilote, {"delai": "1_2_ans"}).cout == "plus_5000"   # seule voie en moins de 2 ans
    assert meilleure_voie(pilote, {"delai": "moins_6_mois"}) is None


def test_sans_diplome_connu_on_montre_la_voie_ouverte_au_plus_grand_nombre():
    cyber = next(m for m in METIERS if m.id == "analyste-cybersecurite")
    assert meilleure_voie(cyber, {}).niveau_requis == "bac"                         # pas la voie « après un bac+2 »
    assert meilleure_voie(cyber, {"diplome": "bac_2"}).niveau_requis == "bac_2"     # avec un bac+2 : la voie courte


def test_libelle_duree():
    assert [libelle_duree(m) for m in (5, 12, 18, 36)] == ["environ 5 mois", "environ 1 an", "environ 18 mois", "environ 3 ans"]


# --- Le choix ------------------------------------------------------------------------------

@pytest.mark.parametrize("dominant", PROFILS)
def test_sans_moyens_le_metier_vient_du_profil_dominant(dominant):
    secondaire = PROFILS[(PROFILS.index(dominant) + 3) % 7]
    resultat = Orientation(METIERS).orienter(analyse(dominant, secondaire), entree())
    assert resultat.principal.metier.profil_principal == dominant
    assert resultat.alternatifs[0].metier.profil_principal == dominant
    assert resultat.alternatifs[1].metier.profil_principal == secondaire
    assert resultat.assouplissements == []
    assert len({c.metier.id for c in [resultat.principal, *resultat.alternatifs]}) == 3


def test_memes_donnees_meme_choix():
    o = Orientation(METIERS)
    a = o.orienter(analyse("sceptique", "batisseur"), entree(diplome="bac", budget="aucun"))
    b = o.orienter(analyse("sceptique", "batisseur"), entree(diplome="bac", budget="aucun"))
    assert [c.metier.id for c in [a.principal, *a.alternatifs]] == [c.metier.id for c in [b.principal, *b.alternatifs]]


@pytest.mark.parametrize("dominant", PROFILS)
def test_avec_des_moyens_les_trois_metiers_sont_atteignables(dominant):
    secondaire = PROFILS[(PROFILS.index(dominant) + 1) % 7]
    moyens = {"diplome": "bac", "budget": "aucun", "delai": "6_12_mois", "temps_hebdo": "temps_plein"}
    resultat = Orientation(METIERS).orienter(analyse(dominant, secondaire), entree(**moyens))
    assert resultat.assouplissements == []
    for choix in [resultat.principal, *resultat.alternatifs]:
        assert voie_possible(choix.voie, moyens), choix.metier.titre


def test_moyens_impossibles_on_assouplit_dans_l_ordre():
    moyens = {"diplome": "sans", "budget": "aucun", "delai": "moins_6_mois", "temps_hebdo": "moins_5h"}
    resultat = Orientation(METIERS).orienter(analyse("batisseur", "sceptique"), entree(**moyens))
    assert resultat.assouplissements  # moins de 5 h par semaine : aucune formation possible
    assert resultat.assouplissements == list(CONTRAINTES[:len(resultat.assouplissements)])
    assert resultat.libelles_assouplissements[0] == "le délai"


def test_le_poste_actuel_n_est_jamais_propose():
    o = Orientation(METIERS)
    avant = o.orienter(analyse("sceptique", "batisseur"), entree()).principal.metier.titre
    apres = o.orienter(analyse("sceptique", "batisseur"), entree(poste=avant)).principal.metier.titre
    assert apres != avant


# --- Le texte libre (avec un faux modèle d'embeddings) ------------------------------------------

class FauxEncodeur:
    """Un vecteur par métier : un texte qui contient le titre d'un métier pointe vers lui."""

    def encoder(self, textes):
        vecteurs = np.full((len(textes), len(METIERS)), 0.01, dtype=np.float32)
        for i, texte in enumerate(textes):
            for j, m in enumerate(METIERS):
                if m.titre.lower() in texte.lower():
                    vecteurs[i, j] = 1.0
        return vecteurs / np.linalg.norm(vecteurs, axis=1, keepdims=True)


def test_le_metier_voulu_departage_les_metiers_du_profil():
    o = Orientation(METIERS, encodeur=FauxEncodeur())
    sans = o.orienter(analyse("sceptique", "batisseur"), entree()).principal.metier.titre
    avec = o.orienter(analyse("sceptique", "batisseur"), entree(job_voulu="Data analyst")).principal.metier.titre
    assert sans != "Data analyst" and avec == "Data analyst"


def test_le_texte_ne_fait_pas_passer_un_autre_profil_devant():
    o = Orientation(METIERS, encodeur=FauxEncodeur())
    resultat = o.orienter(analyse("moraliste", "contemplatif"), entree(job_voulu="Pilote de ligne"))
    assert resultat.principal.metier.profil_principal == "moraliste"  # écart de profil > bonus maximal
    assert 2 * BONUS_VOULU < 0.44 - 0.25
