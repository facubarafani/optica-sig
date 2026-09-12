import { Stat, StatGrid } from "@mi-optica/ui";

/** Las cifras del inicio, con datos de una óptica de verdad. */
export const Inicio = () => (
  <StatGrid>
    <Stat label="Productos activos" value="1.284" />
    <Stat label="Cuentas pendientes" value="31" />
    <Stat label="Vendido hoy" value="306.384,50" unit="ARS" />
    <Stat label="Stock bajo mínimo" value="9" />
  </StatGrid>
);

/** Una sola, para cuando no hay grilla. */
export const Suelta = () => <Stat label="Saldo del día" value="156.384,50" unit="ARS" />;
