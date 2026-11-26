import type { NextConfig } from "next";

// Les appels /api/... du site passent par app/api/[...chemin]/route.ts, qui les relaie
// vers l'API Python (API_URL, port 8000 par défaut) en ajoutant la clé interne.

// En-têtes de sécurité envoyés avec chaque page.
const ENTETES_SECURITE = [
  { key: "X-Content-Type-Options", value: "nosniff" }, // le navigateur ne devine pas le type d'un fichier
  { key: "X-Frame-Options", value: "DENY" }, // le site ne peut pas être affiché dans un cadre d'un autre site
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" }, // on ne transmet pas l'adresse complète aux liens externes
  // Position : seulement pour ce site (bouton « Autour de moi »), et le navigateur demande toujours la permission.
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(self)" },
];

const config: NextConfig = {
  poweredByHeader: false, // n'annonce pas « X-Powered-By: Next.js »
  async headers() {
    return [{ source: "/:chemin*", headers: ENTETES_SECURITE }];
  },
};

export default config;
