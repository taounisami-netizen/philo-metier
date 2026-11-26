"""Étage 2 : offres et formations (réponses de La bonne alternance et de la Géoplateforme simulées)."""

import asyncio
import json
from datetime import date

import httpx
import pytest

from app.opportunites import (Cache, DemandeOpportunites, ServiceOpportunites, distance_km, formation_depuis,
                              lien_voir_plus, offre_depuis)
from app.orientation import charger_metiers

NANTERRE = (48.898, 2.202)
METIERS = {m.id: m for m in charger_metiers()}


def offre(titre, entreprise, lat, lon, creation="2026-11-20T10:00:00Z", partenaire="La bonne alternance",
          url="https://labonnealternance.apprentissage.beta.gouv.fr/emploi/123"):
    return {
        "identifier": {"id": titre, "partner_label": partenaire, "partner_job_id": "x"},
        "workplace": {"name": entreprise, "brand": None, "legal_name": entreprise,
                      "location": {"address": f"1 rue de la Paix 92000 {entreprise}ville",
                                   "geopoint": {"type": "Point", "coordinates": [lon, lat]}}},
        "apply": {"url": url, "phone": None, "recipient_id": None},
        "contract": {"type": ["Apprentissage"], "duration": 24, "start": "2026-09-01T00:00:00Z",
                     "start_type": None, "start_is_flexible": False, "remote": None},
        "offer": {"title": titre, "target_diploma": {"european": "5", "label": "BTS, DUT, BUT"},
                  "publication": {"creation": creation, "expiration": None}},
    }


def formation(intitule, lat, lon, debut="2027-09-01", ville="Nanterre"):
    return {
        "onisep": {"intitule": intitule, "url": "https://www.onisep.fr/http/redirection/formation/slug/FOR.1"},
        "formateur": {"organisme": {"etablissement": {"enseigne": "CFA Exemple"},
                                    "unite_legale": {"raison_sociale": "ASSOCIATION CFA"}}},
        "lieu": {"adresse": {"commune": {"nom": ville}}, "geolocalisation": {"type": "Point", "coordinates": [lon, lat]}},
        "contact": {"telephone": "01 02 03 04 05", "email": "contact@cfa.fr"},
        "modalite": {"duree_indicative": 2, "entierement_a_distance": False},
        "sessions": [{"debut": "2020-09-01", "fin": "2022-06-30"}, {"debut": debut, "fin": "2029-06-30"}],
    }


def service(gestionnaire, cle="cle-test"):
    return ServiceOpportunites(cle=cle, transport=httpx.MockTransport(gestionnaire))


def lancer(coroutine):
    return asyncio.run(coroutine)


# --- Transformation et classement ---------------------------------------------------------------

def test_distance_paris_nanterre():
    assert 10 < distance_km(48.8566, 2.3522, *NANTERRE) < 14  # ~12 km à vol d'oiseau


def test_offre_lisible():
    o = offre_depuis(offre("Développeur web", "Acme", 48.9, 2.21), *NANTERRE)
    assert o.contrat == "Apprentissage · 24 mois · dès sept. 2026"
    assert o.diplome == "BTS, DUT, BUT" and o.publiee_le == "2026-11-20"
    assert o.ville == "Acmeville" and o.distance_km < 2 and o.source == "La bonne alternance"


def test_offre_lien_dangereux_ecarte():
    o = offre_depuis(offre("X", "Y", 48.9, 2.2, url="javascript:alert(1)"), *NANTERRE)
    assert o.url is None


def test_formation_prochaine_session_et_contact():
    f = formation_depuis(formation("BTS SIO", 48.9, 2.2), *NANTERRE, date(2026, 11, 26))
    assert f.prochaine_session == "2027-09-01" and f.duree == "2 ans"
    assert f.organisme == "CFA Exemple" and f.telephone == "01 02 03 04 05"


def test_lien_voir_plus():
    assert lien_voir_plus(["M1805"], 48.898, 2.202, 30).startswith(
        "https://labonnealternance.apprentissage.beta.gouv.fr/recherche?romes=M1805&lat=48.898")


def test_cache_expire():
    t = [0.0]
    c = Cache(duree=10, horloge=lambda: t[0])
    c.ecrire("a", 1)
    assert c.lire("a") == 1
    t[0] = 11
    assert c.lire("a") is None


# --- Recherche complète --------------------------------------------------------------------------

