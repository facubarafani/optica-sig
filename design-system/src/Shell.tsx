import type { ReactNode } from "react";
import { LogoMark } from "./Logo";

/**
 * El marco de la aplicación: barra lateral oscura fija más el área de trabajo.
 * No hay tope de ancho a propósito: las grillas de datos necesitan la ventana
 * entera. Las pantallas de lectura (una ficha, un formulario) se limitan ellas.
 */

export interface NavItemProps {
  label: string;
  icon?: ReactNode;
  active?: boolean;
  onClick?: () => void;
}

export function NavItem({ label, icon, active, onClick }: NavItemProps) {
  return (
    <a className={active ? "mo-on" : undefined} onClick={onClick}>
      {icon}
      {label}
    </a>
  );
}

export interface SidebarProps {
  /** Nombre de la óptica, debajo de la marca. */
  company?: string;
  /** Pie: algo que siga siendo cierto. La sucursal activa, por ejemplo. */
  footer?: ReactNode;
  children: ReactNode;
}

export function Sidebar({ company, footer, children }: SidebarProps) {
  return (
    <aside className="mo-side">
      <div className="mo-brand">
        <LogoMark size={30} />
        <div>
          <b>Mi Óptica</b>
          {company && <small>{company}</small>}
        </div>
      </div>
      <nav className="mo-nav">{children}</nav>
      {footer && <div className="mo-foot">{footer}</div>}
    </aside>
  );
}

export function Topbar({ crumb, user }: { crumb: string; user?: { name: string; initials: string } }) {
  return (
    <div className="mo-topbar">
      <div className="mo-crumb">{crumb}</div>
      {user && (
        <div className="mo-who">
          <span>{user.name}</span>
          <div className="mo-avatar">{user.initials}</div>
        </div>
      )}
    </div>
  );
}

export function AppShell({ sidebar, topbar, children }: {
  sidebar: ReactNode; topbar?: ReactNode; children: ReactNode;
}) {
  return (
    <div className="mo-app mo-root">
      {sidebar}
      <div className="mo-main">
        {topbar}
        <div className="mo-content">{children}</div>
      </div>
    </div>
  );
}
