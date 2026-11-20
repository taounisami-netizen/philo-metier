"""Tests de l'API et de la génération (sans modèle d'embeddings ni appel à Claude)."""

import json

import pytest
from fastapi.testclient import TestClient

from app import generation
from app.main import app, get_recherche
from app.schemas import Citation, Metier, SortieLLM, LivreConseille

PASSAGE_EPICTETE = (
    "Parmi les choses, les unes dépendent de nous, les autres n'en dépendent pas. "
    "Celles qui dépendent de nous, c'est l'opinion, le vouloir, le désir, l'aversion : "
    "en un mot tout ce qui est notre œuvre."
)


class FausseRecherche:
    passages = [{"id": "x"}]

    def chercher(self, question, profils, k=4):
        return [{
            "id": f"{profils[0]}-000-000", "auteur": "Épictète", "livre": "Manuel",
            "texte": PASSAGE_EPICTETE, "url": "https://fr.wikisource.org/wiki/Manuel", "profils": profils,
        }]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    app.dependency_overrides[get_recherche] = lambda: FausseRecherche()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def reponses_toutes(option="a", n=13):
    return [{"question_id": f"q{i:02d}", "option_ids": [option]} for i in range(1, n + 1)]


def test_questionnaire_ne_revele_pas_les_points(client):
    data = client.get("/api/questionnaire").json()
    assert len(data["questions"]) == 13 and data["max_choix"] == 2
    option = data["questions"][0]["options"][0]
    assert set(option) == {"id", "texte"}  # ni poids, ni echo
    assert {"valeur": "etudiant", "libelle": "Étudiant"} in data["statuts"]


def test_resultat_en_mode_demo(client):
    demande = {
        "entree": {"poste_actuel": "Développeur web", "statut": "alternant", "job_voulu": "Chef de projet"},
        "reponses": reponses_toutes(),
    }
    r = client.post("/api/resultat", json=demande)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["mode"] == "demo"
    assert data["sortie"]["citation"]["texte"] in PASSAGE_EPICTETE  # extrait réel
    assert data["sortie"]["ecart_job_voulu"]                        # job voulu → écart rempli
    assert len(data["sortie"]["metiers_alternatifs"]) == 2


def test_reponses_incompletes_refusees(client):
    demande = {"entree": {"poste_actuel": "Étudiant", "statut": "etudiant"}, "reponses": reponses_toutes(n=5)}
    r = client.post("/api/resultat", json=demande)
    assert r.status_code == 422 and "sans réponse" in r.text


# --- Garde-fou sur les citations ---------------------------------------------

def test_citation_exacte_acceptee_malgre_guillemets_et_espaces():
    assert generation.citation_est_dans_le_passage(
        "les unes dépendent de nous,   les autres n’en dépendent pas", PASSAGE_EPICTETE)


def test_citation_inventee_refusee():
    assert not generation.citation_est_dans_le_passage(
        "Le sage ne craint rien car tout dépend de lui.", PASSAGE_EPICTETE)


def faux_llm(texte_citation, passage_id="stoique-000-000"):
    return SortieLLM(
        metier_principal=Metier(titre="Contrôleur aérien", pourquoi="…"),
        metiers_alternatifs=[Metier(titre="A", pourquoi="…"), Metier(titre="B", pourquoi="…")],
        citation=Citation(texte=texte_citation, auteur="Épictète", livre="Manuel", passage_id=passage_id),
        livre_a_lire=LivreConseille(titre="Manuel", auteur="Épictète", pourquoi="…"),
        ecart_job_voulu="…",
    )


