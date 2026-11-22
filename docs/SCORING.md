# Le calcul du profil, pas à pas

Notations : $Q$ = ensemble des questions, $O_q$ = options de la question $q$ ($n = |O_q| = 5$),
$w(q,o,p)$ = points donnés au profil $p$ par l'option $o$ (0 si $p$ n'y figure pas),
$C_q$ = ensemble des options cochées à la question $q$, avec $k_q = |C_q| \in \{1, 2\}$.

**1. Points obtenus, partagés entre les choix**

Chaque question « vaut » la même chose, qu'on coche une ou deux options : les points sont
divisés par le nombre d'options cochées.

$$P(p) = \sum_{q \in Q} \; \sum_{o \in C_q} \frac{w(q,o,p)}{k_q}$$

Exemple : à q01, tu coches a (stoïque 2) et c (moraliste 2) → stoïque reçoit $2/2 = 1$ point
et moraliste $1$ point. Si tu n'avais coché que a, stoïque aurait reçu 2 points.
Sans ce partage, cocher plus d'options rapporterait plus de points au total : il
suffirait de tout cocher pour tout gagner.

**2. Points maximum possibles**

Le maximum est atteint en cochant une seule option, la meilleure pour $p$ :

$$M(p) = \sum_{q \in Q} \max_{o \in O_q} w(q,o,p)$$

Avec la grille actuelle : $M = 16$ (stoïque), $18$ (sceptique, moraliste, contemplatif), $20$ (épicurien, bâtisseur, créateur).

**3. Score normalisé**

$$S(p) = \frac{P(p)}{M(p)} \in [0, 1]$$

Diviser par $M(p)$ compare des pourcentages et non des points bruts : un profil présent
dans plus de questions n'est pas avantagé mécaniquement.

**4. Pourquoi aucun profil n'est avantagé**

Prenons quelqu'un qui répond au hasard : à chaque question, il coche $k$ options
($k = 1$ ou $2$) choisies uniformément parmi les $n$. Chaque option a alors la probabilité
$\tfrac{k}{n}$ d'être cochée, et rapporte $\tfrac{w}{k}$ si elle l'est. Par linéarité de
l'espérance :

$$\mathbb{E}\big[P(p)\big] = \sum_{q \in Q} \sum_{o \in O_q} \frac{k}{n} \cdot \frac{w(q,o,p)}{k}
= \frac{1}{n} \sum_{q \in Q} \sum_{o \in O_q} w(q,o,p)$$

Le $k$ disparaît : le résultat est le même qu'on coche une ou deux options.

Règle de construction : $p$ apparaît dans **au plus une option** de chaque question. La
somme intérieure n'a donc qu'un terme non nul : $\sum_{o} w(q,o,p) = \max_{o} w(q,o,p)$. D'où :

$$\mathbb{E}\big[S(p)\big] = \frac{1}{M(p)} \cdot \frac{1}{n} \sum_{q} \max_{o} w(q,o,p)
= \frac{1}{n} \cdot \frac{M(p)}{M(p)} = \frac{1}{n} = \frac{1}{5} = 0{,}20$$

Tous les profils ont donc exactement la même moyenne sous des réponses aléatoires.
Deux tests le vérifient : `test_aucun_profil_favorise_par_le_hasard` (avec la formule) et
`test_moyenne_exacte_par_enumeration` (en énumérant toutes les combinaisons possibles,
en fractions exactes, pour $k = 1$ et $k = 2$).

**5. Profil dominant, secondaire et « mixte »**

On trie les scores. Écart $= S(\text{1er}) - S(\text{2e})$. Si l'écart est inférieur à
`SEUIL_MIXTE = 0,10`, le profil est dit mixte. Avec $M \approx 18$, un point vaut environ
$\tfrac{1}{18} \approx 0{,}06$ : le profil est mixte quand le 1er et le 2e sont séparés
par moins de 2 points environ. En cas d'égalité parfaite, l'ordre de `profils.json`
départage, ce qui garde le calcul déterministe.

