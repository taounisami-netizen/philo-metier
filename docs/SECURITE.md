# Audit de sécurité

Audit réalisé avant la mise en ligne publique du site. Question de départ : **la clé API Anthropic peut-elle être lue ou utilisée par quelqu'un d'autre ?** Puis : que peut faire un visiteur malveillant ?

## 1. Le chemin de la clé

```
backend/.env  →  variable d'environnement  →  bibliothèque anthropic  →  API Anthropic
(serveur API)       (mémoire du serveur)        (en-tête x-api-key)       (HTTPS)
```

| Endroit | La clé y est-elle ? | Vérification |
|---|---|---|
| Dépôt GitHub (tout l'historique) | Non | Recherche de `sk-ant-…` dans tous les commits : aucune. Seul `.env.example` (sans clé) est suivi. |
| `.gitignore` | Bloque tout `.env*` sauf `.env.example` | Testé sur un dépôt vierge |
| Réponses de l'API | Non | `test_la_cle_n_apparait_dans_aucune_reponse` (succès, erreur, validation) |
| Journaux du serveur | Non | Une erreur de Claude n'affiche que son type, jamais son message : `test_une_erreur_du_llm_ne_recopie_pas_son_message_dans_les_logs` |
| Site Next.js et navigateur | Non | Le site ne connaît pas la clé : elle n'existe que dans l'API. Aucune variable `NEXT_PUBLIC_*`. |
| Claude lui-même | Non | La clé sert à s'authentifier, elle n'est jamais dans le texte envoyé à Claude : une injection de prompt ne peut pas la lui faire répéter. |

**Conclusion : la clé ne peut pas être lue.** Le vrai risque est ailleurs : qu'on la fasse **utiliser** à nos frais.

## 2. Risques trouvés et corrections

| # | Risque | Gravité | Correction | Test |
|---|---|---|---|---|
| 1 | **Abus de coût** : 50 résultats demandés en 0,1 s, tous acceptés. En boucle, quelqu'un pouvait vider le crédit Anthropic. | Élevée | Limite par visiteur (5/min, 30/jour) et **plafond global** de 300 appels à Claude par jour, après quoi le site passe en mode démo gratuit. | `test_trop_de_demandes_par_minute_refusees`, `test_budget_claude_du_jour_puis_mode_demo` |
| 2 | **API appelable sans passer par le site** : une fois en ligne, l'API a sa propre adresse publique. | Élevée | Secret partagé `CLE_INTERNE` : le serveur Next.js l'ajoute à chaque appel, et l'API refuse tout le reste (403). Le secret ne quitte jamais les serveurs. | `test_sans_cle_interne_l_api_refuse` + test de bout en bout |
| 3 | **Limite par IP inefficace derrière le site** : l'API ne voyait que l'adresse du serveur Next, donc tous les visiteurs partageaient la même limite. | Moyenne | Le site transmet l'IP du visiteur (`X-Client-IP`). L'API ne la croit que si la clé interne est valide, pour qu'on ne puisse pas l'inventer. | `test_ip_transmise_par_le_site_utilisee_seulement_avec_la_cle` |
| 4 | **Injection de prompt** : un visiteur peut écrire « ignore tes règles et… » dans un champ libre. | Faible (il ne voit que son propre résultat, et la clé n'est pas exposée) | Les textes de l'utilisateur sont encadrés par `<texte_utilisateur>`, ne peuvent pas fermer la balise, et Claude a pour consigne de les traiter comme des données. La sortie reste validée par Pydantic, et la citation vérifiée mot pour mot. | `test_texte_utilisateur_ne_peut_pas_fermer_sa_balise` |
| 5 | **Lien piégé** : le lien « lire le passage » est affiché tel quel. Un lien `javascript:` exécuterait du code. | Faible (le lien vient du corpus, pas de Claude) | Défense en profondeur : seuls les liens Wikisource et Gutenberg sont acceptés. | `test_lien_de_citation_limite_a_nos_sources` |
| 6 | **Requêtes démesurées** : listes de 200 000 réponses ou de 100 000 options. | Faible (déjà refusées, mais après lecture) | Bornes dans le schéma (30 réponses, 5 options) et corps limité à 64 Ko côté site (413). | `test_requetes_demesurees_refusees` |
| 7 | **Informations exposées** : `/docs` décrit toute l'API, `/api/sante` dit si Claude est configuré. | Faible | Avec `PRODUCTION=1`, `/docs` et `/openapi.json` sont désactivés et `/api/sante` répond seulement `{"ok": true}`. Le site ne relaie que 3 routes. | Vérifié manuellement |
| 8 | **En-têtes de sécurité absents** | Faible | `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `Permissions-Policy`, et suppression de `X-Powered-By`. Liens externes en `noopener noreferrer`. | Vérifié avec `curl -I` |

Aucune faille de type XSS : React échappe tout le texte affiché, et le code n'utilise jamais `dangerouslySetInnerHTML`.

## 3. Dépendances

- `npm audit` : 0 vulnérabilité.
- `pip-audit` sur `requirements-ingestion.txt` : aucune vulnérabilité connue.

À relancer avant chaque mise en ligne, car de nouvelles failles sont publiées régulièrement.

## 4. À faire au moment de la mise en ligne

1. **Créer une clé Anthropic dédiée** à ce site, dans un *workspace* séparé de la console Anthropic, avec une **limite de dépenses mensuelle**. Si elle fuit un jour, on la révoque sans toucher aux autres projets, et la facture ne peut pas dépasser la limite.
2. Mettre la clé et `CLE_INTERNE` dans les **secrets** de l'hébergeur, jamais dans le code ni dans un fichier suivi par Git.
3. Activer `PRODUCTION=1` et régler `CORS_ORIGINS` sur l'adresse du site.
4. Générer `CLE_INTERNE` au hasard : `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

## 5. Limites connues

- Les compteurs sont en mémoire : ils repartent de zéro si le serveur redémarre, et ne fonctionnent que pour un seul serveur. Pour plusieurs serveurs, il faudrait un stockage partagé (Redis).
- Quelqu'un qui change d'adresse IP en boucle peut dépasser la limite par visiteur. C'est pour cela que le plafond global de 300 appels par jour, lui, ne dépend pas de l'IP.
