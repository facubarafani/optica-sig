import { NavItem } from "@mi-optica/ui";

const ic = (d: string) => <svg className="mo-ic mo-ic--lg" viewBox="0 0 24 24"><path d={d} /></svg>;

/** Los ítems viven sobre el casco oscuro: fuera de él no se leen. */
export const EnElCasco = () => (
  <div style={{ background: "var(--ink)", padding: 8, borderRadius: 9, width: 228 }}>
    <div className="mo-side"><nav className="mo-nav">
      <NavItem label="Inicio" icon={ic("M3 3h7v9H3zM14 3h7v5h-7zM14 12h7v9h-7zM3 16h7v5H3z")} />
      <NavItem label="Productos" active icon={ic("m21 16V8l-9-5-9 5v8l9 5z")} />
      <NavItem label="Ventas" icon={ic("M4 2v20l2.5-1.6L9 22l2.5-1.6L14 22l2.5-1.6L19 22V2z")} />
      <NavItem label="Clientes" icon={ic("M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M13 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0")} />
    </nav></div>
  </div>
);
