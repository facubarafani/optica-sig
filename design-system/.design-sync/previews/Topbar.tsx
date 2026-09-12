import { Topbar } from "@mi-optica/ui";

/** Con usuario: la miga a la izquierda, quién está adentro a la derecha. */
export const ConUsuario = () => (
  <div style={{ border: "1px solid var(--border)", borderRadius: 9, overflow: "hidden" }}>
    <Topbar crumb="Productos" user={{ name: "Martina Rossi", initials: "MR" }} />
  </div>
);

/** Sin usuario. */
export const Simple = () => (
  <div style={{ border: "1px solid var(--border)", borderRadius: 9, overflow: "hidden" }}>
    <Topbar crumb="Cuentas pendientes" />
  </div>
);
