"""Orientation : choisir le métier par le calcul, sans IA.

Principe (détaillé dans docs/SCORING.md, partie « Orientation ») :

1. Affinité profil. Chaque métier du tableau (grille/metiers.json) est relié à 1 à 3 profils,
   avec un poids w (1 = profil principal du métier). Son affinité avec l'utilisateur est la
   moyenne pondérée de ses scores :  A(m) = Σ w_p · S(p) / Σ w_p.

2. Ressemblance avec le texte libre. Le poste actuel et le métier voulu sont comparés à la
   description de chaque métier avec le modèle d'embeddings (cosinus). On centre-réduit ces
   similarités sur tous les métiers (z-score, borné à ±2) pour ne garder que l'écart à la moyenne :
       note(m) = A(m) + 0,03 · z_voulu(m) + 0,015 · z_poste(m)
   Le bonus reste petit (au plus ±0,09) : il départage des métiers proches pour le profil,
   sans faire passer un métier d'un autre profil devant.

3. Réalisme. Quand l'utilisateur indique ses moyens (diplôme, budget, délai, temps), un
   métier n'est retenu que s'il a au moins une voie d'accès compatible. Si moins de trois
   métiers passent (dont un de ses deux profils principaux), on assouplit dans l'ordre :
   délai, temps disponible, budget, diplôme, et on le dit.

4. Choix. Métier principal = meilleure note. Puis un autre métier du profil dominant, et
   un métier du profil secondaire. Égalités départagées par l'ordre du tableau : mêmes
   réponses → même résultat.

5. Étranger. Certains métiers ne s'exercent qu'à l'étranger (lieu = « etranger ») : ils ne
   sont proposés qu'à qui a répondu « Prêt à partir à l'étranger » à la question Mobilité.
   Pour cette personne, si aucun des trois métiers choisis n'est à l'étranger, on ajoute
   une piste à l'étranger : le métier « etranger » le mieux noté.
"""

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field

from .schemas import AnalyseProfil, Entree, Lien, ProfilId

FICHIER_METIERS = Path(__file__).parent / "grille" / "metiers.json"

Niveau = Literal["sans", "cap_bep", "bac", "bac_2", "bac_3", "bac_5"]
Cout = Literal["finance", "moins_1000", "1000_5000", "plus_5000"]
# en_poste : on est embauché d'abord, et formé pendant son temps de travail, payé. Ce n'est pas du temps
# à prendre en plus : la voie convient même à qui n'a que quelques heures par semaine (on change d'emploi).
Rythme = Literal["alternance", "temps_plein", "temps_partiel", "en_poste"]
Lieu = Literal["france", "etranger"]

ORDRE_DIPLOME = ["sans", "cap_bep", "bac", "bac_2", "bac_3", "bac_5"]
BUDGET_RANG = {"aucun": 0, "moins_1000": 1, "1000_5000": 2, "plus_5000": 3}
COUT_RANG = {"finance": 0, "moins_1000": 1, "1000_5000": 2, "plus_5000": 3}
DELAI_MAX_MOIS = {"moins_6_mois": 6, "6_12_mois": 12, "1_2_ans": 24, "plus_2_ans": None}
TEMPS_RANG = {"moins_5h": 0, "5_10h": 1, "10_20h": 2, "temps_plein": 3}
# Temps disponible minimal pour suivre chaque rythme de formation.
RYTHME_TEMPS_MIN = {"temps_partiel": TEMPS_RANG["5_10h"], "temps_plein": TEMPS_RANG["temps_plein"],
                    "alternance": TEMPS_RANG["temps_plein"], "en_poste": TEMPS_RANG["moins_5h"]}

CONTRAINTES = ("delai", "temps_hebdo", "budget", "diplome")  # aussi l'ordre d'assouplissement
LIBELLES_CONTRAINTES = {"delai": "le délai", "temps_hebdo": "le temps disponible",
                        "budget": "le budget", "diplome": "le diplôme requis"}

BONUS_VOULU = 0.03
BONUS_POSTE = 0.015
Z_MAX = 2.0
NB_MIN_POSSIBLES = 3

