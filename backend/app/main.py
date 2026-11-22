"""API du site philo-métier.

Lancement (depuis backend/, .venv activé) :
    uvicorn app.main:app --reload --port 8000
Documentation interactive : http://localhost:8000/docs

Routes :
    GET  /api/sante         état du serveur (corpus chargé ? LLM configuré ?)
    GET  /api/questionnaire questions (sans les points), statuts, nombre max de choix
    POST /api/resultat      réponses → profil, métiers, citation, livre : calculés, sans IA (immédiat)
    POST /api/redaction     mêmes données → explications rédigées par Claude (~30 s)
"""

import random

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from .generation import (echos_choisis, graine, journaliser_erreur, llm_disponible, message_utilisateur,
                         passages_pour, rediger, sortie_calculee)
from .orientation import Orientation
from .protection import Limiteur, cle_interne_valide, ip_du_client
from .rag import CorpusIntrouvable, Recherche
from .schemas import (
    CHOIX_SITUATION,
    ChampSituation,
    DemandeResultat,
    OptionPublique,
    QuestionPublique,
    Questionnaire,
    Redaction,
    Resultat,
    Statut,
    StatutPublic,
)
from .scoring import MAX_CHOIX, ReponsesInvalides, calculer_profil, charger_grille


def _charger_env() -> None:
    """Lit backend/.env (clé ANTHROPIC_API_KEY…) s'il existe, sans dépendance externe."""
    import os
    fichier = Path(__file__).parent.parent / ".env"
    if fichier.exists():
        for ligne in fichier.read_text("utf-8").splitlines():
            if "=" in ligne and not ligne.lstrip().startswith("#"):
                cle, valeur = ligne.split("=", 1)
                os.environ.setdefault(cle.strip(), valeur.strip().strip('"'))


_charger_env()
etat: dict = {}


@asynccontextmanager
async def demarrage(app: FastAPI):
    etat["grille"] = charger_grille()
    etat["limiteur"] = Limiteur()            # résultats calculés
    etat["limiteur_redaction"] = Limiteur()  # rédactions par Claude (et budget Claude du jour)
    try:
        etat["recherche"] = Recherche()
        print(f"[api] corpus chargé : {len(etat['recherche'].passages)} passages")
    except CorpusIntrouvable as e:
        etat["recherche"] = None
        print(f"[api] ATTENTION : {e}")
    encodeur = etat["recherche"].modele if etat["recherche"] else None
    etat["orientation"] = Orientation(encodeur=encodeur)
    print(f"[api] orientation : {len(etat['orientation'].metiers)} métiers")
    print(f"[api] LLM : {'Claude configuré' if llm_disponible() else 'pas de clé → mode démo'}")
    yield


# En ligne (PRODUCTION=1) : pas de documentation publique de l'API, et /api/sante en dit le moins possible.
PRODUCTION = os.environ.get("PRODUCTION") == "1"
app = FastAPI(
    title="Philo-métier", lifespan=demarrage,
    docs_url=None if PRODUCTION else "/docs",
    redoc_url=None if PRODUCTION else "/redoc",
    openapi_url=None if PRODUCTION else "/openapi.json",
)
# Le navigateur parle au site Next.js, qui relaie vers l'API côté serveur : l'API n'a besoin
# d'accepter que l'adresse du site. CORS_ORIGINS = liste séparée par des virgules.
ORIGINES = [o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000,http://localhost:3001").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware, allow_origins=ORIGINES, allow_methods=["GET", "POST"], allow_headers=["Content-Type"],
)


@app.middleware("http")
async def seulement_depuis_le_site(request: Request, appel_suivant):
    """En ligne, refuse toute requête /api qui ne vient pas du site (voir protection.py)."""
    if request.url.path.startswith("/api") and not cle_interne_valide(request):
        return JSONResponse({"detail": "Accès refusé."}, status_code=403)
    return await appel_suivant(request)


def get_grille():
    return etat["grille"]


def get_orientation():
    return etat["orientation"]


def get_recherche():
    if etat.get("recherche") is None:
        raise HTTPException(503, "Corpus non chargé : lance le pipeline d'ingestion (README, étape 2).")
    return etat["recherche"]


