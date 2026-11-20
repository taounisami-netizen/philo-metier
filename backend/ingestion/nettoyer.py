"""Étape 2.2 — Nettoyer le texte brut.

Retire ce qui n'est pas du texte de l'auteur :
- l'en-tête et la licence de Gutenberg (avant « *** START » et après « *** END ») ;
- les artefacts de Wikisource : « [modifier] », appels de notes « [1] », flèches « ↑ » ;
- les césures de fin de ligne (« philo-\\nsophie » → « philosophie ») ;
- les retours à la ligne au milieu des paragraphes (texte brut de Gutenberg).

Usage (depuis backend/) :
    python -m ingestion.nettoyer            # tous les livres de corpus/brut/
"""

import json
import re
import unicodedata
from pathlib import Path

DOSSIER_CORPUS = Path(__file__).parent.parent / "corpus"
DOSSIER_BRUT = DOSSIER_CORPUS / "brut"
DOSSIER_PROPRE = DOSSIER_CORPUS / "propre"

DEBUT_GUTENBERG = re.compile(r"\*\*\*\s*START OF (THE|THIS) PROJECT GUTENBERG.*?\*\*\*", re.I)
FIN_GUTENBERG = re.compile(r"\*\*\*\s*END OF (THE|THIS) PROJECT GUTENBERG", re.I)


def retirer_licence_gutenberg(texte: str) -> str:
    debut = DEBUT_GUTENBERG.search(texte)
    if debut:
        texte = texte[debut.end():]
    fin = FIN_GUTENBERG.search(texte)
    if fin:
        texte = texte[:fin.start()]
    return texte


def recoller_lignes(texte: str) -> str:
    """Dans un texte brut, un paragraphe est coupé en lignes de ~70 caractères.
    On recolle les lignes d'un même paragraphe ; une ligne vide sépare deux paragraphes."""
    paragraphes = re.split(r"\n\s*\n", texte)
    recolles = []
    for p in paragraphes:
        p = re.sub(r"(\w)-\n(\w)", r"\1\2", p)  # césure en fin de ligne
        p = re.sub(r"\s*\n\s*", " ", p)
        recolles.append(p)
    return "\n\n".join(recolles)


def nettoyer_texte(texte: str, gutenberg: bool = False) -> str:
    texte = unicodedata.normalize("NFC", texte)
    texte = texte.replace("\r\n", "\n").replace(" ", " ")
    if gutenberg:
        texte = retirer_licence_gutenberg(texte)
        texte = recoller_lignes(texte)
    texte = re.sub(r"\[\s*modifier[^\]]*\]", "", texte, flags=re.I)  # liens « modifier »
    texte = re.sub(r"\[\d+\]|\[[a-z]\]", "", texte)                  # appels de notes [1] [a]
    texte = re.sub(r"\s*↑\s*", " ", texte)                             # flèches de retour aux notes
    texte = re.sub(r"[ \t]+", " ", texte)
    texte = re.sub(r" +([,.;:!?»)])", r"\1", texte)                   # espace avant ponctuation
    texte = re.sub(r"\n{3,}", "\n\n", texte)
    paragraphes = [p.strip() for p in texte.split("\n\n")]
    return "\n\n".join(p for p in paragraphes if p)


def nettoyer_livre(chemin_brut: Path) -> Path:
    livre = json.loads(chemin_brut.read_text("utf-8"))
    est_gutenberg = any(s["url"].startswith("https://www.gutenberg.org") for s in livre["sections"])
    for section in livre["sections"]:
        section["texte"] = nettoyer_texte(section["texte"], gutenberg=est_gutenberg)
    livre["sections"] = [s for s in livre["sections"] if s["texte"]]
    DOSSIER_PROPRE.mkdir(parents=True, exist_ok=True)
    chemin = DOSSIER_PROPRE / chemin_brut.name
    chemin.write_text(json.dumps(livre, ensure_ascii=False, indent=1), "utf-8")
    nb_mots = sum(len(s["texte"].split()) for s in livre["sections"])
    print(f"  {chemin.name} : {nb_mots:,} mots".replace(",", " "))
    return chemin


def main() -> None:
    fichiers = sorted(DOSSIER_BRUT.glob("*.json"))
    if not fichiers:
        raise SystemExit("Aucun livre dans corpus/brut/ : lance d'abord python -m ingestion.telecharger")
    print("Nettoyage :")
    for f in fichiers:
        nettoyer_livre(f)


if __name__ == "__main__":
    main()
