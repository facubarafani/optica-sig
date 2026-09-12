import { Toolbar, SearchBox, Select, Switch, Spacer } from "@mi-optica/ui";

/** La barra de filtros de una grilla: buscador, filtros y el interruptor al final. */
export const Filtros = () => (
  <Toolbar>
    <SearchBox placeholder="Buscar por código o descripción" width={260} />
    <Select small defaultValue="arm" style={{ width: 150 }}>
      <option value="arm">Tipo: Armazón</option>
      <option value="lc">Tipo: Lente de contacto</option>
    </Select>
    <Select small style={{ width: 130 }}><option>Marca</option></Select>
    <Select small style={{ width: 140 }}><option>Proveedor</option></Select>
    <Spacer />
    <Switch label="Ver inactivos" />
  </Toolbar>
);
