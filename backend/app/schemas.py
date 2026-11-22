"""Schémas de données du projet (Pydantic v2).

Trois familles de modèles :
1. La grille (profils + questions), chargée depuis les fichiers JSON de app/grille/.
2. Ce que l'utilisateur envoie (Entree, Reponse).
3. Ce que le site renvoie (AnalyseProfil, calculée en Python, puis Resultat,
   qui ajoute la partie rédigée par le LLM à partir des passages du RAG).
"""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# Les 7 profils de la grille. Les ids doivent correspondre à app/grille/profils.json
# (c'est vérifié au chargement par scoring.verifier_grille).
ProfilId = Literal[
    "stoique",
    "epicurien",
    "sceptique",
    "batisseur",
    "createur",
    "moraliste",
    "contemplatif",
]


# ---------------------------------------------------------------------------
# 1. La grille
# ---------------------------------------------------------------------------

class Livre(BaseModel):
    titre: str
    auteur: str
    # Nom du traducteur à vérifier à l'étape 2 (corpus) :
    # "original en français" = pas de traduction ; None = traduction libre de droits à trouver.
    traduction_suggeree: str | None = None


class Profil(BaseModel):
    id: ProfilId
    nom: str
    trait_dominant: str
    description: str
    philosophes: list[str] = Field(min_length=1)
    livres: list[Livre] = Field(min_length=1)
    metiers: list[str] = Field(min_length=3)
    mots_cles_rag: list[str] = Field(min_length=2)


class Echo(BaseModel):
    """L'idée philosophique derrière une option (affichable dans le résultat).
    Paraphrase : sera remplacée par un vrai passage du corpus à l'étape 3."""

    philosophe: str
    idee: str


class Option(BaseModel):
    id: str
    texte: str
    # Points donnés à chaque profil si l'utilisateur choisit cette option (1 ou 2).
    poids: dict[ProfilId, int] = Field(min_length=1, max_length=2)
    echo: Echo

    @field_validator("poids")
    @classmethod
    def poids_entre_1_et_2(cls, poids: dict[str, int]) -> dict[str, int]:
        for profil, valeur in poids.items():
            if valeur not in (1, 2):
                raise ValueError(f"poids de {profil} = {valeur}, attendu 1 ou 2")
        return poids


class Question(BaseModel):
    id: str
    theme: str
    texte: str
    # Question ouverte facultative posée après le choix. La réponse est conservée
    # pour le LLM (étape 4) mais n'entre pas dans le calcul du score.
    relance: str | None = None
    # Nom d'une illustration affichée par le site au-dessus de la question (ex. "tramway").
    illustration: str | None = None
    options: list[Option] = Field(min_length=2)


class FichierProfils(BaseModel):
    version: int
    profils: list[Profil]


class FichierQuestions(BaseModel):
    version: int
    regles: str
    questions: list[Question]


# ---------------------------------------------------------------------------
# 2. Ce que l'utilisateur envoie
# ---------------------------------------------------------------------------

class Statut(str, Enum):
    """Les valeurs (sans accent) servent dans l'API et la base de données ;
    `libelle` est le texte affiché à l'utilisateur."""

    ETUDIANT = "etudiant"
    ALTERNANT = "alternant"
    SALARIE = "salarie"
    INDEPENDANT = "independant"
    EN_RECHERCHE = "en_recherche"
    RECONVERSION = "reconversion"

    @property
    def libelle(self) -> str:
        return LIBELLES_STATUT[self]


LIBELLES_STATUT: dict[Statut, str] = {
    Statut.ETUDIANT: "Étudiant",
    Statut.ALTERNANT: "Alternant",
    Statut.SALARIE: "Salarié",
    Statut.INDEPENDANT: "Indépendant",
    Statut.EN_RECHERCHE: "En recherche d'emploi",
    Statut.RECONVERSION: "En reconversion",
}


# Les moyens de l'utilisateur : des choix fermés (valeur technique -> texte affiché).
# Le site construit ses listes à partir de ce dictionnaire, envoyé par GET /api/questionnaire.
CHOIX_SITUATION: dict[str, tuple[str, dict[str, str]]] = {
    "temps_hebdo": ("Temps disponible", {
        "moins_5h": "Moins de 5 h par semaine", "5_10h": "5 à 10 h par semaine",
        "10_20h": "10 à 20 h par semaine", "temps_plein": "À temps plein",
    }),
    "budget": ("Budget pour une formation", {
        "aucun": "Aucun (formation financée ou gratuite)", "moins_1000": "Moins de 1 000 €",
        "1000_5000": "1 000 à 5 000 €", "plus_5000": "Plus de 5 000 €",
    }),
    "delai": ("Délai pour changer", {
        "moins_6_mois": "Moins de 6 mois", "6_12_mois": "6 à 12 mois",
        "1_2_ans": "1 à 2 ans", "plus_2_ans": "Plus de 2 ans",
    }),
    "diplome": ("Niveau de diplôme", {
        "sans": "Sans diplôme", "cap_bep": "CAP / BEP", "bac": "Bac",
        "bac_2": "Bac +2", "bac_3": "Bac +3", "bac_5": "Bac +5 ou plus",
    }),
    "mobilite": ("Mobilité", {
        "ville": "Rester dans ma ville", "region": "Dans ma région",
        "france": "Partout en France", "etranger": "Prêt à partir à l'étranger",
    }),
}


