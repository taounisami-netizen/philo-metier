"""Situation de l'utilisateur : problématique et moyens."""

import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import generation
from app import main as api
from app.main import app, get_orientation, get_recherche
from app.orientation import Orientation
from app.schemas import Entree, OptionParcours, ReponseProblematique, Situation
from tests.test_api import FausseRecherche, _Bloc, _faux_client, _redaction_json, faux_redaction, message, reponses_toutes

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
    app.dependency_overrides[get_orientation] = lambda: Orientation(encodeur=None)
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
    msg = message(Entree(**ENTREE))
    assert "5 à 10 h par semaine" in msg and "Bac +3" in msg and "Dans ma région" in msg
    # Les textes libres sont encadrés comme des données
    assert "<texte_utilisateur>Je veux quitter l'hôpital" in msg
    assert "<texte_utilisateur>Deux enfants en bas âge</texte_utilisateur>" in msg


def test_sans_situation_le_message_le_dit():
    assert "Problématique et moyens : non précisés" in message(Entree(poste_actuel="Dev", statut="salarie"))


def test_la_recherche_de_passages_part_de_la_problematique():
    from app.scoring import calculer_profil, charger_grille
    from app.schemas import Reponse
    grille = charger_grille()
    analyse = calculer_profil(grille, [Reponse(**r) for r in reponses_toutes()])
    requete = generation.construire_requete(grille, analyse, [], Entree(**ENTREE))
    assert requete.startswith(SITUATION["problematique"])


# --- Résultat ----------------------------------------------------------------------------------

def test_les_metiers_respectent_les_moyens(client):
    from app.orientation import charger_metiers, voie_possible
    data = client.post("/api/resultat", json={"entree": ENTREE, "reponses": reponses_toutes()}).json()
    assert data["assouplissements"] == []
    fiches = {m.titre: m for m in charger_metiers()}
    contraintes = {c: SITUATION[c] for c in ("delai", "temps_hebdo", "budget", "diplome")}
    for metier in [data["sortie"]["metier_principal"], *data["sortie"]["metiers_alternatifs"]]:
        voie = next(v for v in fiches[metier["titre"]].voies if v.nom == metier["acces"]["voie"])
        assert voie_possible(voie, contraintes), metier["titre"]


def test_avec_claude_la_reponse_est_transmise(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fausse-cle")
    monkeypatch.setattr(api, "rediger", lambda *a: faux_redaction(job=False, problematique=reponse_problematique()))
    data = client.post("/api/redaction", json={"entree": ENTREE, "reponses": reponses_toutes()}).json()
    assert data["reponse_problematique"]["options"][0]["titre"] == "Infirmière en santé au travail"


def test_claude_doit_repondre_a_la_problematique(monkeypatch):
    import anthropic
    appels = []
    sans_reponse = _redaction_json(job=False)  # pas de reponse_problematique
    monkeypatch.setattr(anthropic, "Anthropic", _faux_client([_Bloc(type="tool_use", input=sans_reponse)], appels=appels))
    with pytest.raises(RuntimeError, match="reponse_problematique"):
        generation.rediger("contenu", Entree(**ENTREE))
    assert len(appels) == 2  # une seconde chance a été donnée


def test_reponse_ignoree_sans_problematique(monkeypatch):
    import anthropic
    avec_reponse = _redaction_json(job=False) | {"reponse_problematique": json.loads(reponse_problematique().model_dump_json())}
    monkeypatch.setattr(anthropic, "Anthropic", _faux_client([_Bloc(type="tool_use", input=avec_reponse)]))
    entree = Entree(poste_actuel="Dev", statut="salarie")
    assert generation.rediger("contenu", entree).reponse_problematique is None
