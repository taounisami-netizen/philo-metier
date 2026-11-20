"""Étape 2.1 — Télécharger les livres listés dans sources.json.

Deux sources possibles :
- Wikisource : via l'API officielle (MediaWiki). Un livre est souvent découpé en
  sous-pages (« La République (trad. Cousin)/Livre premier », …) : on les récupère
  toutes, dans l'ordre de la table des matières.
- Gutenberg : un seul fichier texte brut.

Résultat : un fichier JSON par livre dans corpus/brut/, avec la liste des sections
(titre, texte, url). Le texte est déjà débarrassé du HTML, mais pas encore nettoyé.

Usage (depuis backend/) :
    python -m ingestion.telecharger                 # tous les livres
    python -m ingestion.telecharger kant-fondements  # un seul livre
    python -m ingestion.telecharger --lister kant-fondements
        → affiche les sous-pages trouvées, sans rien télécharger (pour régler « exclure »)
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote, unquote

import requests
from bs4 import BeautifulSoup

DOSSIER = Path(__file__).parent
DOSSIER_BRUT = DOSSIER.parent / "corpus" / "brut"
API_WIKISOURCE = "https://fr.wikisource.org/w/api.php"

# Wikimedia demande un User-Agent qui identifie le programme (règle de l'API).
ENTETES = {"User-Agent": "philo-metier/0.1 (projet etudiant ; corpus de philosophie du domaine public)"}
PAUSE = 1.0  # secondes entre deux requêtes, pour ne pas surcharger les serveurs
MAX_TENTATIVES = 6
ATTENTE_MAX = 120  # au-delà, on abandonne ce livre plutôt que d'attendre des heures
DOSSIER_MANUEL = DOSSIER.parent / "corpus" / "manuel"  # fichiers téléchargés à la main

# Pages présentes dans beaucoup de livres Wikisource, jamais utiles : la version
# « Texte entier » (doublon de tous les chapitres), les en-têtes et pages de titre.
EXCLUSIONS_GLOBALES = re.compile(r"/(Texte entier|Entete|Titre)$")

# Éléments HTML de Wikisource qui ne font pas partie du texte de l'auteur.
SELECTEURS_A_SUPPRIMER = [
    "style", "script", "table", ".ws-noexport", ".noprint", ".mw-editsection",
    "sup.reference", "ol.references", ".references", ".reference",
    ".pagenum", ".ws-pagenum", "#headertemplate", ".ws-header", ".headertemplate",
    ".navigation-not-searchable", ".mw-empty-elt",
]


# ---------------------------------------------------------------------------
# Wikisource
# ---------------------------------------------------------------------------

def delai_avant_nouvel_essai(tentative: int, retry_after: str | None) -> float:
    """Délai d'attente après une erreur 429 (trop de requêtes) ou 5xx.
    Si le serveur indique un délai (en-tête Retry-After), on le respecte ; sinon on
    double l'attente à chaque échec (« backoff exponentiel ») : 2, 4, 8, 16, 32 s."""
    if retry_after and retry_after.isdigit():
        return float(retry_after)
    return 2.0 ** tentative


def get_avec_relance(session: requests.Session, url: str, **kwargs) -> requests.Response:
    for tentative in range(1, MAX_TENTATIVES + 1):
        reponse = session.get(url, headers=ENTETES, timeout=60, **kwargs)
        if reponse.status_code == 429 or reponse.status_code >= 500:
            if tentative == MAX_TENTATIVES:
                reponse.raise_for_status()
            attente = delai_avant_nouvel_essai(tentative, reponse.headers.get("Retry-After"))
            if attente > ATTENTE_MAX:
                raise RuntimeError(
                    f"le serveur demande d'attendre {attente / 3600:.1f} h (code {reponse.status_code}) : abandon"
                )
            print(f"      (serveur saturé, code {reponse.status_code} : nouvelle tentative dans {attente:.0f} s)")
            time.sleep(attente)
            continue
        reponse.raise_for_status()
        time.sleep(PAUSE)
        return reponse
    raise RuntimeError("inaccessible")  # jamais atteint


def _api(session: requests.Session, **params) -> dict:
    params |= {"format": "json", "formatversion": 2}
    return get_avec_relance(session, API_WIKISOURCE, params=params).json()


