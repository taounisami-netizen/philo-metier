# Mise en ligne

```
Navigateur ──► Site Next.js (Vercel) ──► API FastAPI (Hugging Face Space) ──► Claude
                 CLE_INTERNE                ANTHROPIC_API_KEY + CLE_INTERNE
```

- **Vercel** héberge le site (gratuit, fait par les créateurs de Next.js).
- **Hugging Face Spaces** héberge l'API dans un conteneur Docker (gratuit, avec assez de mémoire pour le modèle d'embeddings).
- Les secrets ne sont **jamais** dans le code : ils sont saisis dans les réglages de chaque hébergeur.

## 0. Générer la clé interne

Le site et l'API partagent un secret, `CLE_INTERNE`. Il sert à ce que seul le site puisse appeler l'API (voir [SECURITE.md](SECURITE.md)).

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Garde la valeur affichée pour les étapes suivantes. Ne la mets dans aucun fichier.

## 1. L'API sur Hugging Face

1. Crée un compte sur [huggingface.co](https://huggingface.co).
2. **New → Space** : nom `philo-metier-api`, SDK **Docker**, modèle **Blank**, matériel **CPU basic (gratuit)**, visibilité **Public**.
   Le code et le corpus du Space sont publics (comme sur GitHub). Les secrets, eux, restent invisibles.
3. Dans le Space : **Settings → Variables and secrets**
   - *New secret* `ANTHROPIC_API_KEY` : la clé du Workspace philo-metier
   - *New secret* `CLE_INTERNE` : la valeur de l'étape 0
   - *New variable* `CLAUDE_MODEL` : `claude-haiku-5-5`
4. Crée un jeton d'accès en écriture : **Settings → Access Tokens → Create new token**, type **Write**.
5. Envoie l'API, depuis la racine du projet, avec le `.venv` du backend activé :

   ```bash
   pip install -U huggingface_hub
   hf auth login                        # colle le jeton de l'étape 4
   bash deploy/preparer_space.sh        # prépare deploy/build/space/ (vérifie qu'aucun secret n'y est)
   hf upload TON-PSEUDO/philo-metier-api deploy/build/space . --repo-type space
   ```

6. Attends la fin de la construction (onglet **Logs** du Space, 5 à 10 minutes la première fois). Quand le statut est **Running** :
   - `https://TON-PSEUDO-philo-metier-api.hf.space/` doit répondre `{"service":"philo-metier","ok":true}` ;
   - `https://TON-PSEUDO-philo-metier-api.hf.space/api/questionnaire` doit répondre **403** : c'est voulu, l'API refuse ceux qui ne passent pas par le site.

## 2. Le site sur Vercel

1. Crée un compte sur [vercel.com](https://vercel.com) avec **Continue with GitHub**.
2. **Add New → Project**, puis importe le dépôt `philo-metier`.
3. **Root Directory** : `frontend`. Vercel reconnaît Next.js tout seul.
4. **Environment Variables** :
   - `API_URL` : `https://TON-PSEUDO-philo-metier-api.hf.space`
   - `CLE_INTERNE` : la même valeur que sur Hugging Face
5. **Deploy**. Le site est en ligne sur `https://philo-metier-….vercel.app`.

Ensuite, chaque `git push` sur GitHub redéploie automatiquement le site. L'API, elle, se met à jour en relançant les commandes de l'étape 1.5.

## Bon à savoir

- **Réveil de l'API** : un Space gratuit se met en veille après une période sans visite. La première demande qui suit peut prendre une à deux minutes, le temps qu'il redémarre. Les suivantes sont rapides.
- **Budget** : la limite du Workspace philo-metier (5 $/mois), le plafond de 300 appels à Claude par jour et la limite par visiteur s'appliquent. Au-delà, le site passe en mode démo, qui est gratuit.
- **Si une clé fuit** : supprime-la dans la console Anthropic, crée-en une nouvelle et remplace le secret dans le Space. Pour `CLE_INTERNE`, génère une nouvelle valeur et mets-la à jour des deux côtés.