def test_citation_inventee_par_le_llm_remplacee_par_un_extrait_reel(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(generation, "sortie_llm", lambda *a: faux_llm("Une phrase qu'Épictète n'a jamais écrite."))
    demande = {"entree": {"poste_actuel": "Infirmier", "statut": "salarie", "job_voulu": "Médecin"},
               "reponses": reponses_toutes()}
    data = client.post("/api/resultat", json=demande).json()
    assert data["mode"] == "llm"
    assert data["sortie"]["metier_principal"]["titre"] == "Contrôleur aérien"
    assert data["sortie"]["citation"]["texte"] != "Une phrase qu'Épictète n'a jamais écrite."
    assert data["sortie"]["citation"]["texte"] in PASSAGE_EPICTETE


def test_erreur_du_llm_retombe_sur_le_mode_demo(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

    def panne(*a):
        raise RuntimeError("quota dépassé")

    monkeypatch.setattr(generation, "sortie_llm", panne)
    demande = {"entree": {"poste_actuel": "Infirmier", "statut": "salarie"}, "reponses": reponses_toutes()}
    r = client.post("/api/resultat", json=demande)
    assert r.status_code == 200 and r.json()["mode"] == "demo"


def test_json_du_llm_entoure_de_texte():
    assert generation._extraire_json('Voici :\n```json\n{"a": 1}\n```') == {"a": 1}


def test_message_pour_le_llm_contient_l_essentiel():
    from app.schemas import Entree, Reponse
    from app.scoring import calculer_profil, charger_grille
    grille = charger_grille()
    reponses = [Reponse(question_id=f"q{i:02d}", option_ids=["a"], texte_libre="Je dirais la vérité." if i == 4 else None)
                for i in range(1, 14)]
    analyse = calculer_profil(grille, reponses)
    entree = Entree(poste_actuel="Développeur", statut="alternant", job_voulu=None)
    msg = generation.message_utilisateur(grille, entree, analyse, reponses, FausseRecherche().chercher("", ["stoique"]))
    assert "Développeur" in msg and "Alternant" in msg and "[stoique-000-000]" in msg
    assert "Je dirais la vérité." in msg


# --- Variété des passages -------------------------------------------------------

def _candidats(n, livres=("A",)):
    return [{"id": f"p{i}", "livre": livres[i % len(livres)]} for i in range(n)]


def test_tirage_varie_les_passages_entre_deux_personnes():
    import random
    from app.generation import tirer_passages
    candidats = _candidats(16)
    tirages = {tuple(p["id"] for p in tirer_passages(candidats, 4, random.Random(graine))) for graine in range(30)}
    assert len(tirages) > 10  # pas toujours les mêmes passages


def test_tirage_favorise_les_plus_proches():
    import random
    from collections import Counter
    from app.generation import tirer_passages
    candidats = _candidats(16)
    compte = Counter(p["id"] for g in range(500) for p in tirer_passages(candidats, 1, random.Random(g)))
    assert compte["p0"] > compte["p15"] * 5


def test_tirage_varie_les_livres():
    import random
    from app.generation import tirer_passages
    candidats = _candidats(16, livres=("A", "A", "A", "A", "B", "C"))
    for g in range(50):
        choisis = tirer_passages(candidats, 4, random.Random(g))
        assert sum(p["livre"] == "A" for p in choisis) <= 2
        assert len({p["id"] for p in choisis}) == 4


# --- Appel à Claude en « outil » (JSON garanti) --------------------------------------

class _Bloc:
    def __init__(self, **champs):
        self.__dict__.update(champs)


def _faux_client(blocs, stop_reason="tool_use", appels=None):
    class Messages:
        def create(self, **kwargs):
            if appels is not None:
                appels.append(kwargs)
            return _Bloc(content=blocs, stop_reason=stop_reason)

    class Client:
        messages = Messages()

    return lambda *a, **k: Client()


def _sortie_json(job=True):
    return {
        "metier_principal": {"titre": "Psychologue", "pourquoi": "Tu cherches le sens."},
        "metiers_alternatifs": [{"titre": "Écrivain", "pourquoi": "…"}, {"titre": "Chercheur", "pourquoi": "…"}],
        "citation": {"texte": "Ce qui dépend de nous", "auteur": "Épictète", "livre": "Manuel",
                     "passage_id": "stoique-000-000"},
        "livre_a_lire": {"titre": "Manuel", "auteur": "Épictète", "pourquoi": "…"},
        "ecart_job_voulu": "Proche par l'écoute." if job else None,
    }


def _contexte():
    from app.scoring import calculer_profil, charger_grille
    from app.schemas import Entree, Reponse
    grille = charger_grille()
    reponses = [Reponse(**r) for r in reponses_toutes()]
    entree = Entree(poste_actuel="Dev", statut="alternant", job_voulu="Médecin")
    return grille, entree, calculer_profil(grille, reponses), reponses


def test_claude_repond_par_l_outil(monkeypatch):
    import anthropic
    appels = []
    monkeypatch.setattr(anthropic, "Anthropic", _faux_client([_Bloc(type="tool_use", input=_sortie_json())], appels=appels))
    grille, entree, analyse, reponses = _contexte()
    sortie = generation.sortie_llm(grille, entree, analyse, reponses, [{"id": "x", "auteur": "a", "livre": "l", "texte": "t"}])
    assert sortie.metier_principal.titre == "Psychologue"
    assert appels[0]["tools"][0]["name"] == "rediger_resultat"
    assert "$ref" not in json.dumps(appels[0]["tools"][0]["input_schema"])


def test_citation_avec_retour_a_la_ligne_dans_du_texte_brut():
    texte = '{"a": "ligne 1\nligne 2 avec des « guillemets »"}'
    assert generation._extraire_json(texte)["a"].startswith("ligne 1")


def test_reponse_coupee_signalee(monkeypatch):
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", _faux_client([_Bloc(type="text", text='{"metier')], stop_reason="max_tokens"))
    grille, entree, analyse, reponses = _contexte()
    with pytest.raises(RuntimeError, match="max_tokens"):
        generation.sortie_llm(grille, entree, analyse, reponses, [{"id": "x", "auteur": "a", "livre": "l", "texte": "t"}])


def test_reponse_en_texte_acceptee_si_le_modele_n_utilise_pas_l_outil(monkeypatch):
    import anthropic
    texte = "Voici :\n```json\n" + json.dumps(_sortie_json(), ensure_ascii=False) + "\n```"
    monkeypatch.setattr(anthropic, "Anthropic", _faux_client([_Bloc(type="text", text=texte)], stop_reason="end_turn"))
    grille, entree, analyse, reponses = _contexte()
    sortie = generation.sortie_llm(grille, entree, analyse, reponses, [{"id": "x", "auteur": "a", "livre": "l", "texte": "t"}])
    assert sortie.metier_principal.titre == "Psychologue"
