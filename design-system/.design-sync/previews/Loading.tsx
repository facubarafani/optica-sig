import { Loading } from "@mi-optica/ui";

/** Por defecto. */
export const Cargando = () => <Loading />;

/** Con texto propio cuando la espera tiene una razón que vale explicar. */
export const ConTexto = () => <Loading>Recalculando precios de la lista B...</Loading>;
