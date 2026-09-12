# Notas de sincronización

- **React no se empaqueta.** `build.mjs` trae un plugin (`react-from-globals`) que
  resuelve `react`, `react-dom` y `react/jsx-runtime` contra `globalThis`. Marcarlos
  como `external` a secas no alcanza: esbuild deja un `require("react")` que en el
  navegador no existe y el bundle muere al cargar.
- **Los ids de degradado se generan con `useId()`.** Dos logos en la misma página
  con ids fijos comparten el degradado y el segundo se pinta mal. No cambiar a ids
  literales.
- **Los `<svg>` llevan `width` y `height` explícitos** más `flex: 0 0 auto`. Un svg
  sin `width` vale `width:100%` y adentro de un flex se aplasta a nada.
- **Los tokens se generan, no se escriben.** `scripts/gen-tokens.mjs` produce
  `src/tokens.css` y `dist/console-root.css` desde `src/tokens.ts`. Si hay que tocar
  un color, se toca `tokens.ts` y se regenera. Los 21 tokens que ya existían en
  `app/web/index.html` están verificados como idénticos.
- **Poppins es sólo de marca.** La aplicación usa la tipografía del sistema. Si
  aparece `[FONT_MISSING]` por Poppins, va por `cfg.runtimeFontPrefixes`, no
  empaquetada: sólo la usa el lockup.

- **El convertidor va contra `dist/index.mjs`, no contra `dist/index.js`.** El
  `.js` es el IIFE para el harness local y no tiene exports: si se lo pasás como
  `--entry`, esbuild lo re-empaqueta y devuelve `undefined`, y los 26 previews
  mueren con `Cannot read properties of undefined (reading '__dsMainNs')`.
  Comando correcto:
  `node .ds-sync/package-build.mjs --config .design-sync/config.json --node-modules ./node_modules --entry ./dist/index.mjs --out ./ds-bundle`
- **`npm run build` tiene que correr antes del convertidor.** Genera los tres
  archivos de `dist/` más los `.d.ts`, de donde salen los contratos de props.
- **La verificación necesita playwright + chromium** en `.ds-sync/`
  (`npm i -D playwright && npx playwright install chromium`). Sin eso la validación
  sale con `[RENDER_SKIPPED]` y el bundle se subiría sin que nadie lo haya visto.

## Riesgos para la próxima sincronización

- `app/web/index.html` es un archivo autocontenido sin build (regla del CLAUDE.md),
  así que este paquete **no lo reemplaza**: son dos representaciones del mismo
  sistema. Lo único que las mantiene juntas es `dist/console-root.css`. Si alguien
  edita el `:root` de la consola a mano, se separan en silencio.
- Los componentes salieron de la pantalla de Productos. Ventas, stock y cuentas
  pendientes todavía pueden necesitar piezas que acá no están.
- Los previews de `.design-sync/previews/` importan de `@mi-optica/ui` y usan la
  API actual. Si cambia una prop, el preview se rompe en la próxima validación;
  eso es lo que se quiere, pero hay que arreglarlo ahí y no en el bundle.
- `Spacer` y `StatGrid` quedaron con tarjeta mínima a propósito: son ayudas de
  maquetado y no tienen nada propio para mostrar.