@app.get("/")
def accueil():
    """Page d'accueil minimale : Render l'appelle pour vérifier que l'API est en vie."""
    return {"service": "philo-metier", "ok": True}


@app.get("/api/sante")
def sante():
    if PRODUCTION:
        return {"ok": True}
    recherche = etat.get("recherche")
    return {
        "ok": True,
        "passages": len(recherche.passages) if recherche else 0,
        "llm": llm_disponible(),
    }


@app.get("/api/questionnaire", response_model=Questionnaire)
def questionnaire(grille=Depends(get_grille)):
    return Questionnaire(
        questions=[
            QuestionPublique(id=q.id, theme=q.theme, texte=q.texte, relance=q.relance, illustration=q.illustration,
                             options=[OptionPublique(id=o.id, texte=o.texte) for o in q.options])
            for q in grille.questions
        ],
        statuts=[StatutPublic(valeur=s.value, libelle=s.libelle) for s in Statut],
        max_choix=MAX_CHOIX,
        situation=[
            ChampSituation(nom=nom, libelle=libelle,
                           choix=[StatutPublic(valeur=v, libelle=l) for v, l in choix.items()])
            for nom, (libelle, choix) in CHOIX_SITUATION.items()
        ],
    )


def _calculer(demande: DemandeResultat, grille, recherche, orientation):
    """Tout le résultat sans IA. Déterministe : /api/redaction recalcule exactement la même chose."""
    try:
        analyse = calculer_profil(grille, demande.reponses)
    except ReponsesInvalides as e:
        raise HTTPException(422, str(e))
    alea = random.Random(graine(demande))
    passages = passages_pour(recherche, grille, analyse, demande.reponses, alea=alea, entree=demande.entree)
    if not passages:
        raise HTTPException(503, "Aucun passage trouvé pour ce profil dans le corpus.")
    choix = orientation.orienter(analyse, demande.entree)
    sortie = sortie_calculee(grille, demande.entree, analyse, passages, choix, alea)
    return analyse, passages, choix, sortie


@app.post("/api/resultat", response_model=Resultat)
def resultat(demande: DemandeResultat, request: Request, grille=Depends(get_grille),
             recherche=Depends(get_recherche), orientation=Depends(get_orientation)):
    if not etat["limiteur"].autoriser(ip_du_client(request)):
        raise HTTPException(429, "Trop de demandes depuis ton adresse. Réessaie dans une minute.")
    analyse, _, choix, sortie = _calculer(demande, grille, recherche, orientation)
    dominant = grille.profil(analyse.dominant)
    return Resultat(
        entree=demande.entree,
        profil=analyse,
        nom_profil=dominant.nom,
        trait_dominant=dominant.trait_dominant,
        description_profil=dominant.description,
        philosophes=dominant.philosophes,
        echos=echos_choisis(grille, demande.reponses, analyse.dominant)[:4],
        sortie=sortie,
        assouplissements=choix.libelles_assouplissements,
        redaction_possible=llm_disponible(),
    )


@app.post("/api/redaction", response_model=Redaction)
def redaction(demande: DemandeResultat, request: Request, grille=Depends(get_grille),
              recherche=Depends(get_recherche), orientation=Depends(get_orientation)):
    limiteur = etat["limiteur_redaction"]
    if not limiteur.autoriser(ip_du_client(request)):
        raise HTTPException(429, "Trop de demandes depuis ton adresse. Réessaie dans une minute.")
    # Budget Claude du jour : au-delà, le site garde le résultat calculé (gratuit).
    if not llm_disponible() or not limiteur.reserver_appel_llm():
        raise HTTPException(503, "La rédaction par l'IA n'est pas disponible pour le moment.")
    analyse, passages, choix, sortie = _calculer(demande, grille, recherche, orientation)
    contenu = message_utilisateur(grille, demande.entree, analyse, demande.reponses, sortie, choix, passages[0])
    try:
        return rediger(contenu, demande.entree)
    except Exception as e:  # réseau, quota, réponse invalide… : le résultat calculé reste affiché
        journaliser_erreur(e)
        raise HTTPException(503, "La rédaction par l'IA n'est pas disponible pour le moment.")
