# Le corpus et la recherche (RAG)

## Les textes (`backend/ingestion/sources.json`)

| Profil | Auteur | Livre | Traduction | Source |
|---|---|---|---|---|
| Stoïque | Épictète | Manuel (+ extraits des Entretiens) | Jean-Marie Guyau (1854-1888) | Wikisource |
| Épicurien | Épicure | Lettre à Ménécée | Octave Hamelin (1856-1907) | Wikisource |
| Sceptique | Montaigne | Essais | original | Wikisource |
| Bâtisseur | Descartes | Discours de la méthode | original | Wikisource |
| Créateur | Nietzsche | Ainsi parlait Zarathoustra | Henri Albert (1869-1921) | Wikisource |
| Moraliste | Kant | Fondements de la métaphysique des mœurs | Henri Lachelier (1904) — *dates à vérifier* | Wikisource |
| Contemplatif | Platon | La République | Victor Cousin (1792-1867) | Wikisource |
| Contemplatif | Schopenhauer | Aphorismes sur la sagesse dans la vie | J.-A. Cantacuzène (1829-1897) | Gutenberg |

Ajoutés ensuite pour équilibrer les profils :

| Profil | Auteur | Livre | Traduction |
|---|---|---|---|
| Stoïque | Marc Aurèle | Pensées pour moi-même | Jules Barthélemy-Saint-Hilaire (1805-1895) |
| Stoïque | Sénèque | De la brièveté de la vie · De la tranquillité de l'âme | J.-P. Charpentier (1797-1878) · Ch. Du Rozoir (1790-1852) |
| Épicurien | Lucrèce | De la nature des choses | André Lefèvre (1834-1904) |
| Bâtisseur | Spinoza | Éthique | Charles Appuhn (1862-1942) |
| Créateur | Nietzsche | Le Gai Savoir · Par-delà le bien et le mal | Henri Albert (1869-1921) |
| Moraliste | Rousseau | Émile, ou De l'éducation | original |
| Contemplatif | Pascal | Pensées | éd. Léon Brunschvicg (1869-1944) |

Résultat : **3 922 passages**. Par profil : stoïque 240, épicurien 149, sceptique 1 055,
bâtisseur 331, créateur 751, moraliste 755, contemplatif 641. Le déséquilibre ne
fausse pas le profil (calculé sans le corpus), et la recherche filtre par profil :
chaque profil ne cherche que chez ses propres auteurs.

Wikisource (fr) n'accepte que des textes du domaine public en France. Gutenberg
garantit seulement le domaine public aux États-Unis : vérifier le traducteur.

## Lancer le pipeline (depuis `backend/`, `.venv` activé)

```bash
pip install -r requirements-ingestion.txt     # une fois
python -m app.encodeur --telecharger          # modèle ONNX (~120 Mo), une fois

python -m ingestion.telecharger --lister      # 1. voir les pages trouvées (✓ gardée, ✗ exclue)
python -m ingestion.telecharger               # 2. télécharger → corpus/brut/
python -m ingestion.nettoyer                  # 3. nettoyer    → corpus/propre/
python -m ingestion.decouper                  # 4. découper    → corpus/passages.jsonl
python -m ingestion.vectoriser                # 5. vectoriser  → corpus/vecteurs.npy
python -m ingestion.rechercher "ce qui dépend de nous"   # 6. tester la recherche
```

Si une page indésirable est gardée (introduction du traducteur, notes…), ajoute un
mot de son titre dans le champ `exclure` du livre dans `sources.json`, puis relance.

## Découpage en passages

Un modèle d'embeddings résume un texte en **un seul** vecteur. Un chapitre entier
donnerait un vecteur flou, mélangeant toutes ses idées ; un passage de ~350 mots
représente une idée précise, qu'on peut ensuite citer.

- On regroupe des paragraphes entiers jusqu'à 350 mots (cible), jamais plus de 500.
- Un paragraphe de plus de 500 mots est coupé entre deux phrases.
- **Chevauchement** : le dernier paragraphe d'un passage (s'il fait ≤ 120 mots) est
  répété au début du suivant, pour qu'une idée à cheval sur deux passages ne soit pas
  coupée en deux.
