"""Tests du pipeline d'ingestion (sans réseau ni modèle d'embeddings)."""

import numpy as np
import pytest

from ingestion.decouper import (
    CHEVAUCHEMENT_MAX,
    TAILLE_MAX,
    couper_en_phrases,
    decouper_livre,
    decouper_section,
    nb_mots,
    profils_par_auteur,
)
from ingestion.nettoyer import nettoyer_texte, retirer_licence_gutenberg
from ingestion.rechercher import top_k
from ingestion.telecharger import html_vers_texte, ordre_table_des_matieres, tri_naturel


# --- Téléchargement (fonctions pures) -----------------------------------------

def test_html_wikisource_vers_texte():
    html = """
    <div class="ws-noexport">Bandeau de navigation</div>
    <h2>LIVRE PREMIER<span class="mw-editsection">[modifier]</span></h2>
    <p>Le sage ne s'inquiète pas<sup class="reference">[1]</sup> de l'opinion.</p>
    <span class="pagenum">12</span>
    <p>Second paragraphe.</p>
    <ol class="references"><li>Note du traducteur.</li></ol>
    """
    texte = html_vers_texte(html)
    assert "Bandeau" not in texte and "Note du traducteur" not in texte
    assert "[1]" not in texte and "12" not in texte
    assert texte.split("\n\n") == ["LIVRE PREMIER", "Le sage ne s'inquiète pas de l'opinion.", "Second paragraphe."]


def test_ordre_de_la_table_des_matieres():
    html = '<a href="/wiki/R%C3%A9p/Livre_premier">I</a> <a href="/wiki/R%C3%A9p/Livre_deuxi%C3%A8me">II</a>'
    alphabetique = ["Rép/Livre deuxième", "Rép/Livre premier", "Rép/Notes"]
    assert ordre_table_des_matieres(html, alphabetique) == ["Rép/Livre premier", "Rép/Livre deuxième", "Rép/Notes"]


def test_tri_naturel():
    titres = ["Essais/Livre II/Chapitre 1", "Essais/Livre I/Chapitre 10", "Essais/Livre I/Chapitre 2"]
    assert tri_naturel(titres) == ["Essais/Livre I/Chapitre 2", "Essais/Livre I/Chapitre 10", "Essais/Livre II/Chapitre 1"]


# --- Nettoyage ----------------------------------------------------------------

GUTENBERG = """The Project Gutenberg eBook of Test
License blabla
*** START OF THE PROJECT GUTENBERG EBOOK TEST ***

CHAPITRE PREMIER

La vie oscille, comme un pendule, de droite
à gauche, de la souffrance à l'en-
nui.

Second paragraphe.

*** END OF THE PROJECT GUTENBERG EBOOK TEST ***
Licence finale"""


def test_licence_gutenberg_retiree():
    texte = retirer_licence_gutenberg(GUTENBERG)
    assert "License" not in texte and "Licence finale" not in texte
    assert "CHAPITRE PREMIER" in texte


def test_nettoyage_gutenberg_recolle_les_lignes_et_les_cesures():
    texte = nettoyer_texte(GUTENBERG, gutenberg=True)
    assert texte.split("\n\n") == [
        "CHAPITRE PREMIER",
        "La vie oscille, comme un pendule, de droite à gauche, de la souffrance à l'ennui.",
        "Second paragraphe.",
    ]


def test_nettoyage_artefacts_wikisource():
    texte = nettoyer_texte("Le devoir [modifier] commande[2] ↑ sans condition .")
    assert texte == "Le devoir commande sans condition."


# --- Découpage ----------------------------------------------------------------

def paragraphe(n_mots: int, mot: str = "mot") -> str:
    return " ".join([mot] * (n_mots - 1)) + " fin."


