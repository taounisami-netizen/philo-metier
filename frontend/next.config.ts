import type { NextConfig } from "next";

// Les appels /api/... du site sont renvoyés vers l'API Python (FastAPI) sur le port 8000.
// Le navigateur ne parle qu'à Next.js : pas de problème de CORS.
const config: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:chemin*", destination: `${process.env.API_URL ?? "http://localhost:8000"}/api/:chemin*` }];
  },
};

export default config;
