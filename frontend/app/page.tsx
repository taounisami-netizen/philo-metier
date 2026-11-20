"use client";

import { useEffect, useState } from "react";
import {
  chargerQuestionnaire,
  envoyerReponses,
  SITUATION_VIDE,
  type ChampSituation,
  type Entree,
  type Questionnaire,
  type Reponse,
  type ReponseProblematique,
  type Resultat,
  type Situation,
} from "@/lib/api";
import IllustrationTramway from "@/components/IllustrationTramway";

type Etape = "accueil" | "situation" | "questions" | "attente" | "resultat";

// « une forte part du stoïque », « de l'épicurien »…
const PART_DE: Record<string, string> = {
  stoique: "du stoïque",
  epicurien: "de l'épicurien",
  sceptique: "du sceptique",
  batisseur: "du bâtisseur rationnel",
  createur: "du créateur",
  moraliste: "du moraliste",
  contemplatif: "du contemplatif",
};

const EN_LETTRES = ["zéro", "une", "deux", "trois"];

const NOMS_PROFILS: Record<string, string> = {
  stoique: "Le stoïque",
  epicurien: "L'épicurien",
  sceptique: "Le sceptique",
  batisseur: "Le bâtisseur rationnel",
  createur: "Le créateur",
  moraliste: "Le moraliste",
  contemplatif: "Le contemplatif",
};

export default function Page() {
  const [etape, setEtape] = useState<Etape>("accueil");
  const [questionnaire, setQuestionnaire] = useState<Questionnaire | null>(null);
  const [erreurServeur, setErreurServeur] = useState<string | null>(null);
  const [entree, setEntree] = useState<Entree>({ poste_actuel: "", statut: "", job_voulu: null, situation: null });
  const [reponses, setReponses] = useState<Record<string, Reponse>>({});
  const [index, setIndex] = useState(0);
  const [resultat, setResultat] = useState<Resultat | null>(null);

  const [reveil, setReveil] = useState(false);

  useEffect(() => {
    // Si le questionnaire tarde, c'est que l'API se réveille : on prévient le visiteur.
    const minuteur = setTimeout(() => setReveil(true), 3000);
    chargerQuestionnaire()
      .then(setQuestionnaire)
      .catch(() =>
        setErreurServeur(
          process.env.NODE_ENV === "development"
            ? "Le serveur ne répond pas. Vérifie que l'API tourne dans un autre terminal : uvicorn app.main:app --port 8000"
            : "Le serveur ne répond pas. Recharge la page dans une minute.",
        ),
      )
      .finally(() => {
        clearTimeout(minuteur);
        setReveil(false);
      });
  }, []);

  async function terminer() {
    if (!questionnaire) return;
    setEtape("attente");
    try {
      const liste = questionnaire.questions.map((q) => reponses[q.id]);
      setResultat(await envoyerReponses(entree, liste));
      setEtape("resultat");
      window.scrollTo(0, 0);
    } catch (e) {
      setErreurServeur(`Le résultat n'a pas pu être calculé : ${(e as Error).message}`);
      setEtape("questions");
    }
  }

  function recommencer() {
    setReponses({});
    setIndex(0);
    setResultat(null);
    setErreurServeur(null);
    setEtape("accueil");
  }

  return (
    <main className="page">
      {etape === "accueil" && (
        <Accueil
          entree={entree}
          setEntree={setEntree}
          statuts={questionnaire?.statuts ?? []}
          erreurServeur={erreurServeur}
          pret={questionnaire !== null}
          reveil={reveil}
          maxChoix={questionnaire?.max_choix ?? 2}
          commencer={() => setEtape("situation")}
        />
      )}
      {etape === "situation" && questionnaire && (
        <EcranSituation
          champs={questionnaire.situation}
          situation={entree.situation ?? SITUATION_VIDE}
          setSituation={(situation) => setEntree({ ...entree, situation })}
          retour={() => setEtape("accueil")}
          continuer={() => {
            setEtape("questions");
            window.scrollTo(0, 0);
          }}
        />
      )}
      {etape === "questions" && questionnaire && (
        <Questions
          questionnaire={questionnaire}
          index={index}
          setIndex={setIndex}
          reponses={reponses}
          setReponses={setReponses}
          erreurServeur={erreurServeur}
          terminer={terminer}
        />
      )}
      {etape === "attente" && (
        <section className="attente" aria-live="polite">
          <p>Lecture de tes philosophes en cours…</p>
          <p className="douce petite">Recherche des passages qui te ressemblent, puis rédaction de ton portrait.</p>
        </section>
      )}
      {etape === "resultat" && resultat && <PageResultat resultat={resultat} recommencer={recommencer} />}
    </main>
  );
}

