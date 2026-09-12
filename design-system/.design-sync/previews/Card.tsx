import { Card, Button } from "@mi-optica/ui";

/** Con padding: lo normal para un bloque de contenido. */
export const ConPadding = () => (
  <Card pad>
    <div style={{ fontWeight: 650, marginBottom: 6 }}>Receta del 12/08</div>
    <div style={{ fontSize: 13, color: "var(--muted)", lineHeight: 1.6 }}>
      OD -1,25 -0,75 180 · adición +2,00<br />
      OI -1,50 -0,50 175 · adición +2,00<br />
      DNP 62,0 · Dr. Alvarez
    </div>
  </Card>
);

/** Sin padding: cuando adentro va una tabla, que trae el suyo. */
export const SinPadding = () => (
  <Card>
    <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--border)",
                  fontWeight: 650, fontSize: 13 }}>Últimos movimientos</div>
    <div style={{ padding: "12px 16px", fontSize: 13, color: "var(--muted)" }}>
      Ingreso de 12 unidades · Belgrano · 14:02
    </div>
    <div style={{ padding: "12px 16px", borderTop: "1px solid var(--border)" }}>
      <Button small>Ver todos</Button>
    </div>
  </Card>
);
