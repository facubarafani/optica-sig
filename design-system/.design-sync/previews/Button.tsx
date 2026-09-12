import { Button } from "@mi-optica/ui";

const plus = <svg className="mo-ic" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14" /></svg>;
const pencil = <svg className="mo-ic" viewBox="0 0 24 24">
  <path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" /></svg>;

/**
 * Una acción principal por pantalla. El resto va en el estilo por defecto: si
 * todo es azul, nada resalta.
 */
export const Principal = () => (
  <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
    <Button variant="primary" icon={plus}>Nuevo producto</Button>
    <Button>Importar</Button>
    <Button>Exportar</Button>
  </div>
);

/** Destructivo: rojo, pero de contorno. Un rojo lleno es para un saldo, no para un botón. */
export const Destructivo = () => (
  <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
    <Button variant="danger">Dar de baja</Button>
    <Button variant="ghost">Cancelar</Button>
  </div>
);

/** Chicos, para las acciones de una fila de tabla. El de ícono necesita `title`. */
export const EnUnaFila = () => (
  <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
    <Button small>Abrir</Button>
    <Button small iconOnly title="Editar">{pencil}</Button>
  </div>
);

/** Deshabilitado: se atenúa, no desaparece. */
export const Deshabilitado = () => (
  <div style={{ display: "flex", gap: 10 }}>
    <Button variant="primary" disabled>Confirmar venta</Button>
    <Button disabled>Exportar</Button>
  </div>
);
