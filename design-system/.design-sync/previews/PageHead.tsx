import { PageHead, Button } from "@mi-optica/ui";

const plus = <svg className="mo-ic" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14" /></svg>;

/** Encabezado de pantalla: título, el conteo debajo y las acciones a la derecha. */
export const ConAcciones = () => (
  <PageHead
    title="Productos"
    sub="1.284 activos · 212 estilos con variantes · actualizado 14:02"
    actions={<>
      <Button>Importar</Button>
      <Button>Exportar</Button>
      <Button variant="primary" icon={plus}>Nuevo producto</Button>
    </>}
  />
);

/** Sin acciones, para una pantalla de sólo lectura. */
export const Simple = () => (
  <PageHead title="Cuentas pendientes" sub="31 ventas con saldo · 2.184.900,00 ARS" />
);
