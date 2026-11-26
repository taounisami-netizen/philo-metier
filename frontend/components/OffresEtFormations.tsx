"use client";

// Étage 2 : offres et formations en alternance près de chez l'utilisateur.
//
// Un seul geste : choisir sa ville (ou « Autour de moi »). Le site cherche alors, en un appel,
// les offres et les formations des métiers proposés, et les affiche sous chacun d'eux.
// La ville choisie est retenue dans ce navigateur pour la prochaine visite (rien n'est envoyé ailleurs).
// Chaque carte dit d'où vient l'information ; le bas de la section cite les sources et le classement.

import { useEffect, useId, useRef, useState } from "react";
import {
  chercherCommunes,
  chercherOpportunites,
  type Commune,
  type Formation,
  type Offre,
  type Opportunites,
  type OpportunitesMetier,
} from "@/lib/api";

const CLE_LIEU = "philo-metier:lieu";
const RAYONS = [10, 30, 50, 100];
const MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];

type Lieu = { nom: string; latitude: number; longitude: number };
type Etat = "attente" | "chargement" | "ok" | "erreur";

function lireLieu(): Lieu | null {
  try {
    const brut = localStorage.getItem(CLE_LIEU);
    const lieu = brut ? JSON.parse(brut) : null;
    return lieu && typeof lieu.latitude === "number" && typeof lieu.longitude === "number" ? lieu : null;
  } catch {
    return null;
  }
}

function retenirLieu(lieu: Lieu) {
  try {
    localStorage.setItem(CLE_LIEU, JSON.stringify(lieu));
  } catch {}
}

function moisAnnee(iso: string): string {
  const [annee, mois] = iso.split("-").map(Number);
  return `${MOIS[mois - 1]} ${annee}`;
}

function anciennete(iso: string): string {
  const jours = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (jours <= 0) return "publiée aujourd'hui";
  if (jours === 1) return "publiée hier";
  if (jours < 30) return `publiée il y a ${jours} jours`;
  return `publiée en ${moisAnnee(iso)}`;
}

function distance(km: number | null): string | null {
  if (km === null) return null;
  return km < 1 ? "à moins de 1 km" : `à ${Math.round(km)} km`;
}

/* --- Choix du lieu --------------------------------------------------------- */

function ChoixLieu({ lieu, choisir }: { lieu: Lieu | null; choisir: (l: Lieu) => void }) {
  const [saisie, setSaisie] = useState("");
  const [suggestions, setSuggestions] = useState<Commune[]>([]);
  const [active, setActive] = useState(-1);
  const [message, setMessage] = useState<string | null>(null);
  const idListe = useId();

  useEffect(() => {
    if (saisie.trim().length < 2) {
      setSuggestions([]);
      return;
    }
    const annulation = new AbortController();
    const minuteur = setTimeout(() => {
      chercherCommunes(saisie, annulation.signal)
        .then((c) => {
          setSuggestions(c);
          setActive(c.length ? 0 : -1);
        })
        .catch(() => {});
    }, 250);
    return () => {
      clearTimeout(minuteur);
      annulation.abort();
    };
  }, [saisie]);

  function prendre(c: Commune) {
    choisir({ nom: c.code_postal ? `${c.nom} (${c.code_postal})` : c.nom, latitude: c.latitude, longitude: c.longitude });
    setSaisie("");
    setSuggestions([]);
  }

  function autourDeMoi() {
    if (!navigator.geolocation) {
      setMessage("Ton navigateur ne donne pas ta position : tape ta ville.");
      return;
    }
    setMessage("Recherche de ta position…");
    navigator.geolocation.getCurrentPosition(
      (p) => {
        setMessage(null);
        choisir({ nom: "autour de toi", latitude: p.coords.latitude, longitude: p.coords.longitude });
      },
      () => setMessage("Position non disponible : tape ta ville."),
      { maximumAge: 600_000, timeout: 10_000 },
    );
  }

  return (
    <div className="choix-lieu">
      <label htmlFor={`${idListe}-saisie`}>{lieu ? "Chercher ailleurs" : "Où cherches-tu ?"}</label>
      <div className="ligne-lieu">
        <input
          id={`${idListe}-saisie`}
          type="text"
          role="combobox"
          aria-expanded={suggestions.length > 0}
          aria-controls={`${idListe}-liste`}
          aria-activedescendant={active >= 0 ? `${idListe}-${active}` : undefined}
          autoComplete="off"
          placeholder="Ta ville ou ton code postal"
          value={saisie}
          onChange={(e) => setSaisie(e.target.value)}
          onKeyDown={(e) => {
            if (!suggestions.length) return;
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setActive((a) => (a + 1) % suggestions.length);
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setActive((a) => (a - 1 + suggestions.length) % suggestions.length);
            } else if (e.key === "Enter" && active >= 0) {
              e.preventDefault();
              prendre(suggestions[active]);
            } else if (e.key === "Escape") {
              setSuggestions([]);
            }
          }}
        />
        <button type="button" className="lien" onClick={autourDeMoi}>
          Autour de moi
        </button>
      </div>
      {suggestions.length > 0 && (
        <ul className="suggestions" id={`${idListe}-liste`} role="listbox">
          {suggestions.map((c, i) => (
            <li
              key={`${c.nom}-${c.code_postal}`}
              id={`${idListe}-${i}`}
              role="option"
              aria-selected={i === active}
              onMouseDown={(e) => {
                e.preventDefault();
                prendre(c);
              }}
            >
              {c.nom} <span className="douce">{[c.code_postal, c.contexte?.split(",").slice(1).join(",").trim()].filter(Boolean).join(" · ")}</span>
            </li>
          ))}
        </ul>
      )}
      {message && <p className="douce petite">{message}</p>}
    </div>
  );
}