class Situation(BaseModel):
    """La problématique de l'utilisateur et ses moyens. Tout est facultatif."""

    problematique: str | None = Field(default=None, max_length=300)
    temps_hebdo: str | None = None
    budget: str | None = None
    delai: str | None = None
    diplome: str | None = None
    mobilite: str | None = None
    contrainte: str | None = Field(default=None, max_length=200)

    @field_validator("problematique", "contrainte", "temps_hebdo", "budget", "delai", "diplome", "mobilite")
    @classmethod
    def vide_devient_none(cls, valeur: str | None) -> str | None:
        if valeur is None or not valeur.strip():
            return None
        return valeur.strip()

    @model_validator(mode="after")
    def choix_connus(self) -> "Situation":
        for champ, (_, choix) in CHOIX_SITUATION.items():
            valeur = getattr(self, champ)
            if valeur is not None and valeur not in choix:
                raise ValueError(f"{champ} : valeur inconnue « {valeur} »")
        return self

    def libelle(self, champ: str) -> str | None:
        valeur = getattr(self, champ)
        return CHOIX_SITUATION[champ][1][valeur] if valeur else None

    def est_vide(self) -> bool:
        return all(getattr(self, champ) is None for champ in type(self).model_fields)


class Entree(BaseModel):
    poste_actuel: str = Field(min_length=2, max_length=120)
    statut: Statut
    job_voulu: str | None = Field(default=None, max_length=120)
    situation: Situation | None = None

    @field_validator("situation")
    @classmethod
    def situation_vide_devient_none(cls, valeur: Situation | None) -> Situation | None:
        return None if valeur is None or valeur.est_vide() else valeur

    @property
    def problematique(self) -> str | None:
        return self.situation.problematique if self.situation else None

    @field_validator("poste_actuel")
    @classmethod
    def nettoyer_poste(cls, valeur: str) -> str:
        return valeur.strip()

    @field_validator("job_voulu")
    @classmethod
    def vide_devient_none(cls, valeur: str | None) -> str | None:
        if valeur is None or not valeur.strip():
            return None
        return valeur.strip()


class Reponse(BaseModel):
    """Une réponse peut contenir 1 ou plusieurs options (max : scoring.MAX_CHOIX)."""

    question_id: str = Field(max_length=10)
    # Bornes larges mais finies : un visiteur ne peut pas envoyer 100 000 options
    # (le scoring vérifie ensuite la vraie limite, MAX_CHOIX).
    option_ids: list[str] = Field(min_length=1, max_length=5)
    # Réponse libre à la relance (facultative, non comptée dans le score).
    texte_libre: str | None = Field(default=None, max_length=500)

    @field_validator("texte_libre")
    @classmethod
    def texte_vide_devient_none(cls, valeur: str | None) -> str | None:
        if valeur is None or not valeur.strip():
            return None
        return valeur.strip()


# ---------------------------------------------------------------------------
# 3. Ce que le site renvoie
# ---------------------------------------------------------------------------

class ScoreProfil(BaseModel):
    profil_id: ProfilId
    points: float = Field(ge=0)  # peut être fractionnaire (points partagés entre plusieurs choix)
    points_max: int = Field(gt=0)
    score: float = Field(ge=0, le=1)  # points / points_max


class AnalyseProfil(BaseModel):
    """Calculée en Python, sans LLM : mêmes réponses => même profil."""

    scores: list[ScoreProfil]  # triés du plus haut au plus bas
    dominant: ProfilId
    secondaire: ProfilId
    ecart: float = Field(ge=0, le=1)  # score(dominant) - score(secondaire)
    mixte: bool  # True si l'écart est trop faible pour trancher


class AccesMetier(BaseModel):
    """La voie d'accès la plus réaliste avec les moyens de l'utilisateur (orientation.py)."""

    voie: str    # ex. « Titre professionnel de technicien qualité pour adultes »
    duree: str   # ex. « environ 9 mois »
    cout: str    # ex. « gratuit pour toi (financé) »


# Les liens « s'informer » ne peuvent pointer que vers ces sites officiels.
SITES_LIENS = ("https://www.onisep.fr/", "https://mon-vie-via.businessfrance.fr/",
               "https://www.france-volontaires.org/", "https://www.diplomatie.gouv.fr/", "https://www.cned.fr/",
               "https://bpifrance-creation.fr/")


class Lien(BaseModel):
    titre: str
    url: str

    @field_validator("url")
    @classmethod
    def site_connu(cls, url: str) -> str:
        if not url.startswith(SITES_LIENS):
            raise ValueError(f"lien vers un site non prévu : {url}")
        return url


