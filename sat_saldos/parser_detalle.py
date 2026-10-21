"""Parser de la DECLARACIÓN DETALLADA de IVA (vista previa del SAT).

A diferencia del acuse, la declaración detallada trae el renglón
'Acreditamiento del saldo a favor de periodos anteriores'. Con él se reconstruye
el remanente ACUMULADO real de IVA (que el acuse no permite determinar).

Estructura del PDF (validada contra los acuses reales 2025 de una PM RESICO):
- Documento multipágina; las páginas se separan con '\\f' (form feed).
- Cada página trae en su encabezado el impuesto: 'IVA simplificado de confianza'
  o 'ISR simplificado ...'. Los documentos pueden ser solo-IVA o combinados ISR+IVA.
- La página de DETERMINACIÓN de IVA contiene 'CANTIDAD A CARGO' y, según el
  resultado, 'IMPUESTO A CARGO' (a cargo) o 'IMPUESTO A FAVOR' (a favor).
- Los valores están alineados a la derecha; se toma el último número de la línea
  de la etiqueta. La primera ocurrencia de cada etiqueta es la de la determinación.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import DetalleISR, DetalleIVA, PerdidaFiscal
from .parser import _sin_acentos, num

MESMAP = {
    'ENERO': 1, 'FEBRERO': 2, 'MARZO': 3, 'ABRIL': 4, 'MAYO': 5, 'JUNIO': 6,
    'JULIO': 7, 'AGOSTO': 8, 'SEPTIEMBRE': 9, 'OCTUBRE': 10, 'NOVIEMBRE': 11,
    'DICIEMBRE': 12,
}
_NUM = r'\(?-?\$?[\d,]+\.?\d*\)?'
_RE_FECHA = re.compile(r'\d{2}/\d{2}/\d{4}')


def _first(*vals):
    """Primer valor no-None (0.0 es válido, None = no encontrado)."""
    for v in vals:
        if v is not None:
            return v
    return None
_RE_MES = re.compile(r'\b(' + '|'.join(MESMAP) + r')\b')


def es_declaracion_detallada(texto: str) -> bool:
    """True si el texto corresponde a una declaración detallada de IVA."""
    u = texto.upper()
    return 'IVA ACREDITABLE DEL PERIODO' in u or 'ACREDITABLE DEL PERIODO' in u


def _pagina_determinacion_iva(texto: str) -> Optional[str]:
    """Devuelve la página de IVA con la determinación (a cargo / a favor)."""
    for p in texto.split('\f'):
        u = p.upper()
        if 'IVA SIMPLIFICADO' not in u and 'VALOR AGREGADO' not in u:
            continue
        if 'CANTIDAD A CARGO' in u and ('IMPUESTO A CARGO' in u or 'IMPUESTO A FAVOR' in u):
            return p
    return None


def _valor(pagina: str, etiqueta: str, occ: int = 0) -> Optional[float]:
    """Último número de la occ-ésima línea que hace match con la etiqueta."""
    lineas = [l for l in pagina.split('\n') if re.search(etiqueta, l, re.I)]
    if len(lineas) <= occ:
        return None
    limpia = _RE_FECHA.sub('', lineas[occ])
    nums = re.findall(_NUM, limpia)
    return num(nums[-1]) if nums else None


def _periodo(texto: str) -> Optional[int]:
    """Periodo mensual: metadatos si están, si no el primer mes en páginas IVA."""
    flat = re.sub(r'[ \t]+', ' ', texto)
    m = re.search(r'Per[ií]odo de la declaraci[oó]n:\s*([A-Za-zÁÉÍÓÚáéíóú]+)', flat)
    if m and m.group(1).strip():
        return MESMAP.get(_sin_acentos(m.group(1)).upper())
    for p in texto.split('\f'):
        if 'IVA SIMPLIFICADO' in p.upper():
            mm = _RE_MES.search(_sin_acentos(p).upper())
            if mm:
                return MESMAP.get(mm.group(1))
    return None


def _meta(texto: str, archivo: str) -> tuple:
    flat = re.sub(r'[ \t]+', ' ', texto)
    rfc = re.search(r'RFC[:\s]+([A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3})', flat)
    ej = re.search(r'Ejercicio[:\s]+(\d{4})', flat)
    op = re.search(r'N[uú]mero de operaci[oó]n:\s*(\d+)', flat)
    fe = re.search(r'Fecha y hora de presentaci[oó]n:\s*(\d{2}/\d{2}/\d{4})\s*(\d{2}:\d{2})?', flat)
    dt = None
    if fe:
        try:
            dt = datetime.strptime(fe.group(1) + ' ' + (fe.group(2) or '00:00'), '%d/%m/%Y %H:%M')
        except ValueError:
            dt = None
    base = f"{Path(archivo).name} {flat}".lower()
    if 'dejar-sin-efecto' in base or 'dejar sin efecto' in base:
        subtipo = 'dejar-sin-efecto'
    elif 'modificaci' in base:
        subtipo = 'modificacion'
    elif 'complementaria' in base:
        subtipo = 'complementaria'
    else:
        subtipo = 'normal'
    return (rfc.group(1) if rfc else "",
            int(ej.group(1)) if ej else None,
            op.group(1) if op else None, dt, subtipo)


def es_declaracion_detallada_isr(texto: str) -> bool:
    """True si el texto contiene una determinación detallada de ISR."""
    u = texto.upper()
    return ('ISR' in u
            and ('IMPUESTO CAUSADO' in u or 'IMPUESTO DEL EJERCICIO' in u)
            and ('PAGOS PROVISIONALES' in u or 'PAGO PROVISIONAL' in u
                 or 'RESULTADO FISCAL' in u or 'BASE GRAVABLE' in u))


def _paginas_isr(texto: str) -> list[str]:
    """Devuelve las páginas que contienen determinación de ISR."""
    out = []
    for p in texto.split('\f'):
        u = p.upper()
        if 'ISR' not in u and 'RENTA' not in u:
            continue
        if ('IMPUESTO CAUSADO' in u or 'IMPUESTO DEL EJERCICIO' in u
                or 'BASE GRAVABLE' in u or 'RESULTADO FISCAL' in u
                or 'UTILIDAD FISCAL' in u or 'PAGOS PROVISIONALES' in u
                or 'TOTAL DE INGRESOS ACUMULABLES' in u
                or 'TOTAL DE INGRESOS DEL PERIODO' in u
                or 'TOTAL DE DEDUCCIONES AUTORIZADAS' in u):
            out.append(p)
    return out


def _detectar_regimen(texto: str) -> str:
    u = texto.upper()
    if 'SIMPLIFICADO DE CONFIANZA' in u and 'PERSONAS MORALES' in u:
        return 'PM_RESICO'
    if 'PERSONAS MORALES' in u or 'TITULO II' in u:
        return 'PM_RG'
    if 'ACTIVIDAD EMPRESARIAL' in u or 'PERSONAS FISICAS' in u or 'PERSONAS F' in u:
        return 'PF_AE'
    return ''


def _es_anual(texto: str) -> bool:
    u = texto.upper()
    return ('DEL EJERCICIO' in u or 'PERIODICIDAD ANUAL' in u
            or 'RESULTADO FISCAL' in u)


def _perdidas_tabla(paginas: list[str]) -> list[PerdidaFiscal]:
    """Extrae la tabla de pérdidas fiscales de ejercicios anteriores."""
    out = []
    for pag in paginas:
        for line in pag.split('\n'):
            m = re.match(r'.*?(\d{4})\s+', line)
            if not m:
                continue
            nums = re.findall(_NUM, line)
            if len(nums) < 2:
                continue
            anio = int(m.group(1))
            if anio < 2000 or anio > 2099:
                continue
            vals = [num(n) for n in nums]
            out.append(PerdidaFiscal(
                anio_origen=anio,
                pendientes_de_aplicar=vals[0] if len(vals) > 0 else None,
                perdida_actualizada=vals[1] if len(vals) > 1 else None,
                aplicada_en_ejercicio=vals[2] if len(vals) > 2 else None,
                remanente=vals[3] if len(vals) > 3 else None,
            ))
    return out


def parse_detalle_isr(texto: str, archivo: str = "") -> Optional[DetalleISR]:
    """Parsea la determinación de ISR de una declaración detallada (formato nuevo post-2023)."""
    if not es_declaracion_detallada_isr(texto):
        return None
    paginas = _paginas_isr(texto)
    if not paginas:
        return None

    bloque = '\n'.join(paginas)
    rfc, ejercicio, operacion, dt, subtipo = _meta(texto, archivo)
    anual = _es_anual(texto)
    regimen = _detectar_regimen(texto)

    def v(etiqueta, occ=0):
        return _valor(bloque, etiqueta, occ)

    d = DetalleISR(
        archivo=archivo, rfc=rfc, ejercicio=ejercicio,
        periodo=0 if anual else _periodo(texto),
        operacion=operacion, fecha_presentacion=dt, subtipo=subtipo,
        es_anual=anual,
        regimen=regimen, formato='nuevo',
    )

    # Determinación (campos comunes mensual + anual)
    d.ingresos_acumulables = _first(v(r'TOTAL DE INGRESOS ACUMULABLES'),
                                    v(r'INGRESOS ACUMULABLES'),
                                    v(r'TOTAL DE INGRESOS DEL PERIODO'),
                                    v(r'INGRESOS NOMINALES DEL PERIODO'))
    d.deducciones_autorizadas = _first(v(r'TOTAL DE DEDUCCIONES AUTORIZADAS'),
                                       v(r'DEDUCCIONES AUTORIZADAS'))
    d.utilidad_fiscal = _first(v(r'UTILIDAD FISCAL'), v(r'UTILIDAD GRAVABLE'))
    d.perdidas_fiscales_aplicadas = _first(v(r'PERDIDAS FISCALES DE EJERCICIOS ANT'),
                                           v(r'PERDIDAS FISCALES APLICADAS'),
                                           v(r'AMORTIZACION DE PERDIDAS'))
    d.impuesto_causado = v(r'IMPUESTO CAUSADO')
    d.isr_retenido = _first(v(r'ISR RETENIDO AL CONTRIBUYENTE'),
                            v(r'TOTAL DE ISR RETENIDO'),
                            v(r'ISR RETENIDO'),
                            v(r'RETENCIONES'))

    if anual:
        d.ptu_pagada = _first(v(r'TOTAL PTU PAGADA'), v(r'PTU PAGADA'))
        d.resultado_fiscal = v(r'RESULTADO FISCAL')
        d.isr_a_cargo_ejercicio = _first(v(r'ISR A CARGO DEL EJERCICIO'),
                                         v(r'IMPUESTO A CARGO DEL EJERCICIO'))
        d.saldo_a_favor = v(r'SALDO A FAVOR')
        d.perdida_fiscal_ejercicio = _first(v(r'PERDIDA FISCAL DEL EJERCICIO'),
                                            v(r'PERDIDA FISCAL'))
        d.pagos_provisionales_anteriores = _first(
            v(r'IMPORTE DE PAGOS PROVISIONALES POR'),
            v(r'PAGOS PROVISIONALES EFECTUADOS'),
            v(r'TOTAL DE PAGOS PROVISIONALES'))
        d.isr_acreditable_dividendos = v(r'ISR ACREDITABLE.*DIVIDENDOS')
        d.compensaciones = v(r'COMPENSACIONES')
        d.impuesto_del_periodo = _first(v(r'IMPUESTO CAUSADO DEL EJERCICIO'),
                                        v(r'IMPUESTO DEL EJERCICIO'))
        d.perdidas_detalle = _perdidas_tabla(paginas)
    else:
        d.base_gravable = _first(v(r'BASE GRAVABLE'), v(r'BASE DEL IMPUESTO'))
        d.impuesto_del_periodo = _first(v(r'IMPUESTO DEL PERIODO'),
                                        v(r'IMPUESTO DETERMINADO DEL PERIODO'))
        d.pagos_provisionales_anteriores = _first(
            v(r'PAGOS PROVISIONALES.*ANTERIORES'),
            v(r'PAGOS PROVISIONALES EFECTUADOS'))
        d.compensaciones = _first(v(r'COMPENSACION'),
                                  v(r'ACREDITAMIENTO.*SALDO A FAVOR'))
        d.impuesto_a_cargo = v(r'IMPUESTO A CARGO')
        d.cantidad_a_cargo = v(r'CANTIDAD A CARGO')
        d.cantidad_a_pagar = v(r'CANTIDAD A PAGAR')
        d.coeficiente_utilidad = v(r'COEFICIENTE DE UTILIDAD')
        d.perdidas_detalle = _perdidas_tabla(paginas)

    return d


def parse_detalle_iva(texto: str, archivo: str = "") -> Optional[DetalleIVA]:
    """Parsea la determinación de IVA de una declaración detallada.

    `texto` debe ser salida de `pdftotext -layout` (conserva el form feed y la
    alineación). Devuelve None si no es una declaración detallada de IVA legible.
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
        a_cargo_periodo=_valor(pagina, r'^\s*CANTIDAD A CARGO', 0),
        a_favor_periodo=_valor(pagina, r'IMPUESTO A FAVOR', 0),
        acreditamiento_anterior=_valor(pagina, r'ACREDITAMIENTO DEL SALDO A FAVOR', 0) or 0.0,
        impuesto_a_cargo_final=_valor(pagina, r'^\s*IMPUESTO A CARGO', 0),
        cantidad_a_pagar=_valor(pagina, r'CANTIDAD A PAGAR', 0),
    )
