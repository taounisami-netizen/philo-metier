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


class Entree(BaseModel):
    poste_actuel: str = Field(min_length=2, max_length=120)
    statut: Statut
    job_voulu: str | None = Field(default=None, max_length=120)

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

    question_id: str
    option_ids: list[str] = Field(min_length=1)
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


class Metier(BaseModel):
    titre: str
    pourquoi: str


class Citation(BaseModel):
    texte: str
    auteur: str
    livre: str
    # Identifiant du morceau de livre renvoyé par le RAG : permet de vérifier
    # que la citation existe vraiment dans le corpus (anti-hallucination).
    passage_id: str
    url: str | None = None


class LivreConseille(BaseModel):
    titre: str
    auteur: str
    pourquoi: str


class SortieLLM(BaseModel):
    """Ce que le LLM devra renvoyer, en JSON, à l'étape 4."""

    metier_principal: Metier
    metiers_alternatifs: list[Metier] = Field(min_length=2, max_length=2)
    citation: Citation
    livre_a_lire: LivreConseille
    ecart_job_voulu: str | None = None


class Resultat(BaseModel):
    """Résultat final affiché à l'utilisateur."""

    entree: Entree
    profil: AnalyseProfil
    nom_profil: str
    trait_dominant: str
    sortie: SortieLLM
    description_profil: str = ""
    philosophes: list[str] = []
    echos: list[Echo] = []  # idées des philosophes derrière les réponses choisies
    mode: Literal["llm", "demo"] = "demo"  # "demo" : texte généré sans LLM (pas de clé d'API)

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


class Questionnaire(BaseModel):
    questions: list[QuestionPublique]
    statuts: list[StatutPublic]
    max_choix: int


class DemandeResultat(BaseModel):
    entree: Entree
    reponses: list[Reponse]