def test_couper_un_paragraphe_trop_long_entre_les_phrases():
    phrases = [f"Phrase numéro {i} " + " ".join(["mot"] * 47) + "." for i in range(30)]  # 30 × 50 mots
    morceaux = couper_en_phrases(" ".join(phrases), taille_max=200)
    assert all(nb_mots(m) <= 200 for m in morceaux)
    assert all(m.endswith(".") for m in morceaux)  # jamais coupé au milieu d'une phrase
    assert sum(nb_mots(m) for m in morceaux) == 1500  # rien n'est perdu


@pytest.mark.parametrize("graine", range(30))
def test_passages_entre_min_et_max(graine):
    """Sur 30 textes aléatoires : aucun passage > TAILLE_MAX, et aucun passage
    minuscule qui ne serait que la répétition du chevauchement."""
    import random
    rng = random.Random(graine)
    phrase = "Le sage distingue ce qui dépend de lui de ce qui n'en dépend pas, et agit en conséquence."
    # « §i » rend chaque paragraphe unique (sinon deux paragraphes de même longueur seraient identiques)
    paras = [f"§{i} " + " ".join([phrase] * rng.randint(1, 45)) for i in range(rng.randint(3, 25))]
    passages = decouper_section("\n\n".join(paras))
    assert all(nb_mots(p) <= TAILLE_MAX for p in passages)
    for avant, apres in zip(passages, passages[1:]):
        assert apres != avant.split("\n\n")[-1], "passage réduit au seul chevauchement"


def test_cas_du_bug_corrige():
    """Le cas réel qui produisait un passage de 42 mots puis un de 525 mots."""
    phrase = "Il y a des choses qui dépendent de nous et d'autres qui n'en dépendent pas, et le sage sait les distinguer."
    paras = [" ".join([phrase] * n) for n in [3, 8, 1, 14, 2, 40, 5, 6, 1, 9, 4]]
    tailles = [nb_mots(p) for p in decouper_section("\n\n".join(paras))]
    assert max(tailles) <= TAILLE_MAX
    assert min(tailles) >= 60


def test_aucun_paragraphe_perdu():
    paras = [paragraphe(n, mot=f"m{i}") for i, n in enumerate([120, 90, 200, 60, 110, 250, 80])]
    passages = decouper_section("\n\n".join(paras))
    for p in paras:
        assert any(p in passage for passage in passages), p


def test_chevauchement_entre_passages():
    paras = [paragraphe(100, mot=f"m{i}") for i in range(8)]  # 8 × 100 mots
    passages = decouper_section("\n\n".join(paras))
    assert len(passages) >= 2
    # le dernier paragraphe d'un passage (≤ 120 mots) ouvre le passage suivant
    for avant, apres in zip(passages, passages[1:]):
        assert apres.startswith(avant.split("\n\n")[-1])


def test_metadonnees_et_profils():
    livre = {"id": "test", "auteur": "Épictète", "titre": "Manuel", "traducteur": "Guyau",
             "sections": [{"titre": "Manuel/I", "texte": paragraphe(50), "url": "https://x"}]}
    passages = decouper_livre(livre, profils_par_auteur())
    assert passages[0]["id"] == "test-000-000"
    assert passages[0]["profils"] == ["stoique"]
    assert passages[0]["section"] == "Manuel/I"


def test_chaque_auteur_du_corpus_a_un_profil():
    import json
    from pathlib import Path
    sources = json.loads((Path(__file__).parent.parent / "ingestion" / "sources.json").read_text("utf-8"))
    table = profils_par_auteur()
    for livre in sources["livres"]:
        assert table.get(livre["auteur"]), f"{livre['auteur']} n'est dans aucun profil"


def test_chaque_profil_a_au_moins_un_livre_dans_le_corpus():
    import json
    from pathlib import Path
    sources = json.loads((Path(__file__).parent.parent / "ingestion" / "sources.json").read_text("utf-8"))
    table = profils_par_auteur()
    couverts = {pr for livre in sources["livres"] for pr in table.get(livre["auteur"], [])}
    assert couverts == {"stoique", "epicurien", "sceptique", "batisseur", "createur", "moraliste", "contemplatif"}