LIBELLES_NIVEAU = {"sans": "sans diplôme", "cap_bep": "CAP", "bac": "bac", "bac_2": "bac +2", "bac_3": "bac +3",
                   "bac_5": "bac +5"}
# Une unité d'écart (un an de trop, un cran de temps ou de budget en trop) retire autant à la note.
# Ordre de grandeur : l'affinité d'un métier du profil dominant dépasse celle du secondaire d'environ 0,2.
PENALITE_ECART = 0.05

LIBELLES_COUT = {"finance": "gratuit pour toi (financé)", "moins_1000": "moins de 1 000 €",
                 "1000_5000": "entre 1 000 et 5 000 €", "plus_5000": "plus de 5 000 €"}


class Voie(BaseModel):
    nom: str
    niveau_requis: Niveau
    duree_mois: int = Field(gt=0)
    cout: Cout
    rythme: Rythme


class FicheMetier(BaseModel):
    id: str
    titre: str
    profils: dict[ProfilId, float] = Field(min_length=1)
    description: str
    voies: list[Voie] = Field(min_length=1)
    lieu: Lieu = "france"
    liens: list[Lien] = []
    romes: list[str] = []  # codes ROME : recherche d'offres et de formations en alternance (étage 2)

    @property
    def profil_principal(self) -> str:
        return max(self.profils, key=self.profils.get)


class FichierMetiers(BaseModel):
    version: int
    metiers: list[FicheMetier]


def charger_metiers(fichier: Path = FICHIER_METIERS) -> list[FicheMetier]:
    metiers = FichierMetiers.model_validate(json.loads(fichier.read_text("utf-8"))).metiers
    ids = [m.id for m in metiers]
    if len(ids) != len(set(ids)):
        raise ValueError("metiers.json : identifiants en double")
    return metiers


# ---------------------------------------------------------------------------
# Réalisme : les voies d'accès compatibles avec les moyens
# ---------------------------------------------------------------------------

def pret_a_partir(entree: Entree) -> bool:
    return entree.situation is not None and entree.situation.mobilite == "etranger"


def contraintes_de(entree: Entree) -> dict[str, str]:
    situation = entree.situation
    if situation is None:
        return {}
    return {c: getattr(situation, c) for c in CONTRAINTES if getattr(situation, c)}


def voie_possible(voie: Voie, contraintes: dict[str, str]) -> bool:
    if "diplome" in contraintes and ORDRE_DIPLOME.index(voie.niveau_requis) > ORDRE_DIPLOME.index(contraintes["diplome"]):
        return False
    if "budget" in contraintes and COUT_RANG[voie.cout] > BUDGET_RANG[contraintes["budget"]]:
        return False
    # En poste, on a changé de métier dès l'embauche : la durée de la formation ne retarde rien.
    delai_max = DELAI_MAX_MOIS.get(contraintes.get("delai", "plus_2_ans"))
    if delai_max is not None and voie.duree_mois > delai_max and voie.rythme != "en_poste":
        return False
    if "temps_hebdo" in contraintes and TEMPS_RANG[contraintes["temps_hebdo"]] < RYTHME_TEMPS_MIN[voie.rythme]:
        return False
    return True


# Quand on ignore le diplôme de l'utilisateur, chaque niveau exigé en plus compte autant
# que 2,4 ans d'études : on montre d'abord les voies ouvertes au plus grand nombre.
PENALITE_NIVEAU_INCONNU = 1.2


def facilite(voie: Voie, diplome_connu: bool = True) -> float:
    """Plus c'est petit, plus la voie est accessible : un rang de coût vaut deux ans d'études."""
    niveau = 0 if diplome_connu else PENALITE_NIVEAU_INCONNU * ORDRE_DIPLOME.index(voie.niveau_requis)
    return COUT_RANG[voie.cout] + voie.duree_mois / 24 + niveau


