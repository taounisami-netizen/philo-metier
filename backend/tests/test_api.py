"""Tests de l'API et de la génération (sans modèle d'embeddings ni appel à Claude)."""

import json

import pytest
from fastapi.testclient import TestClient

from app import generation
from app import main as api
from app.main import app, get_orientation, get_recherche
from app.orientation import Orientation, charger_metiers
from app.schemas import Entree, Redaction, Reponse
from app.scoring import calculer_profil, charger_grille

PASSAGE_EPICTETE = (
    "Parmi les choses, les unes dépendent de nous, les autres n'en dépendent pas. "
    "Celles qui dépendent de nous, c'est l'opinion, le vouloir, le désir, l'aversion : "
    "en un mot tout ce qui est notre œuvre."
)


class FausseRecherche:
    passages = [{"id": "x"}]

    def chercher(self, question, profils, k=4):
        return [{
            "id": f"{profils[0]}-000-{i:03d}", "auteur": "Épictète", "livre": "Manuel",
            "texte": PASSAGE_EPICTETE, "url": "https://fr.wikisource.org/wiki/Manuel", "profils": profils,
        } for i in range(k)]


@pytest.fixture
def client(monkeypatch):
    for nom in ("ANTHROPIC_API_KEY", "CLE_INTERNE"):
        monkeypatch.delenv(nom, raising=False)
    app.dependency_overrides[get_recherche] = lambda: FausseRecherche()
    app.dependency_overrides[get_orientation] = lambda: Orientation(encodeur=None)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def reponses_toutes(option="a", n=13):
    return [{"question_id": f"q{i:02d}", "option_ids": [option]} for i in range(1, n + 1)]


def demande(job_voulu="Chef de projet", situation=None):
    entree = {"poste_actuel": "Développeur web", "statut": "alternant", "job_voulu": job_voulu}
    if situation:
        entree["situation"] = situation
    return {"entree": entree, "reponses": reponses_toutes()}


def faux_redaction(job=True, problematique=None):
    return Redaction(pourquoi_metier_principal="Rédigé par Claude.", pourquoi_metiers_alternatifs=["Un.", "Deux."],
                     pourquoi_livre="Pour toi.", ecart_job_voulu="Proche par la méthode." if job else None,
                     reponse_problematique=problematique)


def test_questionnaire_ne_revele_pas_les_points(client):
    data = client.get("/api/questionnaire").json()
    assert len(data["questions"]) == 13 and data["max_choix"] == 2
    option = data["questions"][0]["options"][0]
    assert set(option) == {"id", "texte"}  # ni poids, ni echo
    assert {"valeur": "etudiant", "libelle": "Étudiant"} in data["statuts"]


# --- Résultat calculé (sans IA) -----------------------------------------------------------------

def test_resultat_calcule_sans_ia(client):
    r = client.post("/api/resultat", json=demande())
    assert r.status_code == 200, r.text
    data = r.json()
    sortie = data["sortie"]
    titres = {m.titre for m in charger_metiers()}
    assert sortie["metier_principal"]["titre"] in titres                 # vient du tableau
    assert all(m["titre"] in titres for m in sortie["metiers_alternatifs"])
    assert len({sortie["metier_principal"]["titre"], *(m["titre"] for m in sortie["metiers_alternatifs"])}) == 3
    assert sortie["metier_principal"]["acces"]["voie"]                    # avec sa voie d'accès
    assert sortie["citation"]["texte"] in PASSAGE_EPICTETE                # extrait réel
    assert sortie["ecart_job_voulu"]                                      # job voulu → écart rempli
    assert data["redaction_possible"] is False                            # pas de clé d'API


def test_liens_et_piste_a_l_etranger(client):
    sans = client.post("/api/resultat", json=demande()).json()["sortie"]
    assert sans["metier_etranger"] is None
    assert all(l["url"].startswith("https://") for l in sans["metier_principal"]["liens"])
    avec = client.post("/api/resultat", json=demande(situation={"mobilite": "etranger"})).json()["sortie"]
    affiches = [avec["metier_principal"], *avec["metiers_alternatifs"], *([avec["metier_etranger"]] if avec["metier_etranger"] else [])]
    lieux = {m.titre: m.lieu for m in charger_metiers()}
    assert any(lieux[m["titre"]] == "etranger" for m in affiches)


