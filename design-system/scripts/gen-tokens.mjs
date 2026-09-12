/**
 * Genera el CSS de los tokens desde src/tokens.ts.
 *
 * Salidas:
 *   src/tokens.css            el bloque :root de este paquete
 *   dist/console-root.css     el mismo bloque, para pegar en app/web/index.html
 *
 * Correr después de tocar tokens.ts. Si las dos salidas dejan de coincidir con
 * la consola, la consola está vieja, no al revés.
 */
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";

const src = readFileSync(new URL("../src/tokens.ts", import.meta.url), "utf8");
const body = src.slice(src.indexOf("export const tokens = {") );
const pairs = [...body.matchAll(/^\s*"(--[a-z0-9-]+)":\s*(".*?"|'.*?'),\s*$/gmi)]
  .map(([, k, v]) => [k, v.slice(1, -1)]);

if (pairs.length < 20) {
  console.error(`Sólo encontré ${pairs.length} tokens, algo cambió en el formato de tokens.ts`);
  process.exit(1);
}

const block = pairs.map(([k, v]) => `  ${k}: ${v};`).join("\n");
const head = "/* Generado por scripts/gen-tokens.mjs desde src/tokens.ts. No editar a mano. */";

writeFileSync(new URL("../src/tokens.css", import.meta.url), `${head}\n:root{\n${block}\n}\n`);
mkdirSync(new URL("../dist/", import.meta.url), { recursive: true });
writeFileSync(new URL("../dist/console-root.css", import.meta.url), `${head}\n:root{\n${block}\n}\n`);
console.log(`tokens.css y console-root.css escritos: ${pairs.length} tokens`);
