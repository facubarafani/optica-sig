import { Switch } from "@mi-optica/ui";

/** Nada se borra, se desactiva. Este interruptor es cómo se ve lo desactivado. */
export const VerInactivos = () => (
  <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
    <Switch label="Ver inactivos" />
    <Switch label="Incluir otras sucursales" defaultChecked />
  </div>
);
