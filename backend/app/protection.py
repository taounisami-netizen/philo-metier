"""Protections pour un site public : limiter le nombre de résultats et le budget Claude.

La clé API ne sort jamais du serveur, mais chaque appel à Claude coûte de l'argent.
Sans limite, n'importe qui pourrait appeler POST /api/resultat en boucle (avec curl,
sans passer par le site) et vider le crédit du compte Anthropic. Deux garde-fous :

1. Par adresse IP : au plus LIMITE_PAR_MINUTE résultats par minute et
   LIMITE_PAR_JOUR résultats par jour. Au-delà : erreur 429 (« trop de requêtes »).
2. Pour tout le site : au plus LIMITE_LLM_PAR_JOUR appels à Claude par jour.
   Au-delà, les résultats passent en mode démo (gratuit) jusqu'au lendemain.
   C'est le vrai plafond de dépenses : il tient même si quelqu'un change d'IP.

Les compteurs sont en mémoire : ils repartent de zéro au redémarrage, ce qui suffit
pour un seul serveur. Réglages par variables d'environnement (voir .env.example).

3. La clé interne : en ligne, seule le site Next.js a le droit d'appeler l'API.
"""

import hmac
import os
import threading
import time
from collections import defaultdict, deque


def _entier(nom: str, defaut: int) -> int:
    try:
        return int(os.environ.get(nom, defaut))
    except ValueError:
        return defaut


class Limiteur:
    def __init__(self, par_minute: int | None = None, par_jour: int | None = None,
                 llm_par_jour: int | None = None, horloge=time.time):
        self.par_minute = par_minute if par_minute is not None else _entier("LIMITE_PAR_MINUTE", 5)
        self.par_jour = par_jour if par_jour is not None else _entier("LIMITE_PAR_JOUR", 30)
        self.llm_par_jour = llm_par_jour if llm_par_jour is not None else _entier("LIMITE_LLM_PAR_JOUR", 300)
        self.horloge = horloge
        self._verrou = threading.Lock()
        self._requetes: dict[str, deque[float]] = defaultdict(deque)
        self._jour = self._jour_courant()
        self._appels_llm = 0

    def _jour_courant(self) -> int:
        return int(self.horloge() // 86_400)

    def _changer_de_jour_si_besoin(self) -> None:
        jour = self._jour_courant()
        if jour != self._jour:
            self._jour, self._appels_llm = jour, 0

    def autoriser(self, ip: str) -> bool:
        """Enregistre une demande de l'IP. Renvoie False si elle dépasse une limite."""
        maintenant = self.horloge()
        with self._verrou:
            historique = self._requetes[ip]
            while historique and historique[0] <= maintenant - 86_400:  # on oublie ce qui a plus de 24 h
                historique.popleft()
            derniere_minute = sum(1 for t in historique if t > maintenant - 60)
            if derniere_minute >= self.par_minute or len(historique) >= self.par_jour:
                return False
            historique.append(maintenant)
            return True

    def reserver_appel_llm(self) -> bool:
        """Réserve un appel à Claude dans le budget du jour. False si le budget est épuisé."""
        with self._verrou:
            self._changer_de_jour_si_besoin()
            if self._appels_llm >= self.llm_par_jour:
                return False
            self._appels_llm += 1
            return True


def cle_interne_valide(request) -> bool:
    """Vrai si la requête vient bien du site Next.js.

    En ligne, l'API a sa propre adresse publique : sans protection, n'importe qui pourrait
    l'appeler directement (curl…) sans passer par le site. Le site et l'API partagent donc
    un secret, CLE_INTERNE, que le site ajoute dans l'en-tête X-Cle-Interne. Ce secret n'est
    connu que des deux serveurs : il n'est jamais envoyé au navigateur.
    Si CLE_INTERNE n'est pas défini (en local), tout est accepté.
    """
    attendue = os.environ.get("CLE_INTERNE")
    if not attendue:
        return True
    recue = request.headers.get("x-cle-interne", "")
    return hmac.compare_digest(recue.encode(), attendue.encode())  # comparaison à temps constant


def ip_du_client(request) -> str:
    """Adresse du visiteur, pour la limite par IP.

    Derrière le site Next.js, l'API ne voit que l'adresse du serveur Next. Le site transmet
    donc l'adresse du visiteur dans X-Client-IP. On ne croit cet en-tête que si la clé
    interne est configurée (et donc déjà vérifiée) : sinon n'importe qui pourrait l'inventer
    pour contourner la limite.
    """
    if os.environ.get("CLE_INTERNE"):
        transmise = request.headers.get("x-client-ip", "").strip()
        if transmise:
            return transmise[:64]
    return request.client.host if request.client else "inconnu"
