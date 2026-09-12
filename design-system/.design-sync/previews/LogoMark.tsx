import { LogoMark } from "@mi-optica/ui";

/** El anillo en los tamaños donde vive: ícono, barra lateral, favicon. */
export const Tamanos = () => (
  <div style={{ display: "flex", gap: 22, alignItems: "flex-end" }}>
    <LogoMark size={64} />
    <LogoMark size={40} />
    <LogoMark size={30} />
    <LogoMark size={16} />
  </div>
);

/** Sobre el casco oscuro, que es donde va en la barra lateral. */
export const SobreOscuro = () => (
  <div style={{ background: "var(--ink)", padding: 26, borderRadius: 10,
                display: "flex", gap: 20, alignItems: "center" }}>
    <LogoMark size={44} />
    <LogoMark size={30} />
    <LogoMark size={16} />
  </div>
);
