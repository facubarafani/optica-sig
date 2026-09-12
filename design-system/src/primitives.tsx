import type { ReactNode, ButtonHTMLAttributes, InputHTMLAttributes, SelectHTMLAttributes } from "react";

const cx = (...v: (string | false | undefined | null)[]) => v.filter(Boolean).join(" ");

/* ---------------------------------------------------------------- Button */

export type ButtonVariant = "default" | "primary" | "danger" | "ghost";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  /** Compacto, para acciones dentro de una fila de tabla. */
  small?: boolean;
  /** Sólo ícono. Poné `title`: es lo único que lo explica. */
  iconOnly?: boolean;
  icon?: ReactNode;
}

export function Button({ variant = "default", small, iconOnly, icon, children, className, ...rest }: ButtonProps) {
  return (
    <button
      className={cx("mo-btn", variant !== "default" && `mo-btn--${variant}`,
                    small && "mo-btn--sm", iconOnly && "mo-btn--icon", className)}
      {...rest}
    >
      {icon}
      {children}
    </button>
  );
}

/* ---------------------------------------------------------------- Badge */

/** Verde y rojo tienen significado fijo: cobrado / en stock, deuda / agotado. */
export type BadgeTone = "green" | "gray" | "blue" | "amber" | "red";

export function Badge({ tone = "gray", children }: { tone?: BadgeTone; children: ReactNode }) {
  return <span className={`mo-badge mo-badge--${tone}`}>{children}</span>;
}

/* ---------------------------------------------------------------- Card */

export function Card({ pad, className, children }: { pad?: boolean; className?: string; children: ReactNode }) {
  return <div className={cx("mo-card", pad && "mo-card--pad", className)}>{children}</div>;
}

/* ---------------------------------------------------------------- form */

export interface FieldProps {
  label: string;
  required?: boolean;
  help?: string;
  warn?: string;
  children: ReactNode;
}

export function Field({ label, required, help, warn, children }: FieldProps) {
  return (
    <div style={{ marginBottom: 14 }}>
      <label className="mo-field">
        {label} {required && <span className="mo-req">*</span>}
      </label>
      {children}
      {help && <div className="mo-help">{help}</div>}
      {warn && <div className="mo-warn">{warn}</div>}
    </div>
  );
}

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> { small?: boolean }
export function Input({ small, className, ...rest }: InputProps) {
  return <input className={cx("mo-input", small && "mo-input--sm", className)} {...rest} />;
}

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> { small?: boolean }
export function Select({ small, className, children, ...rest }: SelectProps) {
  return <select className={cx("mo-input", small && "mo-input--sm", className)} {...rest}>{children}</select>;
}

export function Switch({ label, ...rest }: { label: string } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="mo-switch">
      <input type="checkbox" {...rest} />
      {label}
    </label>
  );
}

export function SearchBox({ width = 260, ...rest }: { width?: number } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div className="mo-search" style={{ width }}>
      <svg className="mo-ic" viewBox="0 0 24 24"><circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" /></svg>
      <Input small {...rest} />
    </div>
  );
}

/* ---------------------------------------------------------------- layout */

export function PageHead({ title, sub, actions }: { title: string; sub?: string; actions?: ReactNode }) {
  return (
    <div className="mo-page-head">
      <div>
        <h2>{title}</h2>
        {sub && <div className="mo-sub">{sub}</div>}
      </div>
      {actions && <div style={{ display: "flex", gap: 10 }}>{actions}</div>}
    </div>
  );
}

export function Toolbar({ children }: { children: ReactNode }) {
  return <div className="mo-toolbar">{children}</div>;
}

export function Spacer() { return <div className="mo-grow" />; }

/* ---------------------------------------------------------------- stats */

export function StatGrid({ children }: { children: ReactNode }) {
  return <div className="mo-stats">{children}</div>;
}

export function Stat({ label, value, unit, icon }: { label: string; value: ReactNode; unit?: string; icon?: ReactNode }) {
  return (
    <div className="mo-stat">
      <div className="mo-k">{icon}{label}</div>
      <div className="mo-v">{value}{unit && <small> {unit}</small>}</div>
    </div>
  );
}

/* ---------------------------------------------------------------- tabs, vacíos */

export function Tabs({ items, active, onSelect }: {
  items: { key: string; label: string }[];
  active: string;
  onSelect?: (key: string) => void;
}) {
  return (
    <div className="mo-tabs">
      {items.map(i => (
        <button key={i.key} className={i.key === active ? "mo-on" : undefined}
                onClick={() => onSelect?.(i.key)}>{i.label}</button>
      ))}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="mo-empty">{children}</div>;
}

export function Loading({ children = "Cargando..." }: { children?: ReactNode }) {
  return <div className="mo-loading">{children}</div>;
}
