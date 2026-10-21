"""Lee la determinación de IVA desde el MD de una declaración, por RUTA
(impuesto › sección › etiqueta), con PERFIL por régimen.

El régimen va por DECLARACIÓN (su encabezado), no por RFC: un mismo contribuyente
puede cambiar (p. ej. Jordan: régimen general hasta 2021, RESICO desde 2022).

Identidades del formulario (red de seguridad; si no cuadra → "revisar"):
- PM régimen general / PF actividad empresarial:
    causado + cantidad actualizada a reintegrarse − IVA retenido − acreditable
    + otras cantidades a cargo − otras a favor = cantidad a cargo | saldo a favor
- PM RESICO:
    total de IVA a cargo − IVA no cobrado por devoluciones… de ventas
    + IVA por devoluciones… en gastos − IVA acreditable del periodo = idem
- Todos: cantidad a cargo − acreditamiento = impuesto a cargo.
"""
from __future__ import annotations

from .pdf_a_md import TITULOS_TABLA, es_num, norm

PM_GENERAL = "PM régimen general"
PM_RESICO = "PM RESICO"
PF_RESICO = "PF RESICO"
PF_AE = "PF actividad empresarial"


def regimen_de(md: str) -> str:
    """Régimen de la declaración según su encabezado ('' si no se reconoce)."""
    n = norm("\n".join(l for l in md.splitlines() if l.startswith(("## ", "### "))))
    if "SIMPLIFICADO DE CONFIANZA" in n:
        return PF_RESICO if "PERSONAS FISICAS" in n else PM_RESICO
    if "ACTIVIDAD EMPRESARIAL" in n or "PERSONAS FISICAS" in n:
        return PF_AE
    if "PERSONAS MORALES" in n:
        return PM_GENERAL
    return ""


def entradas(md: str):
    """[(impuesto, seccion, etiqueta, valor)] de las filas tipo formulario."""
    imp, sec, out = None, "", []
    for ln in md.splitlines():
        if ln.startswith("## "):
            imp = ln[3:].split(" — ")[0].strip()
        elif ln.startswith("### "):
            sec = norm(ln[4:])
        elif ln.startswith("|") and imp and not sec.startswith(TITULOS_TABLA + ("HISTORICO",)):
            celdas = [c.strip() for c in ln.strip().strip("|").split("|")]
            for i in range(0, len(celdas) - 1, 2):            # pares etiqueta | valor
                if celdas[i] and es_num(celdas[i + 1]):
                    out.append((imp, sec, norm(celdas[i]),
                                float(celdas[i + 1].replace(",", "").replace("$", ""))))
    return out


def _es_pago(sec):
    return sec.startswith("DETALLE DEL PAGO")


def _primero(ent, en_seccion, etiquetas):
    for et in etiquetas:                       # prioridad por etiqueta, 1ª aparición
        for i, s, e, v in ent:
            if i == "IVA" and en_seccion(s) and (e == et or e.startswith(et + " ")):
                return v
    return None


DET = lambda s: not _es_pago(s)   # noqa: E731
PAG = _es_pago

