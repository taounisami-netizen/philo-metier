"""Étage 2 : offres et formations en alternance près de chez l'utilisateur.

Sources (toutes publiques et gratuites, citées sur chaque carte et sur le site) :
- La bonne alternance, via l'API Apprentissage (DGEFP, beta.gouv.fr) :
    GET /api/job/v1/search        offres en alternance (La bonne alternance et ses partenaires :
                                  France Travail, Indeed…) et entreprises qui recrutent sans offre ;
    GET /api/formation/v1/search  formations en apprentissage (catalogue national des Carif-Oref).
  Clé personnelle (variable LBA_API_KEY), envoyée en « Authorization: Bearer ». Usage non commercial.
- Géoplateforme de l'IGN : GET /geocodage/search pour transformer « Nanterre » en coordonnées. Sans clé.

Rien n'est stocké : chaque recherche interroge les API, et la réponse est gardée 30 minutes en mémoire
(mêmes métiers, même lieu à ~1 km près, même rayon) pour ne pas solliciter les services à chaque clic.

Classement, le même pour tout le monde et affiché sur le site :
- offres : les plus proches d'abord ; à distance égale (à 5 km près), les plus récentes ;
- formations : les plus proches d'abord ; à distance égale, celle dont la session commence le plus tôt.
"""

from __future__ import annotations

import asyncio
import math
import os
import threading
import time
from datetime import date, datetime
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, Field

URL_LBA = "https://api.apprentissage.beta.gouv.fr/api"
URL_SITE_LBA = "https://labonnealternance.apprentissage.beta.gouv.fr"
URL_GEOCODAGE = "https://data.geopf.fr/geocodage/search"
DELAI = 10.0              # secondes par appel : au-delà, on affiche ce qu'on a
DUREE_CACHE = 30 * 60     # secondes
NB_OFFRES, NB_FORMATIONS = 5, 3

NIVEAUX = {"3": "CAP", "4": "Bac", "5": "Bac +2", "6": "Bac +3", "7": "Bac +5"}
TYPES_CONTRAT = {"Apprentissage": "apprentissage", "Professionnalisation": "professionnalisation"}
MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]


# --- Ce que le site reçoit ---------------------------------------------------------------

class Offre(BaseModel):
    titre: str
    entreprise: str
    ville: str
    distance_km: float | None = None
    contrat: str                       # « Apprentissage · 24 mois · dès sept. 2026 »
    diplome: str | None = None         # diplôme préparé pendant le contrat
    publiee_le: str | None = None      # AAAA-MM-JJ
    url: str | None = None             # page de l'offre, où postuler
    source: str                        # « La bonne alternance », « France Travail »…


class Formation(BaseModel):
    intitule: str
    organisme: str
    ville: str
    distance_km: float | None = None
    duree: str | None = None           # « 2 ans »
    prochaine_session: str | None = None
    a_distance: bool = False
    telephone: str | None = None
    email: str | None = None
    url: str | None = None             # fiche ONISEP de la formation


class OpportunitesMetier(BaseModel):
    metier_id: str
    titre: str
    offres: list[Offre] = []
    formations: list[Formation] = []
    nb_offres: int = 0                 # avant de garder les NB_OFFRES premières
    nb_formations: int = 0
    nb_recruteurs: int = 0             # entreprises qui recrutent des alternants sans offre publiée
    voir_plus: str | None = None       # même recherche sur La bonne alternance
    message: str | None = None         # pourquoi il n'y a rien à montrer, le cas échéant


class Source(BaseModel):
    nom: str
    url: str
    role: str


class Opportunites(BaseModel):
    disponible: bool
    rayon_km: int
    metiers: list[OpportunitesMetier]
    sources: list[Source]
    classement: str


class DemandeOpportunites(BaseModel):
    metiers: list[str] = Field(min_length=1, max_length=4)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    rayon_km: int = Field(default=30, ge=5, le=100)


class Commune(BaseModel):
    nom: str
    code_postal: str | None = None
    contexte: str | None = None        # « 92, Hauts-de-Seine, Île-de-France »
    latitude: float
    longitude: float


SOURCES = [
    Source(nom="La bonne alternance", url=URL_SITE_LBA,
           role="offres en alternance (La bonne alternance et ses partenaires) et formations en apprentissage "
                "(catalogue des Carif-Oref), via l'API Apprentissage du ministère du Travail"),
    Source(nom="Géoplateforme (IGN)", url="https://geoservices.ign.fr/services-geoplateforme-geocodage",
           role="position des communes, pour calculer les distances"),
]
CLASSEMENT = ("Offres : les plus proches d'abord, puis les plus récentes à distance égale (à 5 km près). "
              "Formations : les plus proches d'abord, puis la session qui commence le plus tôt.")