/* ------------------------------------------------------------------------- */

function Accueil(props: {
  entree: Entree;
  setEntree: (e: Entree) => void;
  statuts: { valeur: string; libelle: string }[];
  erreurServeur: string | null;
  pret: boolean;
  reveil: boolean;
  maxChoix: number;
  commencer: () => void;
}) {
  const { entree, setEntree } = props;
  const [tente, setTente] = useState(false);
  const posteValide = entree.poste_actuel.trim().length >= 2;
  const statutValide = entree.statut !== "";

  function valider(e: React.FormEvent) {
    e.preventDefault();
    setTente(true);
    if (posteValide && statutValide) props.commencer();
  }

  return (
    <section className="accueil">
      <h1>Le métier que TA philosophie t'aurait choisi</h1>
      <p className="chapeau">
        Treize questions tirées des grands débats de la philosophie. À la fin : ton trait dominant, le philosophe qui te
        ressemble, une phrase tirée de ses livres, et le métier que tu aurais pu faire. Si tu décris ta situation, tu
        reçois aussi des pistes concrètes, réalistes avec tes moyens.
      </p>
      <p className="regle">
        À chaque question, tu peux cocher jusqu'à <strong>{EN_LETTRES[props.maxChoix] ?? props.maxChoix} réponses</strong>.
        Mais si tu peux n'en garder qu'une, fais-le : c'est en tranchant qu'on révèle sa philosophie.
      </p>

      <form onSubmit={valider} noValidate>
        <div className="champ">
          <label htmlFor="poste">Ton poste actuel</label>
          <input
            id="poste"
            type="text"
            placeholder="ex. développeur, infirmière, étudiant en droit"
            value={entree.poste_actuel}
            maxLength={120}
            onChange={(e) => setEntree({ ...entree, poste_actuel: e.target.value })}
            aria-invalid={tente && !posteValide}
          />
          {tente && !posteValide && <p className="erreur">Indique ton poste (ou tes études) en quelques mots.</p>}
        </div>

        <div className="champ">
          <label htmlFor="statut">Ton statut</label>
          <select
            id="statut"
            value={entree.statut}
            onChange={(e) => setEntree({ ...entree, statut: e.target.value })}
            aria-invalid={tente && !statutValide}
          >
            <option value="">Choisir…</option>
            {props.statuts.map((s) => (
              <option key={s.valeur} value={s.valeur}>
                {s.libelle}
              </option>
            ))}
          </select>
          {tente && !statutValide && <p className="erreur">Choisis ton statut.</p>}
        </div>

        <div className="champ">
          <label htmlFor="job">Le métier que tu voudrais faire</label>
          <p className="indication">Facultatif. Si tu le remplis, on comparera ce métier à ton profil.</p>
          <input
            id="job"
            type="text"
            value={entree.job_voulu ?? ""}
            maxLength={120}
            onChange={(e) => setEntree({ ...entree, job_voulu: e.target.value || null })}
          />
        </div>

        {props.reveil && (
          <p className="indication" role="status">
            Le serveur se réveille, cela peut prendre jusqu'à une minute. Tu peux remplir le formulaire en attendant.
          </p>
        )}
        {props.erreurServeur && <p className="erreur">{props.erreurServeur}</p>}
        <button className="bouton" type="submit" disabled={!props.pret}>
          Continuer
        </button>
      </form>
    </section>
  );
}

/* ------------------------------------------------------------------------- */