# Etiquetas comunes a todos los regímenes.
_COMUNES = {
    "dev_gastos": (DET, ("IVA POR DEVOLUCIONES, DESCUENTOS Y BONIFICACIONES EN GASTOS",)),
    "dev_ingresos": (DET, ("IVA NO COBRADO POR DEVOLUCIONES, DESCUENTOS Y BONIFICACIONES DE VENTAS",
                           "IVA POR DEVOLUCIONES, DESCUENTOS Y BONIFICACIONES EN INGRESOS")),
    "iva_retenido": (DET, ("IVA RETENIDO",)),
    "reintegrar": (DET, ("CANTIDAD ACTUALIZADA A REINTEGRARSE",)),
    "otras_cargo": (DET, ("OTRAS CANTIDADES A CARGO",)),
    "otras_favor": (DET, ("OTRAS CANTIDADES A FAVOR",)),
    "devolucion": (DET, ("DEVOLUCION INMEDIATA OBTENIDA",)),
    "cantidad_cargo": (DET, ("CANTIDAD A CARGO",)),
    "acreditamiento": (DET, ("ACREDITAMIENTO DEL SALDO A FAVOR",)),
    "impuesto_cargo": (DET, ("IMPUESTO A CARGO",)),
    "saldo_favor": (DET, ("SALDO A FAVOR",)),
    "a_favor": (DET, ("SALDO A FAVOR DEL PERIODO", "IMPUESTO A FAVOR", "SALDO A FAVOR")),
    "pago_a_cargo": (PAG, ("A CARGO",)),
    "pago_actualizacion": (PAG, ("PARTE ACTUALIZADA",)),
    "pago_recargos": (PAG, ("RECARGOS",)),
    "pago_cantidad_cargo": (PAG, ("CANTIDAD A CARGO",)),
}
# Perfil por régimen: qué renglón es el IVA causado y cuál el acreditable (orden
# de prioridad). Régimen no reconocido → unión de todos.
_CAUSADO_GENERAL = ("IMPUESTO CAUSADO", "IVA A CARGO A LA TASA DEL 16%", "TOTAL DE IVA A CARGO")
_CAUSADO_RESICO = ("TOTAL DE IVA A CARGO", "IMPUESTO CAUSADO", "IVA A CARGO A LA TASA DEL 16%")
_ACRED_GENERAL = ("TOTAL DE IVA ACREDITABLE", "IVA ACREDITABLE DEL PERIODO")
_ACRED_RESICO = ("IVA ACREDITABLE DEL PERIODO", "TOTAL DE IVA ACREDITABLE")
PERFILES = {
    PM_GENERAL: (_CAUSADO_GENERAL, _ACRED_GENERAL),
    PF_AE: (_CAUSADO_GENERAL, _ACRED_GENERAL),
    PM_RESICO: (_CAUSADO_RESICO, _ACRED_RESICO),
    PF_RESICO: (_CAUSADO_RESICO, _ACRED_RESICO),
    "": (("IMPUESTO CAUSADO", "TOTAL DE IVA A CARGO", "IVA A CARGO A LA TASA DEL 16%"),
         _ACRED_GENERAL),
}


def leer_iva(md: str, regimen: str | None = None) -> dict:
    """Campos de la determinación de IVA ({} si el MD no trae IVA)."""
    ent = entradas(md)
    reg = regimen_de(md) if regimen is None else regimen
    causado, acred = PERFILES.get(reg, PERFILES[""])
    campos = dict(_COMUNES, iva_causado=(DET, causado), iva_acreditable=(DET, acred))
    out = {}
    for k, (sec, ets) in campos.items():
        v = _primero(ent, sec, ets)
        if v is not None:
            out[k] = v
    return out


def identidad(v: dict) -> list:
    """Verificaciones del formulario (True = cuadra). Lista vacía = sin datos."""
    g = lambda k: v.get(k, 0) or 0   # noqa: E731
    r = []
    if "iva_causado" in v and "iva_acreditable" in v:
        dif = (g("iva_causado") + g("reintegrar") - g("iva_retenido") - g("iva_acreditable")
               + g("otras_cargo") - g("otras_favor") + g("dev_gastos") - g("dev_ingresos"))
        if dif >= 0:
            r.append(abs(dif - g("cantidad_cargo")) < 2)
        else:
            fav = v["saldo_favor"] if "saldo_favor" in v else g("a_favor") + g("devolucion")
            r.append(abs(-dif - fav) < 2)
    if "cantidad_cargo" in v and "impuesto_cargo" in v:
        r.append(abs(g("cantidad_cargo") - g("acreditamiento") - g("impuesto_cargo")) < 2)
    return r


if __name__ == "__main__":
    # Autoverificación mínima con un MD sintético (formato RESICO PM).
    md = "\n".join([
        "## ISR — ISR SIMPLIFICADO DE CONFIANZA. PERSONAS MORALES",
        "## IVA",
        "### DETERMINACIÓN DEL IMPUESTO AL VALOR AGREGADO",
        "| TOTAL DE IVA A CARGO | 10,000 |",
        "| IVA ACREDITABLE DEL PERIODO | 4,000 |",
        "| CANTIDAD A CARGO | 6,000 |",
        "| ACREDITAMIENTO DEL SALDO A FAVOR DE PERIODOS ANTERIORES | 1,500 |",
        "| IMPUESTO A CARGO | 4,500 |",
        "### DETALLE DEL PAGO",
        "| CANTIDAD A CARGO | 9,999 |",
    ])
    assert regimen_de(md) == PM_RESICO
    v = leer_iva(md)
    assert v["iva_causado"] == 10000 and v["cantidad_cargo"] == 6000, v
    assert v["acreditamiento"] == 1500 and v["pago_cantidad_cargo"] == 9999, v
    assert identidad(v) == [True, True], identidad(v)
    v["impuesto_cargo"] = 4000
    assert identidad(v) == [True, False]
    print("parser_md OK")
