import { LogoSymbol } from "@mi-optica/ui";

/** El anillo con el haz. Va suelto, cuando tiene aire alrededor. */
export const ConHaz = () => <LogoSymbol size={72} />;

/** Sobre el casco oscuro. */
export const SobreOscuro = () => (
  <div style={{ background: "var(--ink)", padding: 28, borderRadius: 10 }}>
    <LogoSymbol size={64} />
  </div>
);
