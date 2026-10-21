def _valor_variado(pagina: str, etiquetas: list[str], occ: int = 0):
    """Devuelve el primero de varios posibles rótulos para una misma cifra.

    Mantiene compatibilidad con los formatos antiguos y agrega los labels modernos
    de 2024+ sin romper la lectura de 2023 hacia atrás.
    """
    for etiqueta in etiquetas:
        val = _valor(pagina, etiqueta, occ)
        if val is not None:
            return val
    return None


def _pagina_determinacion_iva(texto: str) -> Optional[str]:
    """Devuelve la página de IVA con la determinación (a cargo / a favor).

    Acepta tanto los labels antiguos como los modernos de 2024+.
    """
    for p in texto.split('\f'):
        u = p.upper()
        if 'IVA' not in u and 'VALOR AGREGADO' not in u:
            continue
        if any(x in u for x in [
            'IVA A CARGO',
            'CANTIDAD A CARGO',
            'IVA ACREDITABLE',
            'ACREDITABLE DEL PERIODO',
            'IMPUESTO A CARGO',
            'IMPUESTO A FAVOR',
            'SALDO A FAVOR',
            'A CARGO',
            'A FAVOR',
        ]):
            return p
    return None


def parse_detalle_iva(texto: str, archivo: str = "") -> Optional[DetalleIVA]:
    """Parsea la determinación de IVA de una declaración detallada.

    Mantiene soporte para los PDFs de 2023 y anteriores y agrega los nuevos labels
    de 2024+ sin romper la compatibilidad.
    """
    if not es_declaracion_detallada(texto):
        return None
    pagina = _pagina_determinacion_iva(texto)
    if pagina is None:
        return None

    rfc, ejercicio, operacion, dt, subtipo = _meta(texto, archivo)
    return DetalleIVA(
        archivo=archivo,
        rfc=rfc,
        ejercicio=ejercicio,
        periodo=_periodo(texto),
        operacion=operacion,
        fecha_presentacion=dt,
        subtipo=subtipo,
        a_cargo_periodo=_valor_variado(pagina, [
            r'IVA A CARGO',
            r'^\s*CANTIDAD A CARGO',
            r'^\s*IMPUESTO A CARGO',
            r'A CARGO',
            r'CANTIDAD A CARGO',
        ], 0),
        a_favor_periodo=_valor_variado(pagina, [
            r'IVA A FAVOR',
            r'IMPUESTO A FAVOR',
            r'SALDO A FAVOR',
            r'A FAVOR',
        ], 0),
        acreditamiento_anterior=_valor_variado(pagina, [
            r'IVA ACREDITABLE',
            r'ACREDITABLE',
            r'ACREDITAMIENTO DEL SALDO A FAVOR',
        ], 0) or 0.0,
        impuesto_a_cargo_final=_valor_variado(pagina, [
            r'^\s*IMPUESTO A CARGO',
            r'IVA A CARGO',
            r'^\s*CANTIDAD A CARGO',
        ], 0),
        cantidad_a_pagar=_valor_variado(pagina, [
            r'CANTIDAD A PAGAR',
            r'PAGO DEL PERIODO',
        ], 0),
    )
