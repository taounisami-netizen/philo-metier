// Relais entre le navigateur et l'API Python.
//
// Le navigateur n'appelle que /api/... sur le site. Ce code tourne sur le SERVEUR Next.js
// (jamais dans le navigateur) : il transmet la demande à l'API en ajoutant
//   - X-Cle-Interne : le secret partagé avec l'API (variable CLE_INTERNE, côté serveur
//     uniquement : sans le préfixe NEXT_PUBLIC_, Next.js ne l'envoie jamais au navigateur) ;
//   - X-Client-IP : l'adresse du visiteur, pour que l'API limite le nombre de demandes par
//     personne et pas pour tout le site à la fois.
// La clé Anthropic, elle, n'est même pas connue de ce serveur : elle n'existe que dans l'API.

import type { NextRequest } from "next/server";

const API_URL = process.env.API_URL ?? "http://localhost:8000";
const ROUTES_AUTORISEES = new Set(["questionnaire", "resultat", "redaction", "sante", "opportunites", "communes"]);
const TAILLE_MAX = 64 * 1024; // 64 Ko : une réponse complète au questionnaire en fait ~10

// Durée maximale d'une requête sur Vercel (secondes). Le premier appel après une période sans
// visite peut être long : l'API sur Render (plan gratuit) doit se réveiller, ~1 minute.
export const maxDuration = 120;

type Contexte = { params: Promise<{ chemin: string[] }> };

function ipDuVisiteur(requete: NextRequest): string {
  // Sur Vercel, ces en-têtes sont écrits par la plateforme elle-même (le visiteur ne peut pas les falsifier).
  return (
    requete.headers.get("x-real-ip") ??
    requete.headers.get("x-forwarded-for")?.split(",")[0].trim() ??
    "local"
  );
}

async function relayer(requete: NextRequest, contexte: Contexte): Promise<Response> {
  const route = (await contexte.params).chemin.join("/");
  if (!ROUTES_AUTORISEES.has(route)) {
    return Response.json({ detail: "Introuvable." }, { status: 404 });
  }

  let corps: string | undefined;
  if (requete.method === "POST") {
    corps = await requete.text();
    if (corps.length > TAILLE_MAX) {
      return Response.json({ detail: "Demande trop volumineuse." }, { status: 413 });
    }
  }

  const entetes: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "application/json", // pendant un réveil, Render montre une page d'attente aux navigateurs, pas aux API
    "X-Client-IP": ipDuVisiteur(requete),
  };
  if (process.env.CLE_INTERNE) entetes["X-Cle-Interne"] = process.env.CLE_INTERNE;

  try {
    // Paramètres d'URL transmis tels quels (ex. /api/communes?q=nant), bornés en taille.
    const parametres = requete.nextUrl.search.length <= 300 ? requete.nextUrl.search : "";
    const reponse = await fetch(`${API_URL}/api/${route}${parametres}`, {
      method: requete.method,
      headers: entetes,
      body: corps,
      cache: "no-store",
      signal: AbortSignal.timeout(110_000),
    });
    return new Response(reponse.body, {
      status: reponse.status,
      headers: { "Content-Type": reponse.headers.get("Content-Type") ?? "application/json" },
    });
  } catch {
    return Response.json({ detail: "Le serveur ne répond pas. Réessaie dans un instant." }, { status: 502 });
  }
}

export const GET = relayer;
export const POST = relayer;