function EcranSituation(props: {
  champs: ChampSituation[];
  situation: Situation;
  setSituation: (s: Situation | null) => void;
  retour: () => void;
  continuer: () => void;
}) {
  const { situation, setSituation } = props;
  const modifier = (champ: keyof Situation, valeur: string) =>
    setSituation({ ...situation, [champ]: valeur.trim() === "" ? null : valeur });

  return (
    <section className="situation">
      <button type="button" className="retour" onClick={props.retour}>
        ← Retour
      </button>
      <h1>Ta situation</h1>
      <p className="chapeau">
        Facultatif, mais c'est ce qui rend le résultat utile. Décris ce que tu cherches à résoudre et les moyens dont tu
        disposes : les pistes proposées tiendront dans ces limites.
      </p>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          props.continuer();
        }}
      >
        <div className="champ">
          <label htmlFor="problematique">Ta problématique</label>
          <p className="indication">En une ou deux phrases : ce que tu veux changer, et ce qui te bloque.</p>
          <textarea
            id="problematique"
            rows={3}
            maxLength={300}
            placeholder="ex. Je veux quitter l'hôpital sans reprendre de longues études."
            value={situation.problematique ?? ""}
            onChange={(e) => modifier("problematique", e.target.value)}
          />
        </div>

        <div className="grille-moyens">
          {props.champs.map((champ) => (
            <div className="champ" key={champ.nom}>
              <label htmlFor={champ.nom}>{champ.libelle}</label>
              <select
                id={champ.nom}
                value={(situation[champ.nom as keyof Situation] as string | null) ?? ""}
                onChange={(e) => modifier(champ.nom as keyof Situation, e.target.value)}
              >
                <option value="">Non précisé</option>
                {champ.choix.map((c) => (
                  <option key={c.valeur} value={c.valeur}>
                    {c.libelle}
                  </option>
                ))}
              </select>
            </div>
          ))}
        </div>

        <div className="champ">
          <label htmlFor="contrainte">Une contrainte importante</label>
          <p className="indication">Ce qui doit absolument être respecté.</p>
          <input
            id="contrainte"
            type="text"
            maxLength={200}
            placeholder="ex. je ne peux pas déménager, je dois garder un salaire"
            value={situation.contrainte ?? ""}
            onChange={(e) => modifier("contrainte", e.target.value)}
          />
        </div>

        <div className="actions">
          <button className="bouton" type="submit">
            Commencer le questionnaire
          </button>
          <button
            type="button"
            className="lien"
            onClick={() => {
              setSituation(null);
              props.continuer();
            }}
          >
            Passer cette étape
          </button>
        </div>
      </form>
    </section>
  );
}

/* ------------------------------------------------------------------------- */

