import { useId } from "react";

/**
 * La marca. La geometría es la misma que la de `design/marca/*.svg` y la del
 * manual: anillo con la apertura a 18 grados y el haz saliendo por ahí.
 *
 * Los degradados llevan ids únicos por instancia (useId). Sin eso, dos logos en
 * la misma página comparten el id y el segundo se pinta con el degradado del
 * primero, que es un error que no se ve hasta que hay dos.
 */

export interface LogoProps {
  /** Alto en px. El ancho sale de la proporción. */
  size?: number;
  className?: string;
}

/** Anillo con haz. Para cuando el logo va suelto y tiene aire. */
export function LogoSymbol({ size = 40, className }: LogoProps) {
  const uid = useId().replace(/:/g, "");
  return (
    <svg viewBox="8 8 118 100" width={size * 1.1800} height={size}
         style={{ flex: "0 0 auto" }} className={className}
         role="img" aria-label="Mi Óptica Digital">
      <defs><linearGradient id={`${uid}-h0`} gradientUnits="userSpaceOnUse" x1="79.14" y1="67.51" x2="35.26" y2="80.64"><stop offset="0" stopColor="#22D3EE" /><stop offset="1" stopColor="#38BDF8" /></linearGradient><linearGradient id={`${uid}-h1`} gradientUnits="userSpaceOnUse" x1="36.55" y1="81.23" x2="17.89" y2="38.82"><stop offset="0" stopColor="#38BDF8" /><stop offset="1" stopColor="#3B82F6" /></linearGradient><linearGradient id={`${uid}-h2`} gradientUnits="userSpaceOnUse" x1="17.45" y1="40.17" x2="57.47" y2="16.83"><stop offset="0" stopColor="#3B82F6" /><stop offset="1" stopColor="#4F46E5" /></linearGradient><linearGradient id={`${uid}-h3`} gradientUnits="userSpaceOnUse" x1="56.08" y1="16.55" x2="83.87" y2="52.96"><stop offset="0" stopColor="#4F46E5" /><stop offset="1" stopColor="#7C3AED" /></linearGradient><linearGradient id={`${uid}-hs0`} gradientUnits="userSpaceOnUse" x1="88.0" y1="62.4" x2="147.0" y2="81.5"><stop offset="0" stopColor="#22D3EE" stopOpacity=".95" /><stop offset="1" stopColor="#22D3EE" stopOpacity="0" /></linearGradient><linearGradient id={`${uid}-hs1`} gradientUnits="userSpaceOnUse" x1="88.0" y1="62.4" x2="147.0" y2="81.5"><stop offset="0" stopColor="#38BDF8" stopOpacity=".95" /><stop offset="1" stopColor="#38BDF8" stopOpacity="0" /></linearGradient><linearGradient id={`${uid}-hs2`} gradientUnits="userSpaceOnUse" x1="88.0" y1="62.4" x2="147.0" y2="81.5"><stop offset="0" stopColor="#3B82F6" stopOpacity=".95" /><stop offset="1" stopColor="#3B82F6" stopOpacity="0" /></linearGradient><linearGradient id={`${uid}-hs3`} gradientUnits="userSpaceOnUse" x1="88.0" y1="62.4" x2="147.0" y2="81.5"><stop offset="0" stopColor="#4F46E5" stopOpacity=".95" /><stop offset="1" stopColor="#4F46E5" stopOpacity="0" /></linearGradient><linearGradient id={`${uid}-hs4`} gradientUnits="userSpaceOnUse" x1="88.0" y1="62.4" x2="147.0" y2="81.5"><stop offset="0" stopColor="#7C3AED" stopOpacity=".95" /><stop offset="1" stopColor="#7C3AED" stopOpacity="0" /></linearGradient></defs><polygon points="88.0,62.4 152.3,65.4 150.2,71.8" fill={`url(#${uid}-hs0)`} /><polygon points="88.0,62.4 150.2,71.8 148.1,78.3" fill={`url(#${uid}-hs1)`} /><polygon points="88.0,62.4 148.1,78.3 146.0,84.8" fill={`url(#${uid}-hs2)`} /><polygon points="88.0,62.4 146.0,84.8 143.9,91.2" fill={`url(#${uid}-hs3)`} /><polygon points="88.0,62.4 143.9,91.2 141.8,97.7" fill={`url(#${uid}-hs4)`} /><path d="M 79.14 67.51 A 34.0 34.0 0 0 1 35.26 80.64" fill="none" stroke={`url(#${uid}-h0)`} strokeWidth="12" strokeLinecap="butt" /><path d="M 36.55 81.23 A 34.0 34.0 0 0 1 17.89 38.82" fill="none" stroke={`url(#${uid}-h1)`} strokeWidth="12" strokeLinecap="butt" /><path d="M 17.45 40.17 A 34.0 34.0 0 0 1 57.47 16.83" fill="none" stroke={`url(#${uid}-h2)`} strokeWidth="12" strokeLinecap="butt" /><path d="M 56.08 16.55 A 34.0 34.0 0 0 1 83.87 52.96" fill="none" stroke={`url(#${uid}-h3)`} strokeWidth="12" strokeLinecap="butt" />
    </svg>
  );
}

