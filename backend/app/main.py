"""API du site philo-métier.

Lancement (depuis backend/, .venv activé) :
    uvicorn app.main:app --reload --port 8000
Documentation interactive : http://localhost:8000/docs

Routes :
    GET  /api/sante         état du serveur (corpus chargé ? LLM configuré ?)
    GET  /api/questionnaire questions (sans les points), statuts, nombre max de choix
    POST /api/resultat      réponses → profil + passages + résultat rédigé
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from .generation import echos_choisis, generer, llm_disponible, passages_pour
from .protection import Limiteur, cle_interne_valide, ip_du_client
from .rag import CorpusIntrouvable, Recherche
from .schemas import (
    DemandeResultat,
    OptionPublique,
    QuestionPublique,
    Questionnaire,
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
    etat["limiteur"] = Limiteur()
    try:
        etat["recherche"] = Recherche()
        print(f"[api] corpus chargé : {len(etat['recherche'].passages)} passages")
    except CorpusIntrouvable as e:
        etat["recherche"] = None
        print(f"[api] ATTENTION : {e}")
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


def get_recherche():
    if etat.get("recherche") is None:
        raise HTTPException(503, "Corpus non chargé : lance le pipeline d'ingestion (README, étape 2).")
    return etat["recherche"]


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
    )


@app.post("/api/resultat", response_model=Resultat)
def resultat(demande: DemandeResultat, request: Request,
             grille=Depends(get_grille), recherche=Depends(get_recherche)):
    if not etat["limiteur"].autoriser(ip_du_client(request)):
        raise HTTPException(429, "Trop de demandes depuis ton adresse. Réessaie dans une minute.")
    try:
        analyse = calculer_profil(grille, demande.reponses)
    except ReponsesInvalides as e:
        raise HTTPException(422, str(e))
    passages = passages_pour(recherche, grille, analyse, demande.reponses)
    if not passages:
        raise HTTPException(503, "Aucun passage trouvé pour ce profil dans le corpus.")
    # Budget Claude du jour : au-delà, le résultat est construit en mode démo (gratuit).
    llm_autorise = llm_disponible() and etat["limiteur"].reserver_appel_llm()
    sortie, mode = generer(grille, demande.entree, analyse, demande.reponses, passages, llm_autorise)
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
        mode=mode,
    )
