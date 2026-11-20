"""Situation de l'utilisateur : problématique et moyens."""

import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import generation
from app.main import app, get_recherche
from app.schemas import Entree, OptionParcours, ReponseProblematique, Situation
from tests.test_api import FausseRecherche, _Bloc, _contexte, _faux_client, _sortie_json, faux_llm, reponses_toutes

SITUATION = {
    "problematique": "Je veux quitter l'hôpital sans reprendre de longues études.",
    "temps_hebdo": "5_10h", "budget": "moins_1000", "delai": "6_12_mois",
    "diplome": "bac_3", "mobilite": "region", "contrainte": "Deux enfants en bas âge",
}
ENTREE = {"poste_actuel": "Infirmière", "statut": "salarie", "situation": SITUATION}


@pytest.fixture
def client(monkeypatch):
    for nom in ("ANTHROPIC_API_KEY", "CLE_INTERNE"):
        monkeypatch.delenv(nom, raising=False)
    app.dependency_overrides[get_recherche] = lambda: FausseRecherche()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def reponse_problematique():
    option = OptionParcours(titre="Infirmière en santé au travail", duree="6 à 12 mois", cout="0 à 1 000 €",
                            financements="CPF, financement employeur",
                            premieres_etapes=["Lister les offres de ta région", "Appeler un service de santé au travail"],
                            pourquoi_toi="Tu restes utile sans l'urgence permanente.")
    return ReponseProblematique(diagnostic="…", options=[option, option], recommandation="…", risques=["…"])


# --- Le site reçoit les choix possibles -------------------------------------------------

def test_le_questionnaire_envoie_les_champs_de_situation(client):
    champs = {c["nom"]: c for c in client.get("/api/questionnaire").json()["situation"]}
    assert set(champs) == {"temps_hebdo", "budget", "delai", "diplome", "mobilite"}
    assert {"valeur": "bac_3", "libelle": "Bac +3"} in champs["diplome"]["choix"]


# --- Validation ----------------------------------------------------------------------------

def test_situation_vide_ignoree():
    entree = Entree(poste_actuel="Dev", statut="salarie",
                    situation={"problematique": "  ", "budget": "", "contrainte": None})
    assert entree.situation is None and entree.problematique is None


def test_choix_inconnu_refuse(client):
    entree = ENTREE | {"situation": SITUATION | {"budget": "un-million"}}
    assert client.post("/api/resultat", json={"entree": entree, "reponses": reponses_toutes()}).status_code == 422


def test_problematique_trop_longue_refusee():
    with pytest.raises(ValidationError):
        Situation(problematique="x" * 301)


# --- Ce que Claude reçoit -----------------------------------------------------------------

def test_le_message_contient_les_moyens_en_clair():
    grille, _, analyse, reponses = _contexte()
    entree = Entree(**ENTREE)
    message = generation.message_utilisateur(grille, entree, analyse, reponses, [])
    assert "5 à 10 h par semaine" in message and "Bac +3" in message and "Dans ma région" in message
    # Les textes libres sont encadrés comme des données
    assert "<texte_utilisateur>Je veux quitter l'hôpital" in message
    assert "<texte_utilisateur>Deux enfants en bas âge</texte_utilisateur>" in message


def test_sans_situation_le_message_le_dit():
    grille, _, analyse, reponses = _contexte()
    entree = Entree(poste_actuel="Dev", statut="salarie")
    assert "Problématique et moyens : non précisés" in generation.message_utilisateur(grille, entree, analyse, reponses, [])


def test_la_recherche_de_passages_part_de_la_problematique():
    grille, _, analyse, reponses = _contexte()
    requete = generation.construire_requete(grille, analyse, [], Entree(**ENTREE))
    assert requete.startswith(SITUATION["problematique"])


# --- Résultat ----------------------------------------------------------------------------------

def test_mode_demo_sans_analyse_de_la_problematique(client):
    r = client.post("/api/resultat", json={"entree": ENTREE, "reponses": reponses_toutes()})
    assert r.status_code == 200
    data = r.json()
    assert data["mode"] == "demo" and data["sortie"]["reponse_problematique"] is None


def test_avec_claude_la_reponse_est_transmise(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fausse-cle")
    sortie = faux_llm("Rien.")
    sortie.ecart_job_voulu = None
    sortie.reponse_problematique = reponse_problematique()
    monkeypatch.setattr(generation, "sortie_llm", lambda *a: sortie)
    data = client.post("/api/resultat", json={"entree": ENTREE, "reponses": reponses_toutes()}).json()
    assert data["mode"] == "llm"
    assert data["sortie"]["reponse_problematique"]["options"][0]["titre"] == "Infirmière en santé au travail"


def test_claude_doit_repondre_a_la_problematique(monkeypatch):
    import anthropic
    sans_reponse = _sortie_json(job=False)  # pas de reponse_problematique
    appels = []
    monkeypatch.setattr(anthropic, "Anthropic", _faux_client([_Bloc(type="tool_use", input=sans_reponse)], appels=appels))
    grille, _, analyse, reponses = _contexte()
    with pytest.raises(RuntimeError, match="reponse_problematique"):
        generation.sortie_llm(grille, Entree(**ENTREE), analyse, reponses, [])
    assert len(appels) == 2  # une seconde chance a été donnée


def test_reponse_ignoree_sans_problematique(monkeypatch):
    import anthropic
    avec_reponse = _sortie_json(job=False) | {"reponse_problematique": json.loads(reponse_problematique().model_dump_json())}
    monkeypatch.setattr(anthropic, "Anthropic", _faux_client([_Bloc(type="tool_use", input=avec_reponse)]))
    grille, _, analyse, reponses = _contexte()
    entree = Entree(poste_actuel="Dev", statut="salarie")
    assert generation.sortie_llm(grille, entree, analyse, reponses, []).reponse_problematique is None
