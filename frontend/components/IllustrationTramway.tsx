// Illustration du dilemme du tramway (dessin original, aux couleurs du site).

function Personne({ x, y }: { x: number; y: number }) {
  // Une silhouette allongée en travers de la voie.
  return (
    <g>
      <circle cx={x} cy={y - 22} r={6} fill="var(--encre)" />
      <line x1={x} y1={y - 15} x2={x} y2={y + 16} stroke="var(--encre)" strokeWidth={3} strokeLinecap="round" />
      <line x1={x - 7} y1={y - 6} x2={x + 7} y2={y - 6} stroke="var(--encre)" strokeWidth={2.5} strokeLinecap="round" />
    </g>
  );
}

function Traverses({ debut, fin, y }: { debut: number; fin: number; y: number }) {
  const xs = [];
  for (let x = debut; x <= fin; x += 22) xs.push(x);
  return (
    <>
      {xs.map((x) => (
        <line key={x} x1={x} y1={y - 9} x2={x} y2={y + 9} stroke="var(--trait)" strokeWidth={3} />
      ))}
    </>
  );
}

export default function IllustrationTramway() {
  const rail = { stroke: "var(--encre-douce)", strokeWidth: 2, fill: "none" } as const;
  return (
    <figure className="illustration">
      <svg viewBox="0 60 640 195" role="img" aria-labelledby="titre-tramway">
        <title id="titre-tramway">
          Un tramway fonce vers cinq personnes attachées sur la voie. Un aiguillage permet de le dévier vers une voie
          où se trouve une seule personne.
        </title>

        {/* Voies */}
        <Traverses debut={30} fin={620} y={150} />
        <Traverses debut={420} fin={620} y={225} />
        <path d="M20 146 H630" {...rail} />
        <path d="M20 154 H630" {...rail} />
        <path d="M290 146 C350 146 370 221 430 221 H630" {...rail} />
        <path d="M290 154 C345 154 365 229 430 229 H630" {...rail} />

        {/* Tramway */}
        <g>
          <rect x={40} y={92} width={120} height={48} rx={7} fill="var(--encre)" />
          <rect x={52} y={102} width={22} height={16} rx={2} fill="var(--papier)" />
          <rect x={82} y={102} width={22} height={16} rx={2} fill="var(--papier)" />
          <rect x={112} y={102} width={22} height={16} rx={2} fill="var(--papier)" />
          <rect x={146} y={104} width={10} height={24} rx={2} fill="var(--papier)" />
          <line x1={100} y1={92} x2={100} y2={72} stroke="var(--encre)" strokeWidth={2} />
          <line x1={84} y1={72} x2={116} y2={72} stroke="var(--encre)" strokeWidth={2} />
          {/* traits de vitesse */}
          <line x1={8} y1={104} x2={30} y2={104} stroke="var(--encre-douce)" strokeWidth={2} strokeLinecap="round" />
          <line x1={14} y1={118} x2={32} y2={118} stroke="var(--encre-douce)" strokeWidth={2} strokeLinecap="round" />
        </g>

        {/* Aiguillage : le levier, seul élément en vert-de-gris */}
        <g>
          <rect x={262} y={196} width={30} height={8} rx={2} fill="var(--encre)" />
          <line x1={277} y1={198} x2={296} y2={170} stroke="var(--vert-de-gris)" strokeWidth={4} strokeLinecap="round" />
          <circle cx={297} cy={168} r={6} fill="var(--vert-de-gris)" />
        </g>

        {/* Cinq personnes sur la voie principale, une sur la voie de côté */}
        {[460, 492, 524, 556, 588].map((x) => (
          <Personne key={x} x={x} y={150} />
        ))}
        <Personne x={540} y={225} />
      </svg>
    </figure>
  );
}