## Orientation : du profil au métier

Le métier n'est pas choisi par l'IA : il sort d'un calcul, dans `backend/app/orientation.py`,
à partir du tableau `backend/app/grille/metiers.json` (59 métiers, au moins 8 par profil).

**1. Le tableau.** Chaque métier est relié à 1 à 3 profils avec un poids $w_p$ (1 pour son
profil principal, 0,3 à 0,6 pour les autres), et a une ou plusieurs **voies d'accès** :
diplôme requis, durée en mois, coût (financé, moins de 1 000 €, 1 000 à 5 000 €, plus de
5 000 €) et rythme (alternance, temps plein, temps partiel). Chaque profil a au moins un
métier accessible sans diplôme et sans frais (vérifié par un test).

**2. L'affinité.** C'est la moyenne pondérée des scores de l'utilisateur sur les profils du métier :

$$A(m) = \frac{\sum_p w_p \cdot S(p)}{\sum_p w_p}$$

Un métier « pur » du profil dominant vaut $S(\text{dominant})$. Un métier qui mêle le
dominant et le secondaire peut passer devant quand les deux scores sont proches (profil mixte).

**3. Le texte libre.** Le poste actuel et le métier voulu sont comparés à la description
de chaque métier avec le modèle d'embeddings (cosinus). On centre-réduit ces 59 similarités
($z$-score, borné à $\pm 2$), pour ne garder que l'écart à la moyenne :

$$\text{note}(m) = A(m) + 0{,}03 \cdot z_{\text{voulu}}(m) + 0{,}015 \cdot z_{\text{poste}}(m)$$

Le bonus vaut au plus $\pm 0{,}09$ : il départage les métiers proches pour le profil, mais
ne fait pas passer devant un métier d'un profil nettement plus faible (testé). Le poste
actuel lui-même n'est jamais proposé.

**4. Le réalisme.** Si l'utilisateur indique ses moyens, une voie n'est possible que si
son diplôme requis, son coût et sa durée tiennent dans ses moyens, et si son rythme est
compatible avec son temps disponible (alternance et temps plein : temps plein ; temps
partiel : au moins 5 à 10 h par semaine). Un métier est retenu s'il a au moins une voie
possible ; on affiche la plus accessible (coût, puis durée ; sans diplôme connu, les voies
qui exigent un niveau plus élevé passent après).

Si moins de 3 métiers passent, ou si aucun n'appartient au profil dominant ou secondaire,
on **assouplit** les moyens dans cet ordre : délai, temps disponible, budget, diplôme. Le
site le dit (« on a assoupli le délai »), et Claude le mentionne avec tact.

**5. Le choix.** Métier principal = meilleure note. Puis le meilleur autre métier du profil
dominant, et le meilleur du profil secondaire. À note égale, l'ordre du tableau départage :
mêmes réponses → même résultat.

**Modifier le tableau.** Ajouter un métier dans `metiers.json` (identifiant unique,
profils, description d'une phrase, voies d'accès), puis relancer `python -m pytest` : les
tests vérifient le format, l'unicité et la couverture de chaque profil. Les durées et coûts
sont des ordres de grandeur, à vérifier sur onisep.fr et moncompteformation.gouv.fr.

## Modifier la grille

- Ajouter une question : 5 options, 1 ou 2 profils par option, poids de 1 ou 2, une idée
  de philosophe (`echo`), et **jamais le même profil dans deux options** de la question.
- Chaque profil doit rester mesuré par au moins 5 questions (aujourd'hui : 8 à 10), et garder les $M(p)$ proches les uns des autres (aujourd'hui 16 à 20).
- Relancer `python -m pytest` : si une règle est cassée, le chargement échoue avec
  un message qui dit laquelle.

Les `echo` sont des paraphrases d'idées de philosophes, affichées sur la page de résultat. Les citations, elles, viennent toujours du corpus.
