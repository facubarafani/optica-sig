import { Field, Input, Select } from "@mi-optica/ui";

/** Campo obligatorio: el asterisco va en rojo, que acá significa falta algo. */
export const Obligatorio = () => (
  <div style={{ maxWidth: 380 }}>
    <Field label="Código" required>
      <Input defaultValue="ARM-001" />
    </Field>
  </div>
);

/** Con ayuda debajo: el texto explica la regla, no repite la etiqueta. */
export const ConAyuda = () => (
  <div style={{ maxWidth: 380 }}>
    <Field label="Lista de precios" help="Vacío = se usa la lista por defecto de la empresa.">
      <Select defaultValue="b">
        <option value="a">Lista A</option>
        <option value="b">Lista B</option>
      </Select>
    </Field>
  </div>
);

/** Con advertencia: algo que se va a guardar igual, pero conviene mirar. */
export const ConAdvertencia = () => (
  <div style={{ maxWidth: 380 }}>
    <Field
      label="Modelo"
      warn="Duna no pertenece al tipo Armazón. Se guarda igual."
    >
      <Select defaultValue="duna">
        <option value="duna">Duna</option>
      </Select>
    </Field>
  </div>
);