/* --- Cartes ------------------------------------------------------------------ */

function CarteOffre({ o }: { o: Offre }) {
  const titre = o.url ? (
    <a href={o.url} target="_blank" rel="noopener noreferrer">
      {o.titre}
    </a>
  ) : (
    o.titre
  );
  return (
    <li className="carte-opportunite">
      <p className="intitule">{titre}</p>
      <p className="details">
        {[o.entreprise, o.ville, distance(o.distance_km)].filter(Boolean).join(" · ")}
        <br />
        {o.contrat}
        {o.diplome ? ` · prépare : ${o.diplome}` : ""}
      </p>
      <p className="provenance">
        {o.publiee_le ? `${anciennete(o.publiee_le)} · ` : ""}via {o.source}
      </p>
    </li>
  );
}

function CarteFormation({ f }: { f: Formation }) {
  const titre = f.url ? (
    <a href={f.url} target="_blank" rel="noopener noreferrer">
      {f.intitule}
    </a>
  ) : (
    f.intitule
  );
  const infos = [f.duree, f.prochaine_session ? `prochaine rentrée : ${moisAnnee(f.prochaine_session)}` : null,
    f.a_distance ? "entièrement à distance" : null].filter(Boolean);
  return (
    <li className="carte-opportunite">
      <p className="intitule">{titre}</p>
      <p className="details">
        {[f.organisme, f.ville, distance(f.distance_km)].filter(Boolean).join(" · ")}
        {infos.length > 0 && (
          <>
            <br />
            {infos.join(" · ")}
          </>
        )}
      </p>
      {(f.telephone || f.email) && (
        <p className="provenance">
          Contacter l'école :{" "}
          {f.telephone && <a href={`tel:${f.telephone.replace(/[^\d+]/g, "")}`}>{f.telephone}</a>}
          {f.telephone && f.email && " · "}
          {f.email && <a href={`mailto:${f.email}`}>{f.email}</a>}
        </p>
      )}
    </li>
  );
}