def html_de_la_page(session: requests.Session, titre: str) -> str:
    data = _api(session, action="parse", page=titre, prop="text", disableeditsection=1, redirects=1)
    if "error" in data:
        raise ValueError(f"Wikisource : « {titre} » → {data['error'].get('info')}")
    return data["parse"]["text"]


def html_vers_texte(html: str) -> str:
    """Garde les titres et paragraphes, retire les notes, numéros de page, bandeaux…"""
    soupe = BeautifulSoup(html, "html.parser")
    for selecteur in SELECTEURS_A_SUPPRIMER:
        for element in soupe.select(selecteur):
            element.decompose()
    blocs = []
    for element in soupe.find_all(["h1", "h2", "h3", "h4", "p", "dd", "li", "div"]):
        # On ne prend un <div> que s'il contient directement du texte (poèmes, citations).
        if element.name == "div" and element.find(["p", "div", "h2", "h3", "h4"]):
            continue
        texte = element.get_text(" ", strip=True)
        if texte:
            blocs.append(texte)
    # Supprime les doublons consécutifs (un même bloc capturé deux fois).
    propres = [b for i, b in enumerate(blocs) if i == 0 or b != blocs[i - 1]]
    return "\n\n".join(propres)


def sous_pages(session: requests.Session, prefixe: str) -> list[str]:
    """Toutes les pages dont le titre commence par `prefixe` (ordre alphabétique)."""
    titres, suite = [], {}
    while True:
        data = _api(session, action="query", list="allpages", apprefix=prefixe,
                    apnamespace=0, aplimit="max", **suite)
        titres += [p["title"] for p in data["query"]["allpages"]]
        if "continue" not in data:
            return titres
        suite = {"apcontinue": data["continue"]["apcontinue"]}


def ordre_table_des_matieres(html_principal: str, candidats: list[str]) -> list[str]:
    """Réordonne les sous-pages selon l'ordre des liens de la page principale.
    (L'API les renvoie par ordre alphabétique : « Livre deuxième » avant « Livre premier ».)"""
    soupe = BeautifulSoup(html_principal, "html.parser")
    ordre = []
    for lien in soupe.find_all("a", href=True):
        href = lien["href"]
        if href.startswith("/wiki/"):
            titre = unquote(href[len("/wiki/"):].split("#")[0]).replace("_", " ")
            if titre in candidats and titre not in ordre:
                ordre.append(titre)
    return ordre + [t for t in candidats if t not in ordre]


def tri_naturel(titres: list[str]) -> list[str]:
    """« Chapitre 2 » avant « Chapitre 10 », et Livre I < II < III."""
    romains = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10}

    def cle(titre: str):
        morceaux = re.split(r"(\d+|\b[IVX]+\b)", titre)
        return [
            (0, int(m)) if m.isdigit() else (0, romains[m]) if m in romains else (1, m)
            for m in morceaux if m
        ]

    return sorted(titres, key=cle)


def filtrer_titres(titres: list[str], inclure=None, exclure=None) -> list[str]:
    return [
        t for t in titres
        if not EXCLUSIONS_GLOBALES.search(t)
        and (inclure is None or inclure.search(t))
        and not (exclure and exclure.search(t))
    ]


def wikisource(session: requests.Session, source: dict, lister: bool = False) -> list[dict]:
    # « inclure » : on ne garde QUE les titres qui correspondent ; « exclure » : on retire ceux-là.
    inclure = re.compile(source["inclure"]) if source.get("inclure") else None
    exclure = re.compile(source["exclure"]) if source.get("exclure") else None

    if "prefixe" in source:
        titres = tri_naturel(sous_pages(session, source["prefixe"]))
        html_principal = None
    else:
        page = source["page"]
        html_principal = html_de_la_page(session, page)
        enfants = sous_pages(session, page + "/")
        titres = ordre_table_des_matieres(html_principal, enfants) if enfants else [page]

    gardes = filtrer_titres(titres, inclure, exclure)
    if lister:
        for t in titres:
            print(("  ✓ " if t in gardes else "  ✗ ") + t)
        print(f"\n{len(gardes)} page(s) gardée(s) sur {len(titres)}.")
        return []

    sections = []
    for i, titre in enumerate(gardes, start=1):
        print(f"    [{i}/{len(gardes)}] {titre}")
        html = html_principal if titre == source.get("page") else html_de_la_page(session, titre)
        sections.append({
            "titre": titre,
            "texte": html_vers_texte(html),
            "url": "https://fr.wikisource.org/wiki/" + quote(titre.replace(" ", "_")),
        })
    return sections


