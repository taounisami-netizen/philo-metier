// Types et appels à l'API Python (voir backend/app/schemas.py).

export type Option = { id: string; texte: string };
export type Question = {
  id: string;
  theme: string;
  texte: string;
  relance: string | null;
  illustration: string | null;
  options: Option[];
};
export type Statut = { valeur: string; libelle: string };
export type ChampSituation = { nom: string; libelle: string; choix: Statut[] };
export type Questionnaire = {
  questions: Question[];
  statuts: Statut[];
  max_choix: number;
  situation: ChampSituation[];
};

// La problématique et les moyens de l'utilisateur. Tout est facultatif.
export type Situation = {
  problematique: string | null;
  temps_hebdo: string | null;
  budget: string | null;
  delai: string | null;
  diplome: string | null;
  mobilite: string | null;
  contrainte: string | null;
};
export const SITUATION_VIDE: Situation = {
  problematique: null, temps_hebdo: null, budget: null, delai: null, diplome: null, mobilite: null, contrainte: null,
};

export type Entree = {
  poste_actuel: string;
  statut: string;
  job_voulu: string | null;
  situation: Situation | null;
};
export type Reponse = { question_id: string; option_ids: string[]; texte_libre: string | null };

// La voie d'accès la plus réaliste avec les moyens de l'utilisateur (calculée par l'API).
export type Acces = { voie: string; duree: string; cout: string };
// Fiches ONISEP et France Travail, ou site officiel, pour s'informer sur le métier.
export type Lien = { titre: string; url: string };
export type Metier = { titre: string; pourquoi: string; acces: Acces | null; liens: Lien[] };
export type OptionParcours = {
  titre: string;
  duree: string;
  cout: string;
  financements: string;
  premieres_etapes: string[];
  pourquoi_toi: string;
};
export type ReponseProblematique = {
  diagnostic: string;
  options: OptionParcours[];
  recommandation: string;
  risques: string[];
};
export type Resultat = {
  entree: Entree;
  nom_profil: string;
  trait_dominant: string;
  description_profil: string;
  philosophes: string[];
  echos: { philosophe: string; idee: string }[];
  assouplissements: string[]; // moyens relâchés pour trouver des métiers, ex. « le délai »
  redaction_possible: boolean; // l'API peut demander à Claude de rédiger les explications
  profil: {
    dominant: string;
    secondaire: string;
    mixte: boolean;
    scores: { profil_id: string; score: number }[];
  };
  sortie: {
    metier_principal: Metier;
    metiers_alternatifs: Metier[];
    citation: { texte: string; auteur: string; livre: string; passage_id: string; url: string | null };
    livre_a_lire: { titre: string; auteur: string; pourquoi: string };
    ecart_job_voulu: string | null;
    metier_etranger: Metier | null; // seulement si la personne est prête à partir à l'étranger
  };
};

// Les explications rédigées par Claude, qui remplacent les phrases types du résultat calculé.
export type Redaction = {
  pourquoi_metier_principal: string;
  pourquoi_metiers_alternatifs: string[];
  pourquoi_livre: string;
  ecart_job_voulu: string | null;
  reponse_problematique: ReponseProblematique | null;
};

async function lire<T>(reponse: Response): Promise<T> {
  if (!reponse.ok) {
    let detail = `${reponse.status}`;
    try {
      const corps = await reponse.json();
      detail = typeof corps.detail === "string" ? corps.detail : JSON.stringify(corps.detail);
    } catch {}
    throw new Error(detail);
  }
  return reponse.json();
}

// En ligne, l'API s'endort après 15 minutes sans visite et met environ une minute à se réveiller.
// Si le premier appel échoue pendant ce réveil, on réessaie deux fois avant d'abandonner.
export async function chargerQuestionnaire(essais = 3): Promise<Questionnaire> {
  for (let essai = 1; ; essai++) {
    try {
      return await lire(await fetch("/api/questionnaire"));
    } catch (e) {
      if (essai >= essais) throw e;
      await new Promise((suite) => setTimeout(suite, 3000));
    }
  }
}

function envoyer<T>(route: string, entree: Entree, reponses: Reponse[]): Promise<T> {
  return fetch(`/api/${route}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ entree, reponses }),
  }).then((r) => lire<T>(r));
}

// 1. Le résultat calculé (profil, métiers, citation, livre) : immédiat, sans IA.
export function envoyerReponses(entree: Entree, reponses: Reponse[]): Promise<Resultat> {
  return envoyer("resultat", entree, reponses);
}

// 2. Les explications rédigées par Claude (~30 s). Mêmes données : l'API recalcule le même résultat.
export function demanderRedaction(entree: Entree, reponses: Reponse[]): Promise<Redaction> {
  return envoyer("redaction", entree, reponses);
}
