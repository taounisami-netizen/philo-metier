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

export type Metier = { titre: string; pourquoi: string };
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
  mode: "llm" | "demo";
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
    reponse_problematique: ReponseProblematique | null;
  };
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

export async function chargerQuestionnaire(): Promise<Questionnaire> {
  return lire(await fetch("/api/questionnaire"));
}

export async function envoyerReponses(entree: Entree, reponses: Reponse[]): Promise<Resultat> {
  return lire(
    await fetch("/api/resultat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entree, reponses }),
    }),
  );
}
