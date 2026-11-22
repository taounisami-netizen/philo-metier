"""Les citations affichées ne contiennent ni titres de section ni numérotation."""

from app.generation import est_titre, extrait, nettoyer_passage


def test_titres_reconnus():
    for titre in ["III", "XLVIII.", "12.", "65 bis.", "⁂", "PREMIÈRE PARTIE.", "LIVRE III", "DÉMONSTRATION",
                  "SECTION II ( suite)", "Chap. II", "De l’Oisiveté. Chap. VIII.", "Quatrième et dernière partie.",
                  "XVII la vie humaine comparée à un théâtre.", "361] ﻿ 82"]:
        assert est_titre(titre), titre


def test_phrases_gardees():
    for phrase in ["Oui.", "Ainsi parlait Zarathoustra.", "Le bon sens est la chose du monde la mieux partagée.",
                   "M. Descartes le dit.", "Il y a deux espèces de génies."]:
        assert not est_titre(phrase), phrase


def test_marc_aurele_sans_numero_au_milieu():
    texte = "LIVRE III\n\nI\n\nCe n’est pas le tout de se dire que la vie se perd.\n\nII\n\nIl est d’autres considérations."
    assert extrait(texte) == "Ce n’est pas le tout de se dire que la vie se perd. Il est d’autres considérations."


def test_descartes_sans_titre_de_partie():
    assert extrait("PREMIÈRE PARTIE.\n\nLe bon sens est la chose du monde la mieux partagée.").startswith("Le bon sens")


def test_numeros_dans_le_texte():
    assert nettoyer_passage("XLVIII Si tu veux progresser, accepte.") == "Si tu veux progresser, accepte."
    assert nettoyer_passage("Qu’ont-ils pensé? 395. Ont-ils été plus heureux?") == "Qu’ont-ils pensé? Ont-ils été plus heureux?"
    vers = "Des fleuves, des montagnes, 20 Sous les bois pleins d’oiseaux."
    assert nettoyer_passage(vers, "lucrece-nature") == "Des fleuves, des montagnes, Sous les bois pleins d’oiseaux."


def test_montaigne_nom_de_chapitre_et_lettrine():
    texte = "De l’yvrongnerie\n\nChap. II\n\nLE monde n’est que varieté et dissemblance."
    assert extrait(texte) == "Le monde n’est que varieté et dissemblance."
    lettrine = "Que l’intention juge nos actions. Chap. VII.\n\nL A mort, dict-on, nous acquitte. J’en sçay qui l’ont prins."
    assert extrait(lettrine) == "J’en sçay qui l’ont prins."


def test_titre_seul_complete_par_la_suite():
    long = " ".join(["mot"] * 80) + "."
    resultat = extrait(f"Le mal. — {long}")
    assert resultat.startswith("Le mal. — mot") and resultat.endswith("…")


def test_seneque_sans_numeros_de_paragraphe():
    texte = "Chapitre I. (1) La plupart des mortels se plaignent. (2) Plusieurs convoitent la fortune d’autrui."
    assert extrait(texte) == "La plupart des mortels se plaignent. Plusieurs convoitent la fortune d’autrui."


def test_platon_sans_pagination():
    assert nettoyer_passage("[372a] Je ne le vois pas, Socrate.") == "Je ne le vois pas, Socrate."