def test_memes_reponses_meme_resultat(client):
    premier = client.post("/api/resultat", json=demande()).json()
    second = client.post("/api/resultat", json=demande()).json()
    assert premier == second


def test_la_graine_change_avec_les_reponses():
    from app.schemas import DemandeResultat
    a = DemandeResultat(**demande())
    b = DemandeResultat(**(demande() | {"reponses": reponses_toutes("b")}))
    assert generation.graine(a) == generation.graine(DemandeResultat(**demande()))
    assert generation.graine(a) != generation.graine(b)


def test_reponses_incompletes_refusees(client):
    demande_courte = {"entree": {"poste_actuel": "Étudiant", "statut": "etudiant"}, "reponses": reponses_toutes(n=5)}
    r = client.post("/api/resultat", json=demande_courte)
    assert r.status_code == 422 and "sans réponse" in r.text


# --- Rédaction par Claude (POST /api/redaction) ---------------------------------------------------

def test_redaction_impossible_sans_cle(client):
    r = client.post("/api/redaction", json=demande())
    assert r.status_code == 503


def test_redaction_par_claude(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fausse-cle")
    recu = {}
    monkeypatch.setattr(api, "rediger", lambda contenu, entree: recu.update(contenu=contenu) or faux_redaction())
    assert client.post("/api/resultat", json=demande()).json()["redaction_possible"] is True
    r = client.post("/api/redaction", json=demande())
    assert r.status_code == 200, r.text
    assert r.json()["pourquoi_metier_principal"] == "Rédigé par Claude."
    # Claude reçoit les choix déjà faits, à expliquer
    principal = client.post("/api/resultat", json=demande()).json()["sortie"]["metier_principal"]["titre"]
    assert f"Métier principal : {principal}" in recu["contenu"]


def test_panne_de_claude_le_resultat_calcule_reste(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fausse-cle")

    def panne(*a):
        raise RuntimeError("quota dépassé")

    monkeypatch.setattr(api, "rediger", panne)
    assert client.post("/api/redaction", json=demande()).status_code == 503
    assert client.post("/api/resultat", json=demande()).status_code == 200


def test_json_du_llm_entoure_de_texte():
    assert generation._extraire_json('Voici :\n```json\n{"a": 1}\n```') == {"a": 1}


def _contexte(entree=None):
    grille = charger_grille()
    reponses = [Reponse(**r) for r in reponses_toutes()]
    reponses[3] = Reponse(question_id="q04", option_ids=["a"], texte_libre="Je dirais la vérité.")
    entree = entree or Entree(poste_actuel="Développeur", statut="alternant", job_voulu="Médecin")
    analyse = calculer_profil(grille, reponses)
    import random
    passages = FausseRecherche().chercher("", [analyse.dominant])
    choix = Orientation(encodeur=None).orienter(analyse, entree)
    sortie = generation.sortie_calculee(grille, entree, analyse, passages, choix, random.Random(0))
    return grille, entree, analyse, reponses, sortie, choix, passages


def message(entree=None):
    grille, entree, analyse, reponses, sortie, choix, passages = _contexte(entree)
    return generation.message_utilisateur(grille, entree, analyse, reponses, sortie, choix, passages[0])


def test_message_pour_le_llm_contient_l_essentiel():
    _, _, _, _, sortie, choix, _ = _contexte()
    msg = message()
    assert "Développeur" in msg and "Alternant" in msg and "Je dirais la vérité." in msg
    assert "CHOIX DE L'ALGORITHME (à expliquer, pas à modifier)" in msg
    assert choix.principal.voie.nom in msg and sortie.metiers_alternatifs[1].titre in msg
    assert PASSAGE_EPICTETE in msg


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


def _faux_client_successif(reponses, appels):
    """Client qui renvoie une réponse différente à chaque appel."""
    class Messages:
        def create(self, **kwargs):
            appels.append(kwargs)
            return reponses[len(appels) - 1]

    class Client:
        messages = Messages()

    return lambda *a, **k: Client()


def _redaction_json(job=True):
    return json.loads(faux_redaction(job).model_dump_json())


ENTREE_JOB = Entree(poste_actuel="Dev", statut="alternant", job_voulu="Médecin")


def test_claude_repond_par_l_outil(monkeypatch):
    import anthropic
    appels = []
    monkeypatch.setattr(anthropic, "Anthropic", _faux_client([_Bloc(type="tool_use", input=_redaction_json())], appels=appels))
    redaction = generation.rediger("contenu", ENTREE_JOB)
    assert redaction.pourquoi_metier_principal == "Rédigé par Claude."
    assert appels[0]["tools"][0]["name"] == "rediger_resultat"
    assert "$ref" not in json.dumps(appels[0]["tools"][0]["input_schema"])


def test_citation_avec_retour_a_la_ligne_dans_du_texte_brut():
    texte = '{"a": "ligne 1\nligne 2 avec des « guillemets »"}'
    assert generation._extraire_json(texte)["a"].startswith("ligne 1")


def test_reponse_coupee_signalee(monkeypatch):
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", _faux_client([_Bloc(type="text", text='{"pourquoi')], stop_reason="max_tokens"))
    with pytest.raises(RuntimeError, match="max_tokens"):
        generation.rediger("contenu", ENTREE_JOB)


def test_reponse_en_texte_acceptee_si_le_modele_n_utilise_pas_l_outil(monkeypatch):
    import anthropic
    texte = "Voici :\n```json\n" + json.dumps(_redaction_json(), ensure_ascii=False) + "\n```"
    monkeypatch.setattr(anthropic, "Anthropic", _faux_client([_Bloc(type="text", text=texte)], stop_reason="end_turn"))
    assert generation.rediger("contenu", ENTREE_JOB).pourquoi_livre == "Pour toi."


def test_outil_coupe_par_max_tokens_puis_reessai_avec_plus_de_place(monkeypatch):
    import anthropic
    coupee = _Bloc(content=[_Bloc(type="thinking", thinking="…"),
                            _Bloc(type="tool_use", input={"pourquoi_metier_principal": "X"})],
                   stop_reason="max_tokens")
    complete = _Bloc(content=[_Bloc(type="tool_use", input=_redaction_json())], stop_reason="tool_use")
    appels = []
    monkeypatch.setattr(anthropic, "Anthropic", _faux_client_successif([coupee, complete], appels))
    assert generation.rediger("contenu", ENTREE_JOB).pourquoi_metier_principal == "Rédigé par Claude."
    assert [a["max_tokens"] for a in appels] == list(generation.JETONS_MAX)


def test_echec_resume_sans_texte_du_visiteur(monkeypatch):
    import anthropic
    secret = "texte-prive-du-visiteur"
    incomplete = _Bloc(content=[_Bloc(type="tool_use", input={"pourquoi_metier_principal": secret})], stop_reason="tool_use")
    monkeypatch.setattr(anthropic, "Anthropic", _faux_client_successif([incomplete, incomplete], []))
    with pytest.raises(RuntimeError) as erreur:
        generation.rediger("contenu", ENTREE_JOB)
    assert "pourquoi_livre" in str(erreur.value) and "pourquoi_metiers_alternatifs" in str(erreur.value)
    assert secret not in str(erreur.value)  # rien de ce que le modèle (ou le visiteur) a écrit


def test_ecart_obligatoire_si_job_voulu(monkeypatch):
    import anthropic
    appels = []
    monkeypatch.setattr(anthropic, "Anthropic", _faux_client([_Bloc(type="tool_use", input=_redaction_json(job=False))], appels=appels))
    with pytest.raises(RuntimeError, match="ecart_job_voulu"):
        generation.rediger("contenu", ENTREE_JOB)
    assert len(appels) == 2  # une seconde chance a été donnée


def test_modele_lu_au_moment_de_l_appel(monkeypatch):
    monkeypatch.delenv("CLAUDE_MODEL", raising=False)
    assert generation.modele_claude() == generation.MODELE_PAR_DEFAUT
    monkeypatch.setenv("CLAUDE_MODEL", "modele-de-test")
    assert generation.modele_claude() == "modele-de-test"
