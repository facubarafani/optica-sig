import * as esbuild from "esbuild";

/**
 * React no se empaqueta: lo provee el runtime que hospeda los componentes
 * (Claude Design lo sirve desde _vendor/). Marcarlo como `external` a secas no
 * alcanza, porque esbuild deja un `require("react")` que en el navegador no
 * existe. Este plugin lo resuelve contra el global.
 */
const fromGlobals = {
  name: "react-from-globals",
  setup(build) {
    const filter = /^(react|react-dom|react-dom\/client|react\/jsx-runtime|react\/jsx-dev-runtime)$/;
    build.onResolve({ filter }, (args) => ({ path: args.path, namespace: "globals" }));
    build.onLoad({ filter: /.*/, namespace: "globals" }, (args) => {
      if (args.path === "react") {
        return { contents: "module.exports = globalThis.React;", loader: "js" };
      }
      if (args.path.startsWith("react-dom")) {
        return { contents: "module.exports = globalThis.ReactDOMClient || globalThis.ReactDOM;", loader: "js" };
      }
      // El runtime automático de JSX sobre createElement. `key` viaja aparte.
      return {
        contents: `
          const R = globalThis.React;
          const h = (type, props, key) =>
            R.createElement(type, key === undefined ? props : Object.assign({}, props, { key }));
          module.exports = { Fragment: R.Fragment, jsx: h, jsxs: h, jsxDEV: h };
        `,
        loader: "js",
      };
    });
  },
};

await esbuild.build({
  entryPoints: ["src/index.ts"],
  bundle: true,
  format: "iife",
  globalName: "MiOpticaUI",
  outfile: "dist/index.js",
  jsx: "automatic",
  target: ["es2020"],
  plugins: [fromGlobals],
  loader: { ".css": "empty" },   // el CSS sale por su propio bundle
  logLevel: "info",
});


/**
 * Entrada ESM del paquete: es la que consume el convertidor de design-sync, que
 * necesita exports de verdad para poder re-empaquetar y leer los tipos. Acá React
 * sí va como `external` a secas: la salida es ESM y el que la empaqueta después
 * resuelve el import.
 */
await esbuild.build({
  entryPoints: ["src/index.ts"],
  bundle: true,
  format: "esm",
  outfile: "dist/index.mjs",
  jsx: "automatic",
  target: ["es2020"],
  external: ["react", "react-dom", "react/jsx-runtime"],
  loader: { ".css": "empty" },
  logLevel: "info",
});

await esbuild.build({
  entryPoints: ["src/styles.css"],
  bundle: true,
  outfile: "dist/index.css",
  logLevel: "info",
});
