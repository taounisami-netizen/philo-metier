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

## Modifier la grille

- Ajouter une question : 5 options, 1 ou 2 profils par option, poids de 1 ou 2, une idée
  de philosophe (`echo`), et **jamais le même profil dans deux options** de la question.
- Chaque profil doit rester mesuré par au moins 5 questions (aujourd'hui : 8 à 10), et garder les $M(p)$ proches les uns des autres (aujourd'hui 16 à 20).
- Relancer `python -m pytest` : si une règle est cassée, le chargement échoue avec
  un message qui dit laquelle.

Les `echo` sont des paraphrases d'idées de philosophes, affichées sur la page de résultat. Les citations, elles, viennent toujours du corpus.
