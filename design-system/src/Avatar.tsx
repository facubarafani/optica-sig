import { useId } from "react";

/**
 * Avatares.
 *
 * Dos modos, porque son dos usos distintos:
 *
 * - **Iniciales** (`name`): para usuarios reales del sistema. El color sale del
 *   nombre, así que la misma persona tiene siempre el mismo, sin guardar nada.
 * - **Personaje** (`character`): un elenco chico y dibujado, para tutoriales,
 *   onboarding y capturas de la documentación.
 *
 * Todos los personajes usan anteojos: es una óptica, y el aro es la misma
 * geometría del isotipo. Es lo que los ata a la marca en vez de dejarlos como
 * ilustración genérica. Los aros van en los colores de marca (cian a violeta) y
 * nunca en rojo ni verde, que adentro del sistema significan otra cosa.
 */

const SKIN = ["#F2C9A0", "#E0A87C", "#C68B63", "#A26B45", "#8A5433", "#F7D9BE"] as const;
const HAIR = ["#2B2118", "#4A3728", "#7A4B28", "#171514", "#8C8C8C", "#D9C08A"] as const;
const WEAR = ["#2563eb", "#0f172a", "#4f46e5", "#0e7490", "#334155", "#7c3aed"] as const;
const RIMS = ["#22d3ee", "#3b82f6", "#7c3aed", "#0f172a", "#4f46e5", "#38bdf8"] as const;
const TINT = ["#e8f6fb", "#eef2fe", "#f3eefe", "#eef4ff", "#e9f5f6", "#f0f0f4"] as const;

/** Los seis personajes. El orden es estable: `character={2}` es siempre el mismo. */
const CAST = [
  { skin: 0, hair: 0, wear: 0, rim: 1, tint: 1, style: "bob" },
  { skin: 2, hair: 3, wear: 1, rim: 0, tint: 0, style: "corto" },
  { skin: 4, hair: 1, wear: 2, rim: 2, tint: 2, style: "rodete" },
  { skin: 1, hair: 5, wear: 3, rim: 5, tint: 4, style: "corto" },
  { skin: 3, hair: 0, wear: 4, rim: 3, tint: 5, style: "rulos" },
  { skin: 5, hair: 4, wear: 5, rim: 4, tint: 3, style: "bob" },
] as const;

export interface AvatarProps {
  /** Nombre de la persona. Sin `character`, dibuja las iniciales. */
  name?: string;
  /** 1 a 6. Elige un personaje del elenco. */
  character?: number;
  /** Lado en px. Abajo de 28 conviene usar iniciales: los anteojos se pierden. */
  size?: number;
  className?: string;
}

/** Mismo nombre, mismo color, sin guardar nada en ningún lado. */
function hashOf(s: string) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return h;
}

function initialsOf(name: string) {
  return name.trim().split(/\s+/).slice(0, 2).map(w => w[0] ?? "").join("").toUpperCase() || "?";
}

/* El pelo va en dos capas: una atrás de la cara (las mechas que se ven a los
   costados y arriba) y otra adelante (el flequillo). En una sola capa el peinado
   queda como una vincha y la coronilla se ve pelada. */
function hairBack(style: string, c: string) {
  if (style === "bob")    return <path d="M13 46V29a19 19 0 0 1 38 0v17z" fill={c} />;
  if (style === "rodete") return <>
    <circle cx="32" cy="8" r="6" fill={c} />
    <path d="M15 34V29a17 17 0 0 1 34 0v5z" fill={c} />
  </>;
  if (style === "rulos")  return <path d="M13 40V30c0-11 8-18 19-18s19 7 19 18v10c-2-4-3-6-5-7
    1-8-5-12-14-12s-15 4-14 12c-2 1-3 3-5 7z" fill={c} />;
  return <path d="M15 33V29a17 17 0 0 1 34 0v4z" fill={c} />;   // corto
}