- On ne mélange jamais deux chapitres.

## La recherche, pas à pas

Le modèle (`intfloat/multilingual-e5-small`) associe à chaque texte un vecteur de
$d = 384$ nombres. On note $p_1, \dots, p_N$ les vecteurs des passages et $q$ celui de
la question.

**1. Similarité cosinus.** Elle mesure l'angle $\theta$ entre deux vecteurs :

$$\cos(q, p_i) = \frac{q \cdot p_i}{\lVert q \rVert \, \lVert p_i \rVert} = \cos\theta \in [-1, 1]$$

Elle vaut 1 si les vecteurs pointent dans la même direction (même sens), 0 s'ils sont
orthogonaux (sans rapport). Elle ne dépend pas de la longueur des vecteurs, seulement
de leur direction.

**2. Normalisation.** À la vectorisation, chaque vecteur est divisé par sa norme :
$\hat{p} = p / \lVert p \rVert$, donc $\lVert \hat{p} \rVert = 1$. La formule devient :

$$\cos(\hat q, \hat p_i) = \frac{\hat q \cdot \hat p_i}{1 \times 1} = \hat q \cdot \hat p_i = \sum_{j=1}^{d} \hat q_j \, \hat p_{i,j}$$

Un simple produit scalaire : $d$ multiplications et $d - 1$ additions.

**3. Tous les passages d'un coup.** On range les vecteurs des passages en lignes d'une
matrice $P$ de taille $N \times d$. Le produit matrice-vecteur donne les $N$
similarités en une seule opération :

$$s = P \, \hat q \in \mathbb{R}^N, \qquad s_i = \hat p_i \cdot \hat q$$

Coût : $N \times d$ multiplications. Avec $N \approx 5\,000$ passages et $d = 384$,
environ 2 millions d'opérations, soit quelques millisecondes.

**4. Les k meilleurs.** `np.argpartition` isole les $k$ plus grandes valeurs en $O(N)$,
puis on ne trie que ces $k$ valeurs ($O(k \log k)$), au lieu de trier les $N$
($O(N \log N)$).

**5. Filtrer par profil.** Pour chercher uniquement chez les auteurs d'un profil, on
remplace les similarités des autres passages par $-\infty$ avant de prendre les $k$
meilleurs.

Le modèle e5 attend un préfixe : `passage: ` devant les textes du corpus,
`query: ` devant la question. Il a été entraîné ainsi, et l'omettre dégrade les
résultats.

## Comment le résultat est construit (`backend/app/generation.py`)

1. Le profil est calculé par `scoring.py` (déterministe, voir étape 1).
2. Une requête est construite à partir des mots de l'utilisateur (réponses libres), puis
   des idées des philosophes derrière les réponses cochées.
3. Recherche : les 16 passages les plus proches chez les auteurs du profil dominant, puis
   **tirage au sort de 4** (poids $1/\text{rang}$ : les plus proches ont plus de chances,
   au plus 2 passages par livre), et de même 2 parmi 8 chez le profil secondaire. Le
   tirage est **fixé par les réponses** (graine = empreinte SHA-256 de la demande) : deux
   personnes au même profil ne reçoivent pas toujours le même passage, mais une même
   personne qui répond pareil retrouve le même.
4. **Citation** : un extrait réel (premières phrases entières) du premier passage tiré.
   Le **métier** et sa voie d'accès sont choisis par `orientation.py` (voir
   [SCORING.md](SCORING.md#orientation--du-profil-au-métier)), le **livre** est celui de la
   citation s'il fait partie des livres du profil. Tout ce résultat est affiché tout de suite.
5. **Avec une clé Anthropic**, un second appel (`/api/redaction`) recalcule le même
   résultat et demande à Claude d'**expliquer** ces choix et de répondre à la problématique,
   en JSON validé par Pydantic (une seconde chance si c'est invalide). Claude ne peut ni
   changer de métier ni écrire de citation : aucune citation inventée ne peut s'afficher.
6. **Sans clé, ou si Claude ne répond pas** : le résultat calculé reste affiché, avec des
   explications types. Le site fonctionne toujours.

La clé est lue dans `backend/.env`, que `.gitignore` exclut : elle ne part jamais sur GitHub.