function Questions(props: {
  questionnaire: Questionnaire;
  index: number;
  setIndex: (i: number) => void;
  reponses: Record<string, Reponse>;
  setReponses: (r: Record<string, Reponse>) => void;
  erreurServeur: string | null;
  terminer: () => void;
}) {
  const { questionnaire, index, reponses } = props;
  const total = questionnaire.questions.length;
  const question = questionnaire.questions[index];
  const reponse = reponses[question.id] ?? { question_id: question.id, option_ids: [], texte_libre: null };
  const choisis = reponse.option_ids;
  const max = questionnaire.max_choix;
  const derniere = index === total - 1;

  function basculer(id: string) {
    const option_ids = choisis.includes(id) ? choisis.filter((x) => x !== id) : [...choisis, id];
    if (option_ids.length > max) return;
    props.setReponses({ ...reponses, [question.id]: { ...reponse, option_ids } });
  }

  function suivant() {
    if (derniere) props.terminer();
    else {
      props.setIndex(index + 1);
      window.scrollTo(0, 0);
    }
  }

  return (
    <section>
      <div className="avancement">
        <span>
          Question {index + 1} sur {total}
        </span>
      </div>
      <div className="barre" aria-hidden="true">
        <div style={{ width: `${(index / total) * 100}%` }} />
      </div>

      {question.illustration === "tramway" && <IllustrationTramway />}
      <p className="theme">{question.theme}</p>
      <h1 className="question-texte">{question.texte}</h1>
      <p className="consigne">
        Choisis la réponse qui te ressemble le plus. Si tu hésites vraiment, tu peux en cocher {EN_LETTRES[max] ?? max}.
      </p>

      <ul className="options">
        {question.options.map((o) => {
          const choisi = choisis.includes(o.id);
          return (
            <li key={o.id}>
              <button
                type="button"
                className="option"
                aria-pressed={choisi}
                disabled={!choisi && choisis.length >= max}
                onClick={() => basculer(o.id)}
              >
                {o.texte}
              </button>
            </li>
          );
        })}
      </ul>

      {question.relance && (
        <div className="relance">
          <label htmlFor="relance">{question.relance}</label>
          <p className="indication">Facultatif. Ta réponse aidera à affiner ton portrait.</p>
          <textarea
            id="relance"
            maxLength={500}
            value={reponse.texte_libre ?? ""}
            onChange={(e) =>
              props.setReponses({ ...reponses, [question.id]: { ...reponse, texte_libre: e.target.value || null } })
            }
          />
        </div>
      )}

      {props.erreurServeur && <p className="erreur">{props.erreurServeur}</p>}
      <div className="navigation">
        {index > 0 ? (
          <button type="button" className="lien-bouton" onClick={() => props.setIndex(index - 1)}>
            Question précédente
          </button>
        ) : (
          <span />
        )}
        <button type="button" className="bouton" disabled={choisis.length === 0} onClick={suivant}>
          {derniere ? "Voir mon résultat" : "Question suivante"}
        </button>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------------- */

function Problematique({ question, reponse }: { question: string; reponse: ReponseProblematique | null }) {
  return (
    <section className="bloc problematique">
      <h2>Ta problématique</h2>
      <p className="question-posee">« {question} »</p>
      {!reponse ? (
        <p className="douce">
          L'analyse de ta problématique a besoin de l'IA, qui n'est pas disponible pour le moment. Réessaie un peu plus
          tard.
        </p>
      ) : (
        <>
          <p>{reponse.diagnostic}</p>
          <div className="recommandation">
            <h3>Ce que je te conseille</h3>
            <p>{reponse.recommandation}</p>
          </div>
          <ol className="pistes">
            {reponse.options.map((o) => (
              <li key={o.titre}>
                <h3>{o.titre}</h3>
                <dl>
                  <dt>Durée</dt>
                  <dd>{o.duree}</dd>
                  <dt>Coût</dt>
                  <dd>{o.cout}</dd>
                  <dt>Financements</dt>
                  <dd>{o.financements}</dd>
                </dl>
                <p>{o.pourquoi_toi}</p>
                <p className="sous-titre">Pour commencer cette semaine</p>
                <ul>
                  {o.premieres_etapes.map((etape) => (
                    <li key={etape}>{etape}</li>
                  ))}
                </ul>
              </li>
            ))}
          </ol>
          <div className="risques">
            <p className="sous-titre">À vérifier avant de te lancer</p>
            <ul>
              {reponse.risques.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          </div>
        </>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------------- */

function PageResultat({ resultat, recommencer }: { resultat: Resultat; recommencer: () => void }) {
  const { sortie, profil } = resultat;
  const secondaire = PART_DE[profil.secondaire];

  return (
    <article className="resultat">
      <p className="douce">Ton profil</p>
      <h1 className="profil">{resultat.nom_profil}</h1>
      <p className="trait">
        {resultat.trait_dominant}
        {profil.mixte && secondaire ? `, avec une forte part ${secondaire}` : ""}
      </p>

      <figure className="citation">
        <blockquote>« {sortie.citation.texte} »</blockquote>
        <figcaption>
          {sortie.citation.auteur}, <cite>{sortie.citation.livre}</cite>
          {sortie.citation.url && (
            <>
              {" "}
              (
              <a href={sortie.citation.url} target="_blank" rel="noopener noreferrer">
                lire le passage
              </a>
              )
            </>
          )}
        </figcaption>
      </figure>

      {resultat.entree.situation?.problematique && (
        <Problematique
          question={resultat.entree.situation.problematique}
          reponse={sortie.reponse_problematique}
        />
      )}

      <section className="bloc">
        <h2>Le métier que tu aurais pu faire</h2>
        <p className="metier">{sortie.metier_principal.titre}</p>
        <p>{sortie.metier_principal.pourquoi}</p>
      </section>

      <section className="bloc">
        <h2>Deux autres pistes</h2>
        <ul className="alternatifs">
          {sortie.metiers_alternatifs.map((m) => (
            <li key={m.titre}>
              <strong>{m.titre}.</strong> {m.pourquoi}
            </li>
          ))}
        </ul>
      </section>

      {sortie.ecart_job_voulu && resultat.entree.job_voulu && (
        <section className="bloc">
          <h2>Et le métier que tu vises : {resultat.entree.job_voulu}</h2>
          <p>{sortie.ecart_job_voulu}</p>
        </section>
      )}

      <section className="bloc">
        <h2>Le livre à lire en premier</h2>
        <p>
          <cite>{sortie.livre_a_lire.titre}</cite>, {sortie.livre_a_lire.auteur}. {sortie.livre_a_lire.pourquoi}
        </p>
      </section>

      {resultat.echos.length > 0 && (
        <section className="bloc">
          <h2>Ce qui, dans tes réponses, t'en rapproche</h2>
          <ul className="echos">
            {resultat.echos.map((e) => (
              <li key={e.idee}>
                {e.philosophe} : <em>{e.idee}</em>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="bloc">
        <h2>Tes scores</h2>
        <ul className="scores">
          {profil.scores.map((s) => (
            <li key={s.profil_id} className={s.profil_id === profil.dominant ? "dominant" : ""}>
              <span>{NOMS_PROFILS[s.profil_id] ?? s.profil_id}</span>
              <span className="jauge" aria-hidden="true">
                <div style={{ width: `${Math.round(s.score * 100)}%` }} />
              </span>
              <span className="valeur">{s.score.toFixed(2)}</span>
            </li>
          ))}
        </ul>
      </section>

      <button type="button" className="bouton" onClick={recommencer}>
        Recommencer le questionnaire
      </button>

      {resultat.mode === "demo" && (
        <p className="note-demo">
          Résultat rédigé sans IA (aucune clé d'API configurée, ou IA indisponible) : le métier vient de la grille des
          profils et la citation est le passage du corpus le plus proche de ton profil.
        </p>
      )}
    </article>
  );
}