function hairFront(style: string, c: string) {
  if (style === "bob")
    return <path d="M18 29c0-8 6-13 14-13s14 5 14 13c-2-6-7-9-14-9s-12 3-14 9z" fill={c} />;
  if (style === "corto")
    return <path d="M18 28c0-8 6-12 14-12s14 4 14 12c-1-4-4-6-7-6-4 0-4 2-7 2s-3-2-7-2c-3 0-6 2-7 6z" fill={c} />;
  if (style === "rodete")
    return <path d="M18 28c0-8 6-12 14-12s14 4 14 12c-2-5-7-8-14-8s-12 3-14 8z" fill={c} />;
  // rulos
  return <path d="M18 28c0-8 6-12 14-12s14 4 14 12c-1-3-3-4-5-4-2 0-3 1-4 1-2 0-2-2-5-2s-3 2-5 2
    c-1 0-2-1-4-1-2 0-4 1-5 4z" fill={c} />;
}

/** Un personaje del elenco, o las iniciales si no se pide ninguno. */
export function Avatar({ name, character, size = 40, className }: AvatarProps) {
  const uid = useId().replace(/:/g, "");

  if (!character) {
    const n = name ?? "";
    const i = hashOf(n) % TINT.length;
    return (
      <div
        className={className}
        style={{
          width: size, height: size, borderRadius: "50%", flex: "0 0 auto",
          background: TINT[i], color: WEAR[i],
          display: "grid", placeItems: "center",
          fontWeight: 700, fontSize: Math.max(size * 0.38, 9),
          fontFamily: "var(--sans)", letterSpacing: ".01em", userSelect: "none",
        }}
        title={name}
      >
        {initialsOf(n)}
      </div>
    );
  }

  const c = CAST[(character - 1) % CAST.length];
  const skin = SKIN[c.skin], rim = RIMS[c.rim];
  return (
    <svg viewBox="0 0 64 64" width={size} height={size} className={className}
         style={{ flex: "0 0 auto", borderRadius: "50%", display: "block" }}
         role="img" aria-label={name ?? `Persona ${character}`}>
      <defs>
        <clipPath id={`${uid}-c`}><circle cx="32" cy="32" r="32" /></clipPath>
      </defs>
      <g clipPath={`url(#${uid}-c)`}>
        <rect width="64" height="64" fill={TINT[c.tint]} />
        {hairBack(c.style, HAIR[c.hair])}
        {/* hombros y cuello */}
        <path d="M4 64c0-12 12-18 28-18s28 6 28 18z" fill={WEAR[c.wear]} />
        <path d="M27 38h10v9c0 2-10 2-10 0z" fill={skin} />
        <path d="M27 42c3 2 7 2 10 0v-4H27z" fill="rgba(0,0,0,.10)" />
        {/* orejas y cabeza */}
        <circle cx="18" cy="30" r="3.2" fill={skin} />
        <circle cx="46" cy="30" r="3.2" fill={skin} />
        <path d="M18 28a14 14 0 0 1 28 0v3a14 14 0 0 1-28 0z" fill={skin} />
        {hairFront(c.style, HAIR[c.hair])}
        {/* Los ojos van detrás de los cristales: sin ellos los aros se leen como
            antiparras y no como una persona con anteojos. */}
        <circle cx="26.6" cy="29.4" r="1.5" fill="#1f2937" />
        <circle cx="37.4" cy="29.4" r="1.5" fill="#1f2937" />
        <path d="M29 37.6c1.9 1.5 4.1 1.5 6 0" fill="none" stroke="rgba(31,41,55,.55)"
              strokeWidth="1.6" strokeLinecap="round" />
        {/* anteojos: el mismo aro del isotipo, en los colores de marca */}
        <g fill="none" stroke={rim} strokeWidth="1.9">
          <circle cx="26" cy="29" r="5.2" />
          <circle cx="38" cy="29" r="5.2" />
          <path d="M31.2 29h1.6" />
          <path d="M20.8 29c-1.3 0-2.1.4-2.7 1" />
          <path d="M43.2 29c1.3 0 2.1.4 2.7 1" />
        </g>
      </g>
    </svg>
  );
}

/** Varios apilados, para mostrar un equipo sin ocupar lugar. */
export function AvatarGroup({ children, size = 32 }: { children: React.ReactNode; size?: number }) {
  return (
    <div style={{ display: "inline-flex", alignItems: "center" }}>
      {Array.isArray(children)
        ? children.map((ch, i) => (
            <div key={i} style={{ marginLeft: i ? -size * 0.28 : 0,
                                  borderRadius: "50%", boxShadow: "0 0 0 2px var(--panel)" }}>{ch}</div>
          ))
        : children}
    </div>
  );
}