class Metier(BaseModel):
    titre: str
    pourquoi: str
    acces: AccesMetier | None = None
    liens: list[Lien] = []


SOURCES_AUTORISEES = ("https://fr.wikisource.org/", "https://www.gutenberg.org/")


class Citation(BaseModel):
    texte: str
    auteur: str
    livre: str
    # Identifiant du morceau de livre renvoyé par le RAG : permet de vérifier
    # que la citation existe vraiment dans le corpus (anti-hallucination).
    passage_id: str
    url: str | None = None

    @field_validator("url")
    @classmethod
    def seulement_nos_sources(cls, valeur: str | None) -> str | None:
        """Le lien « lire le passage » ne peut pointer que vers nos sources (pas de javascript:…)."""
        if valeur and not valeur.startswith(SOURCES_AUTORISEES):
            return None
        return valeur


class LivreConseille(BaseModel):
    titre: str
    auteur: str
    pourquoi: str


class OptionParcours(BaseModel):
    """Une piste réaliste pour répondre à la problématique, compte tenu des moyens."""

    titre: str          # ex. « Devenir développeur web en reconversion courte »
    duree: str          # fourchette, ex. « 6 à 9 mois »
    cout: str           # fourchette ou « financé », ex. « 0 € avec le CPF »
    financements: str   # dispositifs possibles, ex. « CPF, Projet de transition professionnelle »
    premieres_etapes: list[str] = Field(min_length=2, max_length=4)
    pourquoi_toi: str   # le lien avec le profil philosophique


class ReponseProblematique(BaseModel):
    diagnostic: str                                              # la problématique reformulée, et ce qui la bloque
    options: list[OptionParcours] = Field(min_length=2, max_length=3)
    recommandation: str                                          # LA piste conseillée, et pourquoi
    risques: list[str] = Field(min_length=1, max_length=4)


class Sortie(BaseModel):
    """Le résultat calculé (orientation.py + RAG) : métiers, citation, livre.
    Les « pourquoi » sont d'abord des phrases types, puis remplacés par ceux de Claude (Redaction)."""

    metier_principal: Metier
    metiers_alternatifs: list[Metier] = Field(min_length=2, max_length=2)
    citation: Citation
    livre_a_lire: LivreConseille
    ecart_job_voulu: str | None = None
    metier_etranger: Metier | None = None  # seulement pour qui est prêt à partir (question Mobilité)


class Redaction(BaseModel):
    """Ce que Claude rédige, en JSON, à partir des choix DÉJÀ faits par le calcul.
    Il ne choisit rien : il explique, et répond à la problématique s'il y en a une."""

    pourquoi_metier_principal: str
    pourquoi_metiers_alternatifs: list[str] = Field(min_length=2, max_length=2)
    pourquoi_livre: str
    ecart_job_voulu: str | None = None
    reponse_problematique: ReponseProblematique | None = None


class Resultat(BaseModel):
    """Résultat final affiché à l'utilisateur."""

    entree: Entree
    profil: AnalyseProfil
    nom_profil: str
    trait_dominant: str
    sortie: Sortie
    description_profil: str = ""
    philosophes: list[str] = []
    echos: list[Echo] = []  # idées des philosophes derrière les réponses choisies
    # Moyens qu'il a fallu relâcher pour trouver des métiers (ex. « le délai »), dans l'ordre.
    assouplissements: list[str] = []
    # True si le site peut demander à Claude de rédiger les explications (POST /api/redaction).
    redaction_possible: bool = False

    @model_validator(mode="after")
    def ecart_seulement_si_job_voulu(self) -> "Resultat":
        a_un_job_voulu = self.entree.job_voulu is not None
        a_un_ecart = self.sortie.ecart_job_voulu is not None
        if a_un_job_voulu and not a_un_ecart:
            raise ValueError("job_voulu renseigné : ecart_job_voulu est obligatoire")
        if a_un_ecart and not a_un_job_voulu:
            raise ValueError("ecart_job_voulu fourni alors qu'aucun job_voulu n'est renseigné")
        return self


# ---------------------------------------------------------------------------
# 4. API
# ---------------------------------------------------------------------------

class OptionPublique(BaseModel):
    """Une option telle qu'envoyée au site : sans les points ni le profil (sinon on
    pourrait deviner quel profil chaque réponse fait monter)."""

    id: str
    texte: str


class QuestionPublique(BaseModel):
    id: str
    theme: str
    texte: str
    relance: str | None = None
    # Nom d'une illustration affichée par le site au-dessus de la question (ex. "tramway").
    illustration: str | None = None
    options: list[OptionPublique]


class StatutPublic(BaseModel):
    valeur: str
    libelle: str


class ChampSituation(BaseModel):
    nom: str
    libelle: str
    choix: list[StatutPublic]  # même forme : valeur + libellé


class Questionnaire(BaseModel):
    questions: list[QuestionPublique]
    statuts: list[StatutPublic]
    max_choix: int
    situation: list[ChampSituation] = []


class DemandeResultat(BaseModel):
    entree: Entree
    reponses: list[Reponse] = Field(max_length=30)
