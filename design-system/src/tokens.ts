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
  /** La etiqueta de un campo. Un punto más oscura que --muted y un punto más
   *  clara que --text: tiene que leerse como nombre del campo, no como dato. */
  "--label": "#374151",

  // --- texto sobre el casco. Las neutras de arriba están pensadas contra
  //     blanco: --text sobre #0f172a no se lee. Estas cuatro son la escala
  //     equivalente del lado oscuro, y las usan la barra lateral y las
  //     pantallas de acceso.
  /** Cuerpo: un ítem del menú, un párrafo del panel. */
  "--on-ink": "#cbd5e1",
  /** Secundario: el pie de la barra, la bajada del panel. */
  "--on-ink-muted": "#94a3b8",
  /** El descriptor del lockup y el subtítulo de la marca. */
  "--on-ink-faint": "#7c8aa5",
  /** Lo más callado: la ayuda al pie del panel de ingreso. */
  "--on-ink-dim": "#64748b",
  /** Separador sobre el casco. */
  "--on-ink-line": "#1e293b",

  // --- superficies de interacción. Son los dos tintes que el botón tenía
  //     escritos a mano; ahora los nombra el sistema, así la consola de
  //     plataforma pasa a violeta pisando estos dos y nada más.
  /** Pasar el mouse por encima. */
  "--hover": "#f8fafc",
  /** Apretado, y el hover de un botón sin borde: sin borde, el tinte es lo
   *  único que lo señala, así que necesita el fuerte. */
  "--press": "#f1f5f9",

  // --- acción. El botón principal se pinta con la marca: índigo en reposo y
  //     el tramo azul a violeta cuando se lo toca. El espectro pinta lo que
  //     avanza: este botón y el camino recorrido en un asistente (manual,
  //     03 Color). Lo demás sigue en --primary: los enlaces, el foco de un
  //     campo y las chapas informativas. Nunca un estado.
  /** Reposo del botón principal. */
  "--action": "#4f46e5",
  /** Su borde. */
  "--action-600": "#4338ca",
  /** El destello: aparece al pasar por encima y al apretar, no en reposo.
   *  Es un degradado, no un color, así que no tiene hex: para un mail o un
   *  ticket se usa --action. */
  "--action-bloom": "linear-gradient(100deg, #3b82f6, #7c3aed)",
  /** El mismo tramo al 78%, para el apretado. */
  "--action-bloom-press": "linear-gradient(100deg, #2e65c0, #612db9)",
  /** Un degradado no sirve de borde: este es el violeta del extremo. */
  "--action-bloom-border": "#6f34d4",
  /** Anillo de foco del botón principal. El resto del sistema usa --primary-50. */
  "--action-ring": "#ede9fe",

  // --- acción del sistema: enlaces, foco de los campos, chapas informativas ---
  "--primary": "#2563eb",
  "--primary-600": "#1d4ed8",
  /** Contorno de una fila elegible al pasar por encima, como --danger-200. */
  "--primary-200": "#bfdbfe",
  /** Apretado. El manual (03 Color) lista los dos de arriba; este cierra la
   *  rampa para que un botón lleno tenga estado apretado. */
  "--primary-700": "#1e40af",
  "--primary-50": "#eff6ff",

  // --- estado. Rojo y verde significan algo: deuda/cobrado, agotado/en stock.
  //     Por eso la marca no los usa (ver el manual, 03 Color).
  "--danger": "#dc2626",
  /** Contorno del botón destructivo: rojo, pero apenas. Un rojo lleno es un
   *  saldo, no un botón. */
  "--danger-200": "#fecaca",
  "--danger-50": "#fef2f2",
  "--ok": "#16a34a",
  "--ok-50": "#f0fdf4",
  "--warn": "#d97706",
  "--warn-50": "#fffbeb",

  // --- marca. El logo, las piezas de marca y el botón principal (arriba).
  //     Nunca para estado: el espectro se corta antes del rojo y del verde
  //     justamente para no competir con ellos. ---
  "--brand-cyan": "#22d3ee",
  "--brand-sky": "#38bdf8",
  "--brand-blue": "#3b82f6",
  "--brand-indigo": "#4f46e5",
  "--brand-violet": "#7c3aed",

  // --- forma ---
  "--radius": "10px",
  "--radius-sm": "7px",
  /** Campos de texto. Subió de 8 a 12 px cuando el botón pasó a cápsula: con
   *  el campo en 8 px las dos formas chocaban y el botón se leía corrido.
   *  A 12 el campo deja de ser una caja y la cápsula sigue siendo lo único
   *  redondo del todo, que es lo que la hace encontrable. */
  "--radius-control": "12px",
  /** Botones. La cápsula los separa del campo y de la celda, que son las
   *  otras dos cajas de la pantalla. */
  "--radius-pill": "999px",
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
