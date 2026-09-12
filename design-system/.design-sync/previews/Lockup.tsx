import { Lockup } from "@mi-optica/ui";

/** La marca completa. El espectro vive en las letras de DIGITAL. */
export const Principal = () => <Lockup size={44} />;

/** Sobre el casco oscuro: es lo que se ve en la pantalla de ingreso. */
export const SobreOscuro = () => (
  <div style={{ background: "var(--ink)", padding: 30, borderRadius: 10 }}>
    <Lockup size={38} dark />
  </div>
);

/** Una sola tinta, para sello, ticket o impresión sin degradado. */
export const UnaTinta = () => <Lockup size={38} flat />;
