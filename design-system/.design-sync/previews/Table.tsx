import { Table, Badge, Button, SwatchList, type Column } from "@mi-optica/ui";

type Row = {
  code: string; desc: string; type: string; brand: string; model: string | null;
  colors: { hex: string; name: string }[]; variants: number;
  price: string | null; cost: string | null; active: boolean;
};

const rows: Row[] = [
  { code: "ARM-001", desc: "Armazón acetato full rim 52", type: "Armazón", brand: "Vulk",
    model: "Sole", variants: 3, price: null, cost: null, active: true,
    colors: [{ hex: "#7A4B28", name: "Havana" }, { hex: "#14181F", name: "Negro" },
             { hex: "#D9D4CB", name: "Cristal" }] },
  { code: "ARM-001-HAV", desc: "Armazón acetato full rim 52 Havana", type: "Armazón",
    brand: "Vulk", model: "Sole", variants: 0, price: "128.400,00", cost: "61.200,00",
    active: true, colors: [{ hex: "#7A4B28", name: "Havana" }] },
  { code: "LC-0042", desc: "Lente de contacto mensual -1.25", type: "Lente cont.",
    brand: "Bausch & Lomb", model: null, variants: 0, price: "46.900,00",
    cost: "23.100,00", active: true, colors: [] },
  { code: "ACC-0031", desc: "Estuche rígido bicolor", type: "Accesorio", brand: "",
    model: null, variants: 0, price: "8.900,00", cost: "3.400,00", active: false,
    colors: [{ hex: "#1B2A3A", name: "Azul" }, { hex: "#8C1F2F", name: "Bordó" }] },
];

/**
 * La grilla de productos. Fijate en ARM-001: es un estilo con variantes, así que
 * no muestra ni precio ni stock. Un estilo no se vende ni se stockea, sólo sus
 * variantes. La grilla dibuja esa regla en vez de explicarla.
 */
const columns: Column<Row>[] = [
  { key: "code", label: "Código", mono: true, width: 132 },
  { key: "desc", label: "Descripción", trunc: true },
  { key: "type", label: "Tipo", width: 110 },
  { key: "brand", label: "Marca", width: 120, render: r => r.brand || "-" },
  { key: "model", label: "Modelo", priority: 2, width: 96, render: r => r.model || "-" },
  { key: "colors", label: "Colores", priority: 2, width: 104,
    render: r => (r.colors.length ? <SwatchList colors={r.colors} /> : "-") },
  { key: "variants", label: "Variantes", priority: 2, width: 96,
    render: r => (r.variants ? <a href="#">{r.variants} variantes</a> : "-") },
  { key: "price", label: "Precio", num: true, width: 116, render: r => r.price ?? "-" },
  { key: "cost", label: "Costo", num: true, priority: 2, width: 104, render: r => r.cost ?? "-" },
  { key: "active", label: "Estado", priority: 3, width: 84,
    render: r => <Badge tone={r.active ? "green" : "gray"}>{r.active ? "Activo" : "Inactivo"}</Badge> },
];

export const Productos = () => (
  <Table
    columns={columns}
    rows={rows}
    rowKey={r => r.code}
    isInactive={r => !r.active}
    actions={() => <Button small>Abrir</Button>}
  />
);

/** Sin resultados: dice qué pasó, no sólo que está vacío. */
export const SinResultados = () => (
  <Table columns={columns.slice(0, 4)} rows={[]} rowKey={r => r.code}
         empty="Ningún producto coincide con el filtro." />
);
