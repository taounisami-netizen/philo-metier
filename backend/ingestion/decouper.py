"""Étape 2.3 — Découper les livres en passages (« chunks »).

Pourquoi découper ? Un modèle d'embeddings transforme un texte en UN vecteur. Si on
vectorise un chapitre entier, toutes ses idées sont mélangées dans un seul vecteur, et
la recherche devient floue. Avec des passages de ~350 mots, chaque vecteur représente
une idée (ou quelques-unes), et on peut citer le passage exact.

Règles :
- on regroupe des paragraphes entiers jusqu'à ~TAILLE_CIBLE mots, sans dépasser TAILLE_MAX ;
- un paragraphe plus long que TAILLE_MAX est coupé entre deux phrases ;
- chevauchement : le dernier paragraphe d'un passage est répété au début du suivant
  (s'il est court), pour qu'une idée à cheval sur deux passages ne soit pas perdue ;
- on ne franchit jamais la frontière entre deux sections (chapitres).

Chaque passage garde ses métadonnées : auteur, livre, traducteur, section, url, et les
profils de la grille auxquels l'auteur est rattaché (lus dans app/grille/profils.json).

Usage (depuis backend/) :
    python -m ingestion.decouper           → corpus/passages.jsonl
"""

import json
import re
from pathlib import Path

DOSSIER_CORPUS = Path(__file__).parent.parent / "corpus"
FICHIER_PROFILS = Path(__file__).parent.parent / "app" / "grille" / "profils.json"

TAILLE_CIBLE = 350   # mots
TAILLE_MAX = 500     # mots
TAILLE_MIN = 60      # un passage plus court est fusionné avec le précédent (si ça tient)
TAILLE_PLANCHER = 25  # en dessous, un passage isolé est jeté (titre seul, citation latine…)
CHEVAUCHEMENT_MAX = 120  # on ne répète le dernier paragraphe que s'il fait moins de 120 mots

FIN_DE_PHRASE = re.compile(r"(?<=[.!?…»])\s+(?=[A-ZÀ-ÖØ-Þ«—])")


def nb_mots(texte: str) -> int:
    return len(texte.split())


def couper_en_phrases(paragraphe: str, taille_max: int = TAILLE_MAX) -> list[str]:
    """Coupe un paragraphe trop long en morceaux de phrases entières (≤ taille_max mots)."""
    phrases = FIN_DE_PHRASE.split(paragraphe)
    morceaux, courant = [], []
    for phrase in phrases:
        if courant and nb_mots(" ".join(courant + [phrase])) > taille_max:
            morceaux.append(" ".join(courant))
            courant = []
        courant.append(phrase)
    if courant:
        morceaux.append(" ".join(courant))
    # Cas extrême : une « phrase » sans ponctuation plus longue que taille_max.
    resultat = []
    for m in morceaux:
        mots = m.split()
        for i in range(0, len(mots), taille_max):
            resultat.append(" ".join(mots[i:i + taille_max]))
    return resultat


def decouper_section(texte: str) -> list[str]:
    paragraphes = []
    for p in texte.split("\n\n"):
        # Un paragraphe trop long est coupé en morceaux de ~TAILLE_CIBLE mots (et non TAILLE_MAX),
        # pour laisser de la place à un titre ou à une courte phrase qui le précède.
        paragraphes += couper_en_phrases(p, TAILLE_CIBLE) if nb_mots(p) > TAILLE_MAX else [p]

    passages: list[list[str]] = []
    courant: list[str] = []
    reporte = False  # True si courant[0] est le paragraphe répété du passage précédent

    def taille(paras: list[str]) -> int:
        return sum(nb_mots(x) for x in paras)

    def que_le_report() -> bool:
        return reporte and len(courant) == 1

    def fermer() -> None:
        """Termine le passage en cours et prépare le chevauchement du suivant."""
        nonlocal courant, reporte
        if courant and not que_le_report():
            passages.append(courant)
            dernier = courant[-1]
            courant = [dernier] if nb_mots(dernier) <= CHEVAUCHEMENT_MAX else []
            reporte = bool(courant)
        else:  # un passage qui ne contiendrait que le report est déjà dans le précédent
            courant, reporte = [], False

    for p in paragraphes:
        if courant and taille(courant) + nb_mots(p) > TAILLE_MAX:
            if taille(courant) < TAILLE_MIN and not reporte and passages:
                # Trop petit pour être un passage : on le rattache au passage précédent.
                passages[-1] = passages[-1] + courant
                courant = []
            else:
                fermer()
            if courant and taille(courant) + nb_mots(p) > TAILLE_MAX:
                courant, reporte = [], False  # le report ne tient pas avec p : on y renonce
        courant.append(p)
        if taille(courant) >= TAILLE_CIBLE:
            fermer()
    if courant and not que_le_report():
        passages.append(courant)

    textes = ["\n\n".join(p) for p in passages]
    # Fusionne un dernier passage trop court avec le précédent, seulement si la somme tient.
    if len(textes) >= 2 and nb_mots(textes[-1]) < TAILLE_MIN \
            and nb_mots(textes[-2]) + nb_mots(textes[-1]) <= TAILLE_MAX:
        dernier = textes.pop()
        if not textes[-1].endswith(dernier):
            textes[-1] += "\n\n" + dernier
    # Un passage minuscule isolé (titre seul…) n'apporte rien à la recherche.
    return [t for t in textes if nb_mots(t) >= TAILLE_PLANCHER]


def profils_par_auteur() -> dict[str, list[str]]:
    profils = json.loads(FICHIER_PROFILS.read_text("utf-8"))["profils"]
    table: dict[str, list[str]] = {}
    for p in profils:
        for philosophe in p["philosophes"]:
            table.setdefault(philosophe, []).append(p["id"])
    return table


def decouper_livre(livre: dict, table_profils: dict[str, list[str]]) -> list[dict]:
    resultat = []
    for num_section, section in enumerate(livre["sections"]):
        for num_passage, texte in enumerate(decouper_section(section["texte"])):
            resultat.append({
                "id": f"{livre['id']}-{num_section:03d}-{num_passage:03d}",
                "livre_id": livre["id"],
                "auteur": livre["auteur"],
                "livre": livre["titre"],
                "traducteur": livre.get("traducteur"),
                "section": section["titre"],
                "url": section["url"],
                "profils": table_profils.get(livre["auteur"], []),
                "nb_mots": nb_mots(texte),
                "texte": texte,
            })
    return resultat


def main() -> None:
    fichiers = sorted((DOSSIER_CORPUS / "propre").glob("*.json"))
    if not fichiers:
        raise SystemExit("Aucun livre dans corpus/propre/ : lance d'abord python -m ingestion.nettoyer")
    table = profils_par_auteur()
    tous = []
    print("Découpage :")
    for f in fichiers:
        passages = decouper_livre(json.loads(f.read_text("utf-8")), table)
        sans_profil = "" if passages and passages[0]["profils"] else "  ⚠ auteur rattaché à aucun profil"
        print(f"  {f.stem} : {len(passages)} passages{sans_profil}")
        tous += passages
    sortie = DOSSIER_CORPUS / "passages.jsonl"
    with sortie.open("w", encoding="utf-8") as fichier:
        for p in tous:
            fichier.write(json.dumps(p, ensure_ascii=False) + "\n")
    tailles = sorted(p["nb_mots"] for p in tous)
    print(f"\n{len(tous)} passages → {sortie}")
    if tailles:
        print(f"Taille : min {tailles[0]}, médiane {tailles[len(tailles) // 2]}, max {tailles[-1]} mots")


if __name__ == "__main__":
    main()