def ecart(voie: Voie, moyens: dict[str, str]) -> float:
    """De combien une voie dépasse les moyens de départ (0 si elle tient). Unités : un an de trop,
    un cran de temps disponible, de budget ou de diplôme en trop comptent chacun 1."""
    total = 0.0
    if "diplome" in moyens:
        total += max(0, ORDRE_DIPLOME.index(voie.niveau_requis) - ORDRE_DIPLOME.index(moyens["diplome"]))
    if "budget" in moyens:
        total += max(0, COUT_RANG[voie.cout] - BUDGET_RANG[moyens["budget"]])
    delai_max = DELAI_MAX_MOIS.get(moyens.get("delai", "plus_2_ans"))
    if delai_max is not None and voie.rythme != "en_poste":
        total += max(0, voie.duree_mois - delai_max) / 12
    if "temps_hebdo" in moyens:
        total += max(0, RYTHME_TEMPS_MIN[voie.rythme] - TEMPS_RANG[moyens["temps_hebdo"]])
    return total


def ecarts_lisibles(voie: Voie, moyens: dict[str, str]) -> list[str]:
    """Ce qui dépasse, en clair, pour l'afficher sous la voie d'accès."""
    phrases = []
    if "diplome" in moyens and ORDRE_DIPLOME.index(voie.niveau_requis) > ORDRE_DIPLOME.index(moyens["diplome"]):
        phrases.append(f"demande un niveau {LIBELLES_NIVEAU[voie.niveau_requis]}")
    if "budget" in moyens and COUT_RANG[voie.cout] > BUDGET_RANG[moyens["budget"]]:
        phrases.append(f"coûte {LIBELLES_COUT[voie.cout]}, plus que ton budget")
    delai_max = DELAI_MAX_MOIS.get(moyens.get("delai", "plus_2_ans"))
    if delai_max is not None and voie.rythme != "en_poste" and voie.duree_mois > delai_max:
        phrases.append(f"dure {libelle_duree(voie.duree_mois)}, plus que ton délai")
    if "temps_hebdo" in moyens and RYTHME_TEMPS_MIN[voie.rythme] > TEMPS_RANG[moyens["temps_hebdo"]]:
        phrases.append("demande plus de temps que tu n'en as" if voie.rythme == "temps_partiel"
                       else "demande d'être disponible à temps plein")
    return phrases


def meilleure_voie(metier: FicheMetier, contraintes: dict[str, str], moyens: dict[str, str] | None = None) -> Voie | None:
    """La plus accessible des voies compatibles. Avec un diplôme connu, les voies réservées à un
    niveau plus élevé sont déjà écartées : on prend alors la plus courte et la moins chère.
    moyens : les moyens de départ, quand certains ont été assouplis : on prend d'abord la voie
    qui les dépasse le moins (13 mois plutôt que 36 pour un délai de 12)."""
    possibles = [v for v in metier.voies if voie_possible(v, contraintes)]
    diplome_connu = "diplome" in (moyens or contraintes)
    return min(possibles, key=lambda v: (ecart(v, moyens or {}), facilite(v, diplome_connu))) if possibles else None


def libelle_duree(mois: int) -> str:
    if mois >= 24 and mois % 12 == 0:
        return f"environ {mois // 12} ans"
    if mois == 12:
        return "environ 1 an"
    return f"environ {mois} mois"


# ---------------------------------------------------------------------------
# Notes et choix
# ---------------------------------------------------------------------------

def _normaliser(texte: str) -> str:
    sans_accents = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", sans_accents.lower()).strip()


def est_le_poste_actuel(metier: FicheMetier, poste: str) -> bool:
    titre, poste = _normaliser(metier.titre), _normaliser(poste)
    return titre == poste or (len(poste) >= 6 and (poste in titre or titre in poste))


def affinite(metier: FicheMetier, scores: dict[str, float]) -> float:
    total = sum(metier.profils.values())
    return sum(w * scores[p] for p, w in metier.profils.items()) / total


def _z(similarites: np.ndarray) -> np.ndarray:
    ecart = similarites.std()
    if ecart < 1e-9:
        return np.zeros_like(similarites)
    return np.clip((similarites - similarites.mean()) / ecart, -Z_MAX, Z_MAX)


@dataclass
class Choix:
    metier: FicheMetier
    voie: Voie
    note: float
    ecarts: list[str] = field(default_factory=list)  # ce qui dépasse les moyens de départ, en clair