# ---------------------------------------------------------------------------
# Gutenberg
# ---------------------------------------------------------------------------

def gutenberg(session: requests.Session, source: dict, lister: bool = False) -> list[dict]:
    numero = source["id"]
    url = f"https://www.gutenberg.org/cache/epub/{numero}/pg{numero}.txt"
    local = DOSSIER_MANUEL / f"pg{numero}.txt"
    if lister:
        print(f"  Gutenberg n°{numero} : un seul fichier → {url}")
        return []
    if local.exists():  # Gutenberg bloque souvent les scripts : fichier téléchargé à la main
        print(f"    fichier local utilisé : corpus/manuel/{local.name}")
        return [{"titre": f"Gutenberg {numero}", "texte": verifier_gutenberg(local.read_text("utf-8"), url), "url": url}]
    try:
        reponse = get_avec_relance(session, url)
    except Exception as e:
        raise RuntimeError(
            f"{e}\n    → Télécharge le fichier avec ton navigateur : {url}\n"
            f"      et enregistre-le sous backend/corpus/manuel/{local.name}, puis relance."
        ) from e
    reponse.encoding = "utf-8"
    return [{"titre": f"Gutenberg {numero}", "texte": verifier_gutenberg(reponse.text, url), "url": url}]


def verifier_gutenberg(texte: str, url: str) -> str:
    """Un vrai livre Gutenberg contient le marqueur « *** START OF … ». Sinon, c'est une
    page d'erreur (maintenance, blocage) qu'il ne faut surtout pas mettre dans le corpus."""
    if "*** START OF" not in texte[:20000]:
        debut = " ".join(texte[:200].split())
        raise RuntimeError(
            f"ce n'est pas un livre Gutenberg (début : « {debut[:80]}… »).\n"
            f"    → Gutenberg est peut-être en maintenance. Réessaie plus tard : {url}"
        )
    return texte


# ---------------------------------------------------------------------------

def charger_sources() -> list[dict]:
    return json.loads((DOSSIER / "sources.json").read_text("utf-8"))["livres"]


def telecharger(livre: dict, session: requests.Session, lister: bool = False,
                forcer: bool = False) -> Path | None:
    print(f"\n▶ {livre['auteur']} — {livre['titre']}")
    deja = DOSSIER_BRUT / f"{livre['id']}.json"
    if deja.exists() and not lister and not forcer:
        print(f"  déjà téléchargé ({deja.name}) — utilise --forcer pour recommencer")
        return deja
    source = livre["source"]
    recuperer = {"wikisource": wikisource, "gutenberg": gutenberg}[source["type"]]
    sections = recuperer(session, source, lister=lister)
    if lister:
        return None
    DOSSIER_BRUT.mkdir(parents=True, exist_ok=True)
    chemin = DOSSIER_BRUT / f"{livre['id']}.json"
    contenu = {k: v for k, v in livre.items() if k != "source"} | {"sections": sections}
    chemin.write_text(json.dumps(contenu, ensure_ascii=False, indent=1), "utf-8")
    nb_mots = sum(len(s["texte"].split()) for s in sections)
    print(f"  → {chemin.name} : {len(sections)} section(s), {nb_mots:,} mots".replace(",", " "))
    return chemin


def main() -> None:
    parser = argparse.ArgumentParser(description="Télécharge les livres du corpus.")
    parser.add_argument("ids", nargs="*", help="identifiants des livres (défaut : tous)")
    parser.add_argument("--lister", action="store_true", help="affiche les pages sans télécharger")
    parser.add_argument("--forcer", action="store_true", help="retélécharge même les livres déjà présents")
    args = parser.parse_args()

    livres = charger_sources()
    if args.ids:
        inconnus = set(args.ids) - {l["id"] for l in livres}
        if inconnus:
            sys.exit(f"Identifiant(s) inconnu(s) : {', '.join(sorted(inconnus))}")
        livres = [l for l in livres if l["id"] in args.ids]

    erreurs = []
    with requests.Session() as session:
        for livre in livres:
            try:
                telecharger(livre, session, lister=args.lister, forcer=args.forcer)
            except Exception as e:  # on continue avec les autres livres
                print(f"  ✗ ERREUR : {e}")
                erreurs.append(livre["id"])
    if erreurs:
        sys.exit(f"\nÉchec pour : {', '.join(erreurs)}")


if __name__ == "__main__":
    main()
