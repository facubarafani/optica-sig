import { AppShell, Sidebar, NavItem, Topbar, PageHead, Button, Badge } from "@mi-optica/ui";

const ic = (d: string) => (
  <svg className="mo-ic mo-ic--lg" viewBox="0 0 24 24"><path d={d} /></svg>
);

/**
 * El marco entero: casco oscuro a la izquierda, barra de arriba y área de
 * trabajo. Sin tope de ancho: las grillas de datos necesitan la ventana entera.
 */
export const Marco = () => (
  <div style={{ height: 420, overflow: "hidden", border: "1px solid var(--border)",
                borderRadius: 10 }}>
    <AppShell
      sidebar={
        <Sidebar company="Óptica Belgrano" footer="Sucursal: Belgrano">
          <NavItem label="Inicio" icon={ic("M3 3h7v9H3zM14 3h7v5h-7zM14 12h7v9h-7zM3 16h7v5H3z")} />
          <NavItem label="Productos" active icon={ic("m21 16V8l-9-5-9 5v8l9 5z")} />
          <NavItem label="Ventas" icon={ic("M4 2v20l2.5-1.6L9 22l2.5-1.6L14 22l2.5-1.6L19 22V2z")} />
          <NavItem label="Cuentas pendientes" icon={ic("M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18M12 7v5l3 2")} />
        </Sidebar>
      }
      topbar={<Topbar crumb="Productos" user={{ name: "Martina Rossi", initials: "MR" }} />}
    >
      <PageHead
        title="Productos"
        sub="1.284 activos · 212 estilos con variantes"
        actions={<Button variant="primary">Nuevo producto</Button>}
      />
      <div style={{ display: "flex", gap: 8 }}>
        <Badge tone="green">Activo</Badge>
        <Badge tone="gray">A3</Badge>
      </div>
    </AppShell>
  </div>
);