@dataclass
class ResultatOrientation:
    principal: Choix
    alternatifs: list[Choix]
    assouplissements: list[str] = field(default_factory=list)  # contraintes relâchées, dans l'ordre
    etranger: Choix | None = None  # piste à l'étranger, pour qui est prêt à partir

    @property
    def choix_affiches(self) -> list[Choix]:
        return [self.principal, *self.alternatifs, *([self.etranger] if self.etranger else [])]

    @property
    def libelles_assouplissements(self) -> list[str]:
        return [LIBELLES_CONTRAINTES[c] for c in self.assouplissements]


class Orientation:
    """Le tableau des métiers, prêt à l'emploi (vecteurs calculés une fois au démarrage)."""

    def __init__(self, metiers: list[FicheMetier] | None = None, encodeur=None):
        self.metiers = metiers if metiers is not None else charger_metiers()
        self.encodeur = encodeur
        self.vecteurs = None
        if encodeur is not None:
            textes = [f"passage: {m.titre}. {m.description}" for m in self.metiers]
            self.vecteurs = encodeur.encoder(textes)

    def bonus_texte(self, entree: Entree) -> np.ndarray:
        bonus = np.zeros(len(self.metiers))
        if self.vecteurs is None:
            return bonus
        textes, poids = [f"query: {entree.poste_actuel}"], [BONUS_POSTE]
        if entree.job_voulu:
            textes.append(f"query: {entree.job_voulu}")
            poids.append(BONUS_VOULU)
        for vecteur, p in zip(self.encodeur.encoder(textes), poids):
            bonus += p * _z(self.vecteurs @ vecteur)
        return bonus

    def orienter(self, analyse: AnalyseProfil, entree: Entree) -> ResultatOrientation:
        scores = {s.profil_id: s.score for s in analyse.scores}
        bonus = self.bonus_texte(entree)
        notes = {m.id: affinite(m, scores) + bonus[i] for i, m in enumerate(self.metiers)}
        partir = pret_a_partir(entree)
        candidats = [m for m in self.metiers if not est_le_poste_actuel(m, entree.poste_actuel)
                     and (partir or m.lieu == "france")]
        profils_cles = {analyse.dominant, analyse.secondaire}

        moyens = contraintes = contraintes_de(entree)
        assouplies: list[str] = []
        while True:
            possibles = [(m, v) for m in candidats if (v := meilleure_voie(m, contraintes, moyens))]
            assez = len(possibles) >= NB_MIN_POSSIBLES and any(m.profil_principal in profils_cles for m, _ in possibles)
            if assez or not contraintes:
                break
            a_relacher = next(c for c in CONTRAINTES if c in contraintes)
            contraintes = {c: v for c, v in contraintes.items() if c != a_relacher}
            assouplies.append(a_relacher)

        # Après un assouplissement, une voie qui dépasse peu les moyens passe devant une voie qui les
        # dépasse beaucoup : la note perd PENALITE_ECART par unité d'écart (0 si rien n'a été assoupli).
        def note(m, v):
            return round(notes[m.id] - PENALITE_ECART * ecart(v, moyens), 4)
        # Tri stable : à note égale, l'ordre du tableau décide (résultat reproductible).
        classes = sorted(possibles, key=lambda mv: -note(*mv))
        choix = [Choix(m, v, note(m, v), ecarts_lisibles(v, moyens)) for m, v in classes]

        principal, reste = choix[0], choix[1:]
        alternatifs: list[Choix] = []
        for profil in (analyse.dominant, analyse.secondaire):
            trouve = next((c for c in reste if c.metier.profil_principal == profil and c not in alternatifs), None)
            alternatifs.append(trouve or next(c for c in reste if c not in alternatifs))

        etranger = None
        if partir and all(c.metier.lieu == "france" for c in [principal, *alternatifs]):
            # D'abord les métiers accessibles avec les moyens retenus pour les autres, puis la meilleure note.
            ailleurs = [(m, meilleure_voie(m, contraintes, moyens)) for m in candidats if m.lieu == "etranger"]
            if ailleurs:
                m, voie = min(ailleurs, key=lambda mv: (mv[1] is None, -notes[mv[0].id]))
                voie = voie or meilleure_voie(m, {}, moyens)
                etranger = Choix(m, voie, round(notes[m.id], 4), ecarts_lisibles(voie, moyens))
        return ResultatOrientation(principal, alternatifs, assouplies, etranger)
