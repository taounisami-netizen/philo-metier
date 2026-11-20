# Mise en ligne

```
Navigateur ──► Site Next.js (Vercel) ──► API FastAPI (Render, Docker) ──► Claude
                 CLE_INTERNE                ANTHROPIC_API_KEY + CLE_INTERNE
```

- **Vercel** héberge le site (gratuit, fait par les créateurs de Next.js).
- **Render** héberge l'API dans un conteneur Docker (plan gratuit : 512 Mo de mémoire). Le modèle d'embeddings tourne au format ONNX quantifié, sans PyTorch, pour tenir dans cette mémoire (voir `backend/app/encodeur.py`).
- Les secrets ne sont **jamais** dans le code : ils sont saisis dans les réglages de chaque hébergeur.

## 0. Avant la première mise en ligne

Le site et l'API partagent un secret, `CLE_INTERNE`. Il sert à ce que seul le site puisse appeler l'API (voir [SECURITE.md](SECURITE.md)).

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Garde la valeur affichée pour les étapes suivantes. Ne la mets dans aucun fichier.

Les vecteurs du corpus doivent avoir été calculés avec l'encodeur ONNX, le même que celui de l'API en ligne (depuis `backend/`, `.venv` activé) :

```bash
pip install -r requirements-ingestion.txt
python -m app.encodeur --telecharger      # modèle ONNX dans backend/modele/ (~120 Mo, ignoré par git)
python -m ingestion.verifier_encodeur     # fidélité, mémoire (doit rester sous ~420 Mo), vitesse
python -m ingestion.vectoriser            # recalcule corpus/vecteurs.npy et corpus/index.json
```

Les trois fichiers `corpus/passages.jsonl`, `corpus/vecteurs.npy` et `corpus/index.json` sont versionnés : Render les prend dans le dépôt GitHub.

## 1. L'API sur Render

1. Crée un compte sur [render.com](https://render.com) avec **GitHub**.
2. **New → Blueprint**, puis choisis le dépôt `philo-metier`. Render lit `render.yaml` à la racine.
3. Render demande la valeur des deux secrets :
   - `ANTHROPIC_API_KEY` : la clé du Workspace philo-metier
   - `CLE_INTERNE` : la valeur de l'étape 0
4. **Apply**. La construction prend 3 à 5 minutes (onglet **Logs** du service `philo-metier-api`).
5. Quand le statut est **Live**, avec l'adresse affichée en haut (`https://philo-metier-api-….onrender.com`) :
   - `/` doit répondre `{"service":"philo-metier","ok":true}` ;
   - `/api/questionnaire` doit répondre **403** : c'est voulu, l'API refuse ceux qui ne passent pas par le site.

Ensuite, chaque `git push` qui modifie `backend/` reconstruit l'API automatiquement.

## 2. Le site sur Vercel

1. Crée un compte sur [vercel.com](https://vercel.com) avec **Continue with GitHub**.
2. **Add New → Project**, puis importe le dépôt `philo-metier`.
3. **Root Directory** : `frontend`. Vercel reconnaît Next.js tout seul.
4. **Environment Variables** :
   - `API_URL` : l'adresse Render de l'étape 1.5, sans `/` à la fin
   - `CLE_INTERNE` : la même valeur que sur Render
5. **Deploy**. Le site est en ligne sur `https://philo-metier-….vercel.app`.

Ensuite, chaque `git push` redéploie automatiquement le site.

## Bon à savoir

- **Réveil de l'API** : le plan gratuit de Render met l'API en veille après 15 minutes sans visite, et le réveil prend environ une minute. Le site charge le questionnaire dès l'ouverture de la page d'accueil, affiche un message si le réveil est en cours, et réessaie tout seul. Le visiteur remplit le formulaire pendant ce temps.
- **Budget** : la limite du Workspace philo-metier (5 $/mois), le plafond de 300 appels à Claude par jour et la limite par visiteur s'appliquent. Au-delà, le site passe en mode démo, qui est gratuit.
- **Si une clé fuit** : supprime-la dans la console Anthropic, crée-en une nouvelle et remplace le secret dans Render (**Environment**). Pour `CLE_INTERNE`, génère une nouvelle valeur et mets-la à jour des deux côtés.