# --- Petits outils ---------------------------------------------------------------------------

def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance à vol d'oiseau (formule de haversine), en km."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _coord(point) -> tuple[float, float] | None:
    """GeoJSON : coordinates = [longitude, latitude]."""
    try:
        lon, lat = point["coordinates"]
        return float(lat), float(lon)
    except (TypeError, KeyError, ValueError):
        return None


def _get(d, *cles, defaut=None):
    for c in cles:
        if not isinstance(d, dict):
            return defaut
        d = d.get(c)
    return defaut if d is None else d


def _texte(valeur, longueur: int = 160) -> str | None:
    """Données venues d'un tiers : texte simple, sans retours à la ligne, de longueur bornée."""
    if not isinstance(valeur, str):
        return None
    t = " ".join(valeur.split())
    return (t[: longueur - 1] + "…") if len(t) > longueur else (t or None)


def _url_sure(valeur) -> str | None:
    """Seulement des liens https (jamais javascript:, data:…)."""
    return valeur if isinstance(valeur, str) and valeur.startswith("https://") and len(valeur) < 2000 else None


def _date(valeur) -> date | None:
    if not isinstance(valeur, str):
        return None
    try:
        return datetime.fromisoformat(valeur.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _mois_annee(d: date) -> str:
    return f"{MOIS[d.month - 1]} {d.year}"


def lien_voir_plus(romes: list[str], lat: float, lon: float, rayon: int) -> str:
    return f"{URL_SITE_LBA}/recherche?" + urlencode(
        {"romes": ",".join(romes), "lat": round(lat, 4), "lon": round(lon, 4), "radius": rayon})


# --- Transformation des réponses de l'API ----------------------------------------------------

def offre_depuis(brut: dict, lat: float, lon: float) -> Offre | None:
    titre = _texte(_get(brut, "offer", "title"), 120)
    if not titre:
        return None
    lieu = _get(brut, "workplace", "location") or {}
    position = _coord(lieu.get("geopoint"))
    entreprise = (_texte(_get(brut, "workplace", "brand")) or _texte(_get(brut, "workplace", "name"))
                  or _texte(_get(brut, "workplace", "legal_name")) or "Entreprise non précisée")
    types = [TYPES_CONTRAT.get(t, t.lower()) for t in _get(brut, "contract", "type", defaut=[]) if isinstance(t, str)]
    morceaux = [" ou ".join(types).capitalize() or "Alternance"]
    duree = _get(brut, "contract", "duration")
    if isinstance(duree, int) and duree > 0:
        morceaux.append(f"{duree} mois")
    debut = _date(_get(brut, "contract", "start"))
    if debut:
        morceaux.append(f"dès {_mois_annee(debut)}")
    niveau = _get(brut, "offer", "target_diploma", "european")
    diplome = _texte(_get(brut, "offer", "target_diploma", "label"), 80) or NIVEAUX.get(str(niveau))
    publiee = _date(_get(brut, "offer", "publication", "creation"))
    partenaire = _texte(_get(brut, "identifier", "partner_label"), 60)
    return Offre(
        titre=titre, entreprise=entreprise,
        ville=_ville(_get(lieu, "address")),
        distance_km=round(distance_km(lat, lon, *position), 1) if position else None,
        contrat=" · ".join(morceaux), diplome=diplome,
        publiee_le=publiee.isoformat() if publiee else None,
        url=_url_sure(_get(brut, "apply", "url")),
        source="La bonne alternance" if not partenaire or partenaire.lower().startswith(("offres_emploi_lba", "la bonne"))
        else partenaire,
    )


def _ville(adresse) -> str:
    """« 12 rue X 92000 Nanterre » → « Nanterre » (le plus souvent : ce qui suit le code postal)."""
    t = _texte(adresse, 200) or ""
    morceaux = t.replace(",", " ").split()
    for i, m in enumerate(morceaux):
        if len(m) == 5 and m.isdigit() and i + 1 < len(morceaux):
            return " ".join(morceaux[i + 1:])[:60]
    return t[:60] or "Lieu non précisé"


def formation_depuis(brut: dict, lat: float, lon: float, aujourd_hui: date) -> Formation | None:
    intitule = (_texte(_get(brut, "onisep", "intitule"), 140)
                or _texte(_get(brut, "certification", "valeur", "intitule", "cfd", "long"), 140)
                or _texte(_get(brut, "certification", "valeur", "intitule", "rncp"), 140))
    if not intitule:
        return None
    organisme = None
    for role in ("formateur", "responsable"):
        org = _get(brut, role, "organisme")
        organisme = organisme or _texte(_get(org, "etablissement", "enseigne")) or _texte(_get(org, "unite_legale", "raison_sociale"))
    position = _coord(_get(brut, "lieu", "geolocalisation"))
    sessions = sorted(d for s in _get(brut, "sessions", defaut=[]) if (d := _date(_get(s, "debut"))) and d >= aujourd_hui)
    duree = _get(brut, "modalite", "duree_indicative")
    return Formation(
        intitule=intitule, organisme=organisme or "Organisme non précisé",
        ville=_texte(_get(brut, "lieu", "adresse", "commune", "nom"), 60) or "Lieu non précisé",
        distance_km=round(distance_km(lat, lon, *position), 1) if position else None,
        duree=(f"{duree} an" + ("s" if duree > 1 else "")) if isinstance(duree, (int, float)) and 0 < duree <= 6 else None,
        prochaine_session=sessions[0].isoformat() if sessions else None,
        a_distance=bool(_get(brut, "modalite", "entierement_a_distance", defaut=False)),
        telephone=_texte(_get(brut, "contact", "telephone"), 30),
        email=_texte(_get(brut, "contact", "email"), 120),
        url=_url_sure(_get(brut, "onisep", "url")) or _url_sure(_get(brut, "onisep", "lien_site_onisepfr")),
    )


def classer_offres(offres: list[Offre]) -> list[Offre]:
    vues, uniques = set(), []
    for o in offres:  # la même offre publiée chez plusieurs partenaires
        cle = (o.titre.lower(), o.entreprise.lower(), o.ville.lower())
        if cle not in vues:
            vues.add(cle)
            uniques.append(o)

    def cle_tri(o: Offre):
        tranche = math.floor(o.distance_km / 5) if o.distance_km is not None else 10_000
        return (tranche, -(date.fromisoformat(o.publiee_le).toordinal() if o.publiee_le else 0), o.titre)
    return sorted(uniques, key=cle_tri)


def classer_formations(formations: list[Formation]) -> list[Formation]:
    vues, uniques = set(), []
    for f in formations:
        cle = (f.intitule.lower(), f.organisme.lower(), f.ville.lower())
        if cle not in vues:
            vues.add(cle)
            uniques.append(f)
    return sorted(uniques, key=lambda f: (f.distance_km if f.distance_km is not None else 1e6,
                                          f.prochaine_session or "9999", f.intitule))


# --- Appels aux API --------------------------------------------------------------------------

class Cache:
    def __init__(self, duree: float = DUREE_CACHE, taille: int = 500, horloge=time.time):
        self.duree, self.taille, self.horloge = duree, taille, horloge
        self._donnees: dict = {}
        self._verrou = threading.Lock()

    def lire(self, cle):
        with self._verrou:
            v = self._donnees.get(cle)
            if v and v[0] > self.horloge():
                return v[1]
            self._donnees.pop(cle, None)
            return None

    def ecrire(self, cle, valeur):
        with self._verrou:
            if len(self._donnees) >= self.taille:
                self._donnees.pop(next(iter(self._donnees)))
            self._donnees[cle] = (self.horloge() + self.duree, valeur)


class ServiceIndisponible(Exception):
    pass


class ServiceOpportunites:
    """Interroge La bonne alternance et la Géoplateforme. transport : pour les tests (httpx.MockTransport)."""

    def __init__(self, cle: str | None = None, transport: httpx.AsyncBaseTransport | None = None):
        self.cle = cle if cle is not None else os.environ.get("LBA_API_KEY", "").strip()
        self.transport = transport
        self.cache = Cache()

    @property
    def disponible(self) -> bool:
        return bool(self.cle)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self.transport, timeout=DELAI,
                                 headers={"User-Agent": "philo-metier (projet etudiant, non commercial)"})

    async def _lba(self, client: httpx.AsyncClient, chemin: str, params: dict) -> dict:
        cle_cache = (chemin, tuple(sorted(params.items())))
        if (en_cache := self.cache.lire(cle_cache)) is not None:
            return en_cache
        try:
            r = await client.get(f"{URL_LBA}{chemin}", params=params, headers={"Authorization": f"Bearer {self.cle}"})
        except httpx.HTTPError as e:
            raise ServiceIndisponible(f"{chemin} : {type(e).__name__}") from e
        if r.status_code != 200:
            raise ServiceIndisponible(f"{chemin} : HTTP {r.status_code}")
        donnees = r.json()
        self.cache.ecrire(cle_cache, donnees)
        return donnees

    async def pour_metier(self, client, metier_id: str, titre: str, romes: list[str],
                          lat: float, lon: float, rayon: int) -> OpportunitesMetier:
        resultat = OpportunitesMetier(metier_id=metier_id, titre=titre)
        if not romes:
            resultat.message = ("Ce métier ne se prépare pas par l'alternance, ou s'exerce à l'étranger : "
                                "suis plutôt les liens « S'informer » de sa fiche.")
            return resultat
        # positions arrondies (~1 km) : le cache sert aussi aux voisins, et l'API ne reçoit pas l'adresse exacte
        params = {"romes": ",".join(romes), "latitude": round(lat, 2), "longitude": round(lon, 2), "radius": rayon}
        offres_brutes, formations_brutes = await asyncio.gather(
            self._lba(client, "/job/v1/search", params),
            self._lba(client, "/formation/v1/search", {**params, "page_size": 50}),
            return_exceptions=True,
        )
        if isinstance(offres_brutes, Exception) and isinstance(formations_brutes, Exception):
            raise ServiceIndisponible(str(offres_brutes))
        if not isinstance(offres_brutes, Exception):
            offres = [o for b in offres_brutes.get("jobs", []) if isinstance(b, dict) and (o := offre_depuis(b, lat, lon))]
            offres = classer_offres(offres)
            resultat.offres, resultat.nb_offres = offres[:NB_OFFRES], len(offres)
            resultat.nb_recruteurs = len(offres_brutes.get("recruiters", []) or [])
        if not isinstance(formations_brutes, Exception):
            aujourd_hui = date.today()
            formations = [f for b in formations_brutes.get("data", []) if isinstance(b, dict)
                          and (f := formation_depuis(b, lat, lon, aujourd_hui))]
            formations = classer_formations(formations)
            resultat.formations, resultat.nb_formations = formations[:NB_FORMATIONS], len(formations)
        resultat.voir_plus = lien_voir_plus(romes, lat, lon, rayon)
        if not resultat.offres and not resultat.formations:
            resultat.message = f"Rien dans un rayon de {rayon} km pour l'instant : élargis le rayon."
        return resultat

    async def rechercher(self, demande: DemandeOpportunites, metiers: dict) -> Opportunites:
        """metiers : identifiant → FicheMetier (titre, romes). Les identifiants inconnus sont ignorés."""
        fiches = [metiers[i] for i in dict.fromkeys(demande.metiers) if i in metiers]
        if not self.disponible:
            return Opportunites(disponible=False, rayon_km=demande.rayon_km, sources=SOURCES, classement=CLASSEMENT,
                                metiers=[OpportunitesMetier(metier_id=f.id, titre=f.titre) for f in fiches])
        async with self._client() as client:
            resultats = await asyncio.gather(*(
                self.pour_metier(client, f.id, f.titre, f.romes, demande.latitude, demande.longitude, demande.rayon_km)
                for f in fiches), return_exceptions=True)
        sortie, panne = [], False
        for f, r in zip(fiches, resultats):
            if isinstance(r, Exception):
                panne = True
                r = OpportunitesMetier(metier_id=f.id, titre=f.titre,
                                       message="La bonne alternance ne répond pas pour le moment. Réessaie dans un instant.")
            sortie.append(r)
        return Opportunites(disponible=not (panne and all(not r.offres and not r.formations for r in sortie)),
                            rayon_km=demande.rayon_km, metiers=sortie, sources=SOURCES, classement=CLASSEMENT)

    async def communes(self, texte: str) -> list[Commune]:
        texte = " ".join(texte.split())[:60]
        if len(texte) < 2:
            return []
        cle_cache = ("communes", texte.lower())
        if (en_cache := self.cache.lire(cle_cache)) is not None:
            return en_cache
        async with self._client() as client:
            try:
                r = await client.get(URL_GEOCODAGE, params={"q": texte, "type": "municipality",
                                                            "autocomplete": 1, "limit": 5})
            except httpx.HTTPError as e:
                raise ServiceIndisponible("géocodage") from e
        if r.status_code != 200:
            raise ServiceIndisponible(f"géocodage : HTTP {r.status_code}")
        communes = []
        for f in r.json().get("features", []):
            pos = _coord(_get(f, "geometry"))
            nom = _texte(_get(f, "properties", "city")) or _texte(_get(f, "properties", "label"))
            if pos and nom:
                communes.append(Commune(nom=nom, code_postal=_texte(_get(f, "properties", "postcode"), 10),
                                        contexte=_texte(_get(f, "properties", "context"), 80),
                                        latitude=pos[0], longitude=pos[1]))
        self.cache.ecrire(cle_cache, communes)
        return communes
