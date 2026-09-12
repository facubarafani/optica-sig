/**
 * Fuente única de los tokens.
 *
 * Los valores están copiados de `app/web/index.html` sin redondear: la consola
 * es el sistema real y este paquete la describe, no al revés. Los que empiezan
 * con `brand` son nuevos y salen del manual de marca.
 *
 * `scripts/gen-tokens.mjs` genera desde acá tanto `tokens.css` (para este
 * paquete) como el bloque `:root` de la consola, así no hay dos copias que se
 * puedan separar con el tiempo.
 */

/** Nombre de la variable CSS -> valor. El nombre es el contrato. */
export const tokens = {
  // --- superficies y texto (idénticos a la consola) ---
  "--bg": "#f4f6f9",
  "--panel": "#ffffff",
  "--border": "#e3e8ef",
  "--text": "#1f2937",
  "--muted": "#6b7280",
  /** El casco: barra lateral y panel de ingreso. */
  "--ink": "#0f172a",

  // --- acción ---
  "--primary": "#2563eb",
  "--primary-600": "#1d4ed8",
  "--primary-50": "#eff6ff",

  // --- estado. Rojo y verde significan algo: deuda/cobrado, agotado/en stock.
  //     Por eso la marca no los usa (ver el manual, 03 Color).
  "--danger": "#dc2626",
  "--danger-50": "#fef2f2",
  "--ok": "#16a34a",
  "--ok-50": "#f0fdf4",
  "--warn": "#d97706",
  "--warn-50": "#fffbeb",

  // --- marca. Sólo para el logo y piezas de marca, nunca para estado. ---
  "--brand-cyan": "#22d3ee",
  "--brand-sky": "#38bdf8",
  "--brand-blue": "#3b82f6",
  "--brand-indigo": "#4f46e5",
  "--brand-violet": "#7c3aed",

  // --- forma ---
  "--radius": "10px",
  "--radius-sm": "7px",
  "--radius-lg": "14px",
  "--shadow": "0 1px 3px rgba(16,24,40,.08),0 1px 2px rgba(16,24,40,.04)",
  "--shadow-lg": "0 12px 32px rgba(16,24,40,.18)",

  // --- medidas del marco ---
  "--sidebar": "228px",
  "--topbar": "56px",

  // --- tipografía ---
  "--sans": '-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif',
  "--mono": "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace",
  /** Sólo marca. Nunca dentro de una tabla (ver el manual, 04 Tipografía). */
  "--brand-font": "'Poppins',-apple-system,BlinkMacSystemFont,sans-serif",
} as const;

export type TokenName = keyof typeof tokens;

/** Para leer un token desde TS sin escribir el string a mano. */
export const t = (name: TokenName): string => `var(${name})`;

/** Los cinco colores de la marca, en el orden en que se dispersan. */
export const spectrum = [
  tokens["--brand-cyan"],
  tokens["--brand-sky"],
  tokens["--brand-blue"],
  tokens["--brand-indigo"],
  tokens["--brand-violet"],
] as const;
