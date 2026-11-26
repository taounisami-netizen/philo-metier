"""Orientation : le métier choisi par le calcul (orientation.py, grille/metiers.json)."""

import numpy as np
import pytest

from app.orientation import (
    BONUS_VOULU,
    CONTRAINTES,
    ecart,
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


def _sans_voies_en_poste():
    metiers = []
    for m in METIERS:
        voies = [v for v in m.voies if v.rythme != "en_poste"]
        if voies:
            metiers.append(m.model_copy(update={"voies": voies}))
    return metiers


def test_moyens_impossibles_on_assouplit_dans_l_ordre():
    # Sans les métiers où l'on est formé en poste, moins de 5 h par semaine ne laisse aucune formation possible.
    moyens = {"diplome": "sans", "budget": "aucun", "delai": "moins_6_mois", "temps_hebdo": "moins_5h"}
    resultat = Orientation(_sans_voies_en_poste()).orienter(analyse("batisseur", "sceptique"), entree(**moyens))
    assert resultat.assouplissements
    assert resultat.assouplissements == list(CONTRAINTES[:len(resultat.assouplissements)])
    assert resultat.libelles_assouplissements[0] == "le délai"
    # ce qui dépasse est dit en clair sous la voie
    assert any(c.ecarts for c in resultat.choix_affiches)


def test_apres_assouplissement_la_voie_qui_depasse_le_moins():
    moyens = {"diplome": "sans", "budget": "aucun", "delai": "6_12_mois", "temps_hebdo": "moins_5h"}
    resultat = Orientation(_sans_voies_en_poste()).orienter(analyse("batisseur", "stoique"), entree(**moyens))
    for c in resultat.choix_affiches:
        meilleur = min(ecart(v, moyens) for v in c.metier.voies if v.rythme != "en_poste")
        assert ecart(c.voie, moyens) == meilleur
    # un long cursus (3 ans de bac pro) ne passe pas devant un titre professionnel de quelques mois
    assert resultat.principal.voie.duree_mois <= 12


def test_ouvrier_sans_diplome_ni_temps_pistes_realistes():
    """Le cas qui a motivé le rythme « en poste » : usine, sans diplôme, sans budget, moins de 5 h par semaine."""
    moyens = {"diplome": "sans", "budget": "aucun", "delai": "6_12_mois", "temps_hebdo": "moins_5h"}
    for dom, sec in [("batisseur", "stoique"), ("stoique", "batisseur"), ("moraliste", "epicurien"), ("sceptique", "batisseur")]:
        r = Orientation(METIERS).orienter(analyse(dom, sec), entree(poste="Ouvrier à l'usine", **moyens))
        assert r.assouplissements == [], (dom, r.libelles_assouplissements)
        for c in r.choix_affiches:
            assert c.voie.niveau_requis == "sans" and c.voie.cout == "finance" and not c.ecarts, c.metier.id
            assert c.voie.rythme == "en_poste", c.metier.id


def test_en_poste_compatible_avec_peu_de_temps_et_sans_delai():
    voie = next(v for m in METIERS if m.id == "aiguilleur-du-rail" for v in m.voies)
    assert voie.rythme == "en_poste"
    assert voie_possible(voie, {"temps_hebdo": "moins_5h", "delai": "moins_6_mois", "diplome": "bac", "budget": "aucun"})


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


# --- Métiers à l'étranger et liens ---------------------------------------------------------

def test_chaque_profil_a_un_metier_a_l_etranger():
    for p in PROFILS:
        assert any(m.lieu == "etranger" and m.profil_principal == p for m in METIERS), p


def test_presque_tous_les_metiers_ont_un_lien_officiel():
    sans_lien = [m.id for m in METIERS if not m.liens]
    assert len(sans_lien) <= 5, sans_lien  # pas de fiche ONISEP : ingénieur, chef de projet, tatoueur…


def test_lien_vers_un_site_inconnu_refuse():
    from app.schemas import Lien
    with pytest.raises(ValueError):
        Lien(titre="Piège", url="javascript:alert(1)")
    with pytest.raises(ValueError):
        Lien(titre="Autre site", url="https://exemple.com/metier")


def _tous_les_choix(resultat):
    return [c.metier for c in resultat.choix_affiches]


@pytest.mark.parametrize("dominant, secondaire", [(p, PROFILS[(i + 3) % 7]) for i, p in enumerate(PROFILS)])
def test_pas_d_etranger_sans_l_avoir_demande(dominant, secondaire):
    o = Orientation(METIERS)
    for e in (entree(), entree(mobilite="france"), entree(mobilite="ville", diplome="sans", budget="aucun")):
        r = o.orienter(analyse(dominant, secondaire), e)
        assert r.etranger is None
        assert all(m.lieu == "france" for m in _tous_les_choix(r))


@pytest.mark.parametrize("dominant, secondaire", [(p, PROFILS[(i + 3) % 7]) for i, p in enumerate(PROFILS)])
def test_pret_a_partir_recoit_une_piste_a_l_etranger(dominant, secondaire):
    r = Orientation(METIERS).orienter(analyse(dominant, secondaire), entree(mobilite="etranger"))
    choix = _tous_les_choix(r)
    assert any(m.lieu == "etranger" for m in choix)
    assert len({m.id for m in choix}) == len(choix)  # jamais deux fois le même métier
    if r.etranger:
        assert r.etranger.metier.lieu == "etranger"


def test_piste_etranger_respecte_les_moyens_quand_c_est_possible():
    r = Orientation(METIERS).orienter(analyse("epicurien", "createur"),
                                      entree(mobilite="etranger", diplome="sans", budget="aucun"))
    piste = r.etranger or next(c for c in r.choix_affiches if c.metier.lieu == "etranger")
    assert piste.voie.niveau_requis == "sans" and piste.voie.cout in ("finance", "moins_1000") or r.assouplissements