/** Sólo el anillo. Para huecos cuadrados: ícono, favicon, barra lateral. */
export function LogoMark({ size = 30, className }: LogoProps) {
  const uid = useId().replace(/:/g, "");
  return (
    <svg viewBox="8 8 84 84" width={size} height={size}
         style={{ flex: "0 0 auto" }} className={className}
         role="img" aria-label="Mi Óptica Digital">
      <defs><linearGradient id={`${uid}-h0`} gradientUnits="userSpaceOnUse" x1="79.14" y1="67.51" x2="35.26" y2="80.64"><stop offset="0" stopColor="#22D3EE" /><stop offset="1" stopColor="#38BDF8" /></linearGradient><linearGradient id={`${uid}-h1`} gradientUnits="userSpaceOnUse" x1="36.55" y1="81.23" x2="17.89" y2="38.82"><stop offset="0" stopColor="#38BDF8" /><stop offset="1" stopColor="#3B82F6" /></linearGradient><linearGradient id={`${uid}-h2`} gradientUnits="userSpaceOnUse" x1="17.45" y1="40.17" x2="57.47" y2="16.83"><stop offset="0" stopColor="#3B82F6" /><stop offset="1" stopColor="#4F46E5" /></linearGradient><linearGradient id={`${uid}-h3`} gradientUnits="userSpaceOnUse" x1="56.08" y1="16.55" x2="83.87" y2="52.96"><stop offset="0" stopColor="#4F46E5" /><stop offset="1" stopColor="#7C3AED" /></linearGradient></defs><path d="M 79.14 67.51 A 34.0 34.0 0 0 1 35.26 80.64" fill="none" stroke={`url(#${uid}-h0)`} strokeWidth="12" strokeLinecap="butt" /><path d="M 36.55 81.23 A 34.0 34.0 0 0 1 17.89 38.82" fill="none" stroke={`url(#${uid}-h1)`} strokeWidth="12" strokeLinecap="butt" /><path d="M 17.45 40.17 A 34.0 34.0 0 0 1 57.47 16.83" fill="none" stroke={`url(#${uid}-h2)`} strokeWidth="12" strokeLinecap="butt" /><path d="M 56.08 16.55 A 34.0 34.0 0 0 1 83.87 52.96" fill="none" stroke={`url(#${uid}-h3)`} strokeWidth="12" strokeLinecap="butt" />
    </svg>
  );
}

export interface LockupProps {
  /** Tamaño del nombre en px. Todo lo demás se calcula a partir de esto. */
  size?: number;
  /** Sobre fondo oscuro el nombre va en blanco. */
  dark?: boolean;
  /** Una sola tinta, para impresión sin degradado. */
  flat?: boolean;
  className?: string;
}

/**
 * Lockup completo: símbolo, nombre y DIGITAL con el espectro en las letras.
 * El degradado va como relleno de un `<text>` en SVG y no como fondo recortado,
 * porque al imprimir el recorte deja una línea suelta.
 */
export function Lockup({ size = 40, dark = false, flat = false, className }: LockupProps) {
  const uid = useId().replace(/:/g, "");
  const s = size * 0.17;
  const w = 7.05 * s, h = 1.35 * s;
  return (
    <div className={["mo-lockup", className].filter(Boolean).join(" ")} style={{ gap: size * 0.08 }}>
      <LogoSymbol size={size * 1.05} />
      <div className="mo-words">
        <div className="mo-name" style={{ fontSize: size, color: dark ? "#fff" : "var(--ink)" }}>
          Mi Óptica
        </div>
        <div style={{ height: size * 0.21 }} />
        <svg viewBox={`0 0 ${w} ${h}`} style={{ width: w, height: h, display: "block", flex: "0 0 auto" }}
             role="img" aria-label="DIGITAL">
          {!flat && (
            <defs>
              <linearGradient id={`${uid}-d`} x1="0" y1="0" x2="1" y2="0">
                <stop offset="0" stopColor="var(--brand-cyan)" />
                <stop offset=".5" stopColor="var(--brand-blue)" />
                <stop offset="1" stopColor="var(--brand-violet)" />
              </linearGradient>
            </defs>
          )}
          <text x="0" y={h * 0.78} fontFamily="var(--brand-font)" fontSize={s} fontWeight={400}
                letterSpacing={s * 0.34} fill={flat ? "#64748b" : `url(#${uid}-d)`}>
            DIGITAL
          </text>
        </svg>
      </div>
    </div>
  );
}