# --- Recherche ----------------------------------------------------------------

def test_top_k_trie_et_complet():
    s = np.array([0.1, 0.9, -0.2, 0.5, 0.7])
    assert top_k(s, 3).tolist() == [1, 4, 3]
    assert top_k(s, 10).tolist() == [1, 4, 3, 0, 2]


def test_similarite_cosinus_egale_produit_scalaire_si_normalise():
    rng = np.random.default_rng(0)
    P = rng.normal(size=(50, 16))
    q = rng.normal(size=16)
    P /= np.linalg.norm(P, axis=1, keepdims=True)
    q /= np.linalg.norm(q)
    cosinus = np.array([p @ q / (np.linalg.norm(p) * np.linalg.norm(q)) for p in P])
    assert np.allclose(P @ q, cosinus)


# --- Filtres et relances ------------------------------------------------------

def test_filtres_montaigne_et_doublons():
    import json, re
    from pathlib import Path
    from ingestion.telecharger import filtrer_titres
    sources = json.loads((Path(__file__).parent.parent / "ingestion" / "sources.json").read_text("utf-8"))
    montaigne = next(l for l in sources["livres"] if l["id"] == "montaigne-essais")["source"]
    titres = ["Essais/Livre I", "Essais/Livre I/Chapitre 1", "Essais/Livre I/Entete",
              "Essais/Livre I/Texte entier", "Essais/Livre III/10", "Essais/Livre III/Chapitre 10"]
    assert filtrer_titres(titres, re.compile(montaigne["inclure"])) == ["Essais/Livre I/Chapitre 1", "Essais/Livre III/Chapitre 10"]


def test_exclusions_globales():
    from ingestion.telecharger import filtrer_titres
    titres = ["Discours (éd. Cousin)/Première partie", "Discours (éd. Cousin)/Texte entier", "Manuel/Titre"]
    assert filtrer_titres(titres) == ["Discours (éd. Cousin)/Première partie"]


def test_delai_de_relance():
    from ingestion.telecharger import delai_avant_nouvel_essai
    assert delai_avant_nouvel_essai(1, "30") == 30          # on respecte Retry-After
    assert [delai_avant_nouvel_essai(n, None) for n in range(1, 6)] == [2, 4, 8, 16, 32]


def test_abandon_si_attente_trop_longue(monkeypatch):
    """Gutenberg peut répondre « reviens dans 6 h » : on abandonne au lieu d'attendre."""
    from ingestion import telecharger as t

    class Reponse:
        status_code = 503
        headers = {"Retry-After": "21600"}

    class Session:
        def get(self, *a, **k):
            return Reponse()

    monkeypatch.setattr(t.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="6.0 h"):
        t.get_avec_relance(Session(), "https://exemple")


def test_titre_suivi_d_un_tres_long_paragraphe():
    """Bug réel (Montaigne) : « Chap. III. De trois commerces. » finissait seul dans un passage."""
    phrase = "Il faut se réserver une arrière-boutique toute nôtre, toute franche, en laquelle nous établissions notre vraie liberté."
    texte = "Chap. III. De trois commerces.\n\n" + " ".join([phrase] * 60) + "\n\nCourte conclusion du chapitre."
    tailles = [nb_mots(p) for p in decouper_section(texte)]
    assert min(tailles) >= 25 and max(tailles) <= TAILLE_MAX, tailles
    assert decouper_section(texte)[0].startswith("Chap. III.")


def test_page_html_refusee_comme_livre_gutenberg():
    from ingestion.telecharger import verifier_gutenberg
    with pytest.raises(RuntimeError, match="maintenance"):
        verifier_gutenberg("<!DOCTYPE html><title>Temporarily Down for Maintenance</title>", "https://x")
    assert verifier_gutenberg("blabla\n*** START OF THE PROJECT GUTENBERG EBOOK X ***\ntexte", "u")