function BlocMetier({ m, ouvert }: { m: OpportunitesMetier; ouvert: boolean }) {
  const resume = m.message && !m.offres.length && !m.formations.length
    ? ""
    : ` : ${m.nb_offres} offre${m.nb_offres > 1 ? "s" : ""}, ${m.nb_formations} formation${m.nb_formations > 1 ? "s" : ""}`;
  return (
    <details className="opportunites-metier" open={ouvert}>
      <summary>
        <span className="titre-metier">{m.titre}</span>
        <span className="douce">{resume}</span>
      </summary>
      {m.message && <p className="douce petite">{m.message}</p>}
      {m.offres.length > 0 && (
        <>
          <h3>Offres en alternance</h3>
          <ul className="cartes">
            {m.offres.map((o) => (
              <CarteOffre key={`${o.titre}-${o.entreprise}-${o.ville}`} o={o} />
            ))}
          </ul>
        </>
      )}
      {m.formations.length > 0 && (
        <>
          <h3>Formations en apprentissage</h3>
          <p className="douce petite">En apprentissage, la formation ne coûte rien à l'apprenti : l'employeur et son opérateur de compétences la financent.</p>
          <ul className="cartes">
            {m.formations.map((f) => (
              <CarteFormation key={`${f.intitule}-${f.organisme}-${f.ville}`} f={f} />
            ))}
          </ul>
        </>
      )}
      {m.voir_plus && (m.nb_offres > m.offres.length || m.nb_formations > m.formations.length || m.nb_recruteurs > 0) && (
        <p className="petite">
          <a href={m.voir_plus} target="_blank" rel="noopener noreferrer">
            Tout voir sur La bonne alternance
          </a>
          {m.nb_recruteurs > 0 && (
            <span className="douce">
              {" "}
              (dont {m.nb_recruteurs} entreprise{m.nb_recruteurs > 1 ? "s" : ""} qui recrute{m.nb_recruteurs > 1 ? "nt" : ""} des
              alternants sans offre publiée : la candidature spontanée y est possible)
            </span>
          )}
        </p>
      )}
    </details>
  );
}

/* --- Section --------------------------------------------------------------- */

export default function OffresEtFormations({ metiers }: { metiers: string[] }) {
  const [lieu, setLieu] = useState<Lieu | null>(null);
  const [rayon, setRayon] = useState(30);
  const [etat, setEtat] = useState<Etat>("attente");
  const [donnees, setDonnees] = useState<Opportunites | null>(null);
  const [changer, setChanger] = useState(false);
  const derniere = useRef(0);
  const cleMetiers = metiers.join(",");

  useEffect(() => setLieu(lireLieu()), []);

  useEffect(() => {
    if (!lieu || !cleMetiers) return;
    const numero = ++derniere.current; // une réponse en retard ne remplace pas la plus récente
    setEtat("chargement");
    chercherOpportunites(cleMetiers.split(","), lieu.latitude, lieu.longitude, rayon)
      .then((d) => {
        if (numero !== derniere.current) return;
        setDonnees(d);
        setEtat(d.disponible ? "ok" : "erreur");
      })
      .catch(() => numero === derniere.current && setEtat("erreur"));
  }, [lieu, rayon, cleMetiers]);

  function choisir(l: Lieu) {
    setLieu(l);
    retenirLieu(l);
    setChanger(false);
  }

  return (
    <section className="bloc opportunites" aria-busy={etat === "chargement"}>
      <h2>Près de chez toi : offres et formations en alternance</h2>
      {lieu && (
        <p className="lieu-choisi">
          {lieu.nom === "autour de toi" ? "Autour de toi" : `Autour de ${lieu.nom}`}, dans un rayon de{" "}
          <select aria-label="Rayon de recherche" value={rayon} onChange={(e) => setRayon(Number(e.target.value))}>
            {RAYONS.map((r) => (
              <option key={r} value={r}>
                {r} km
              </option>
            ))}
          </select>
          {!changer && (
            <>
              {" · "}
              <button type="button" className="lien" onClick={() => setChanger(true)}>
                changer de ville
              </button>
            </>
          )}
        </p>
      )}
      {(!lieu || changer) && <ChoixLieu lieu={lieu} choisir={choisir} />}

      {etat === "chargement" && <p className="en-cours douce">Recherche des offres et des formations…</p>}
      {etat === "erreur" && (
        <p className="douce">
          {donnees?.metiers.find((m) => m.message)?.message ?? "La recherche ne répond pas pour le moment. Réessaie dans un instant."}
        </p>
      )}
      {etat === "ok" && donnees && (
        <>
          {donnees.metiers.map((m, i) => (
            <BlocMetier key={m.metier_id} m={m} ouvert={i === 0} />
          ))}
          <p className="sources petite douce">
            Sources :{" "}
            {donnees.sources.map((s, i) => (
              <span key={s.nom}>
                {i > 0 && " · "}
                <a href={s.url} target="_blank" rel="noopener noreferrer" title={s.role}>
                  {s.nom}
                </a>
              </span>
            ))}
            . {donnees.classement} Ta ville reste dans ton navigateur, pour la prochaine fois : le site ne la garde pas, et
            ne transmet à La bonne alternance qu'une position arrondie à environ 1 km.
          </p>
        </>
      )}
    </section>
  );
}