def test_recherche_classe_et_cite_ses_sources():
    vus = []

    def api(requete: httpx.Request):
        vus.append(requete)
        assert requete.headers["Authorization"] == "Bearer cle-test"
        if requete.url.path.endswith("/job/v1/search"):
            return httpx.Response(200, json={"jobs": [
                offre("Loin mais récent", "A", 49.2, 2.5, creation="2026-11-25T00:00:00Z"),
                offre("Proche ancien", "B", 48.90, 2.21, creation="2026-10-01T00:00:00Z"),
                offre("Proche récent", "C", 48.91, 2.20, creation="2026-11-24T00:00:00Z"),
                offre("Proche récent", "C", 48.91, 2.20, creation="2026-11-24T00:00:00Z", partenaire="France Travail"),
            ], "recruiters": [{}, {}, {}], "warnings": []})
        return httpx.Response(200, json={"data": [formation("Loin", 49.5, 2.9), formation("Près", 48.9, 2.2)],
                                         "pagination": {}})

    demande = DemandeOpportunites(metiers=["developpeur-logiciel"], latitude=NANTERRE[0], longitude=NANTERRE[1])
    r = lancer(service(api).rechercher(demande, METIERS))
    m = r.metiers[0]
    assert r.disponible and [o.titre for o in m.offres] == ["Proche récent", "Proche ancien", "Loin mais récent"]
    assert m.nb_offres == 3  # le doublon publié chez deux partenaires compte une fois
    assert m.nb_recruteurs == 3
    assert [f.intitule for f in m.formations] == ["Près", "Loin"]
    assert {s.nom for s in r.sources} >= {"La bonne alternance"}
    # l'API reçoit la position arrondie (~1 km), pas l'adresse exacte
    assert vus[0].url.params["latitude"] == "48.9" and "M1805" in vus[0].url.params["romes"]


def test_cache_evite_un_second_appel():
    appels = []

    def api(requete):
        appels.append(requete.url.path)
        return httpx.Response(200, json={"jobs": [], "recruiters": [], "data": []})

    s = service(api)
    demande = DemandeOpportunites(metiers=["boulanger"], latitude=45.76, longitude=4.83)
    lancer(s.rechercher(demande, METIERS))
    lancer(s.rechercher(demande, METIERS))
    assert len(appels) == 2  # offres + formations, une seule fois


def test_metier_sans_alternance_explique_pourquoi():
    r = lancer(service(lambda req: pytest.fail("aucun appel attendu")).rechercher(
        DemandeOpportunites(metiers=["volontaire-vie"], latitude=48.9, longitude=2.2), METIERS))
    assert r.metiers[0].message and not r.metiers[0].offres


def test_sans_cle_etage_desactive_sans_appel():
    r = lancer(service(lambda req: pytest.fail("aucun appel attendu"), cle="").rechercher(
        DemandeOpportunites(metiers=["boulanger"], latitude=48.9, longitude=2.2), METIERS))
    assert r.disponible is False


def test_api_en_panne_message_clair():
    r = lancer(service(lambda req: httpx.Response(500)).rechercher(
        DemandeOpportunites(metiers=["boulanger"], latitude=48.9, longitude=2.2), METIERS))
    assert r.disponible is False and "ne répond pas" in r.metiers[0].message


def test_metier_inconnu_ignore():
    r = lancer(service(lambda req: httpx.Response(200, json={"jobs": [], "data": []})).rechercher(
        DemandeOpportunites(metiers=["inexistant", "boulanger"], latitude=48.9, longitude=2.2), METIERS))
    assert [m.metier_id for m in r.metiers] == ["boulanger"]


def test_communes():
    def geo(requete):
        assert requete.url.host == "data.geopf.fr" and requete.url.params["type"] == "municipality"
        return httpx.Response(200, json={"features": [{
            "geometry": {"type": "Point", "coordinates": [2.202314, 48.898095]},
            "properties": {"city": "Nanterre", "label": "Nanterre", "postcode": "92000",
                           "context": "92, Hauts-de-Seine, Île-de-France"}}]})
    communes = lancer(service(geo).communes("nant"))
    assert communes[0].nom == "Nanterre" and communes[0].code_postal == "92000"
    assert abs(communes[0].latitude - 48.898) < 0.01
    assert lancer(service(geo).communes("n")) == []


def test_tous_les_metiers_france_ont_des_romes_valides():
    import re
    for m in METIERS.values():
        assert all(re.fullmatch(r"[A-N]\d{4}", r) for r in m.romes), m.id
        if m.lieu == "etranger":
            assert m.romes == []
    assert sum(1 for m in METIERS.values() if m.romes) >= 70
