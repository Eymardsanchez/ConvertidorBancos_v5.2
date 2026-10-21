"""PDF de declaración SAT → Markdown que respeta el formato del PDF.

Reglas (definidas por el usuario, validadas contra BUCJ / Italsem / Jordan):
1. Lectura POR FILA (renglón visual).
2. CONTINUACIÓN: texto justo debajo del texto anterior en la MISMA columna
   (separación ≤ CONT_Y) se une a la fila de arriba. Medido en los formularios:
   renglones de una misma etiqueta ≈ 0.8 pt; etiquetas distintas ≥ 7.7 pt.
   La cifra que aparezca en esas líneas es de la etiqueta completa.
3. El TÍTULO de la sección (renglón de una celda, sin cifras, CENTRADO) define
   impuesto / sección / formato: formulario → | etiqueta | valor |; tabla → columnas.
Encabezados "## <impuesto>" y "### <sección>" para que cada cifra tenga su ruta
(impuesto › sección › etiqueta): la misma etiqueta en ISR, RETENCIONES, DETALLE
DEL PAGO o el histórico no se confunde con la de IVA.

Páginas sin capa de texto (escaneadas) quedan marcadas; el pipeline cae entonces
a los parsers de texto/OCR existentes.
"""
from __future__ import annotations

import io
import os
import re
import unicodedata
from pathlib import Path

from .extractor import pdf_bytes

TOL_Y = 3.0      # pt: mismo renglón visual
HUECO = 9.0      # pt: hueco horizontal entre celdas
ALINEA_X = 4.0   # pt: misma columna
CONT_Y = 3.0     # pt: separación máx. para "texto justo debajo" (continuación)
CENTRO = 0.03    # fracción del ancho: tolerancia para "título centrado"

ETIQUETAS = (    # un renglón que empieza así nunca es título
    "IMPUESTO A CARGO", "IMPUESTO A FAVOR", "IMPUESTO CAUSADO", "CANTIDAD A",
    "SALDO A FAVOR", "DIFERENCIA A CARGO", "A CARGO", "A FAVOR", "TOTAL DE",
    "IVA A CARGO", "IVA ACREDITABLE", "IVA RETENIDO",
)
TITULOS_TABLA = ("DETALLE DE INGRESOS", "SUMA DE FACTURAS", "PAGOS PROVISIONALES",
                 "DETALLE DE LOS PAGOS", "DETALLE DE GASTOS", "DETALLE DE DEDUCCIONES")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().upper()


def es_num(t: str) -> bool:
    return bool(re.fullmatch(r"-?\$?\s?\d{1,3}(,\d{3})*(\.\d+)?|-?\$?\d+(\.\d+)?", t.strip()))


def _parece_formulario(fila) -> bool:
    """Fila 'etiqueta | cifra' (o dos pares): señal de que terminó una tabla."""
    if len(fila) not in (2, 4):
        return False
    for i, c in enumerate(fila):
        if i % 2 == 0 and (es_num(c["t"]) or len(c["t"]) < 12):
            return False
        if i % 2 == 1 and not es_num(c["t"]):
            return False
    return True


def impuesto_de(n: str):
    if "RETENCION" in n:                      # "IVA retenciones", "ISR retenciones…"
        return "RETENCIONES"
    if "VALOR AGREGADO" in n or n.startswith("IVA "):
        return "IVA"
    if "SOBRE LA RENTA" in n or n.startswith("ISR "):
        return "ISR"
    if n.startswith("IEPS") or "PRODUCCION Y SERVICIOS" in n:
        return "IEPS"
    return None


def _filas(words):
    filas = []
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        if filas and abs(filas[-1][0]["top"] - w["top"]) <= TOL_Y:
            filas[-1].append(w)
        else:
            filas.append([w])
    out = []
    for f in filas:
        f.sort(key=lambda w: w["x0"])
        celdas, act = [], [f[0]]
        for w in f[1:]:
            if w["x0"] - act[-1]["x1"] > HUECO:
                celdas.append(act)
                act = []
            act.append(w)
        celdas.append(act)
        out.append([{"t": " ".join(w["text"] for w in c), "x0": c[0]["x0"],
                     "x1": c[-1]["x1"], "top": min(w["top"] for w in c),
                     "bot": max(w["bottom"] for w in c)} for c in celdas])
    return out


def _bloque(c, t=None):
    return {"t": c["t"] if t is None else t, "v": None, "x0": c["x0"], "x1": c["x1"],
            "top": c["top"], "bot": c["bot"]}


def pdf_a_md(ruta) -> str:
    import pdfplumber

    md: list = [f"# {Path(ruta).name}", ""]
    impuesto, seccion, tabla = None, "ENCABEZADO", False
    seccion_form = seccion           # última sección tipo formulario (para volver tras una tabla)
    with pdfplumber.open(io.BytesIO(pdf_bytes(Path(ruta)))) as pdf:
        for npag, pg in enumerate(pdf.pages, 1):
            md.append(f"<!-- página {npag} -->")
            W = float(pg.width)
            words = pg.extract_words(x_tolerance=1.5, y_tolerance=2)
            if not words:
                md.append("_(página sin capa de texto — requiere OCR)_")
                continue
            columnas: list = []        # bloque abierto más reciente por columna
            bloques: list = []         # bloques de la página (para cifras sin etiqueta)
            hubo_filas = False
            for fila in _filas(words):
                c0 = fila[0]
                n = norm(c0["t"])
                centro = ((c0["x0"] + c0["x1"]) / 2 - W / 2) / W
                # --- encabezado prellenado ("IVA personas morales") — ANTES que títulos
                if len(fila) == 1 and "PERSONAS" in n and impuesto_de(n):
                    impuesto = impuesto_de(n)
                    md.append(f"## {impuesto} — {c0['t']}")
                    columnas, hubo_filas, tabla = [], False, False
                    continue
                # --- título de sección -------------------------------------
                if (len(fila) == 1 and not re.search(r"\d", c0["t"])
                        and abs(centro) <= CENTRO and not n.startswith(ETIQUETAS)):
                    if n.startswith("DECLARACION PROVISIONAL"):
                        continue
                    imp = impuesto_de(n)
                    if imp:
                        impuesto = imp
                    if md and isinstance(md[-1], str) and md[-1].startswith("### ") and not hubo_filas:
                        md[-1] += f" — {c0['t']}"            # subtítulo
                    else:
                        if imp:
                            md.append(f"## {imp}")
                        md.append(f"### {c0['t']}")
                    seccion, tabla, hubo_filas = c0["t"], n.startswith(TITULOS_TABLA), False
                    if not tabla:
                        seccion_form = seccion
                    columnas = []
                    continue
                # --- concepto dentro de DETALLE DEL PAGO ("R21 IMPUESTO AL VALOR AGREGADO")
                if len(fila) == 1 and re.match(r"^R\d+\s", n) and impuesto_de(n.split(" ", 1)[1]):
                    impuesto = impuesto_de(n.split(" ", 1)[1])
                    md += [f"## {impuesto}", f"### {seccion}"]
                    columnas, hubo_filas = [], False
                    continue
                if n == "MES" and len(fila) > 1:              # tabla histórica
                    tabla = True
                    md.append("### HISTÓRICO (meses anteriores)")
                if tabla and _parece_formulario(fila):        # terminó la tabla
                    tabla = False
                    md.append(f"### {seccion_form}")
                    columnas, hubo_filas = [], False
                if tabla:
                    md.append("| " + " | ".join(c["t"] for c in fila) + " |")
                    continue
                # --- formulario: continuación + pares etiqueta | valor --------
                nueva, ult = [], None
                for c in fila:
                    if es_num(c["t"]):
                        dest = ult
                        if dest is None:              # cifra sin etiqueta a su izquierda
                            cands = [b for b in bloques[-12:] if b["x1"] < c["x0"]
                                     and b["top"] - TOL_Y <= c["top"] <= b["bot"] + TOL_Y]
                            dest = max(cands, key=lambda b: b["x1"]) if cands else None
                        if dest is None:
                            dest = _bloque(c, "")
                            nueva.append(dest)
                            bloques.append(dest)
                        if dest["v"] is None:
                            dest["v"] = c["t"]
                        ult = None
                        continue
                    arriba = next((b for b in columnas if abs(b["x0"] - c["x0"]) <= ALINEA_X
                                   and 0 <= c["top"] - b["bot"] <= CONT_Y), None)
                    if arriba is not None:            # texto justo debajo → misma fila
                        arriba["t"] += " " + c["t"]
                        arriba["bot"] = c["bot"]
                        arriba["x1"] = max(arriba["x1"], c["x1"])
                        ult = arriba
                    else:
                        b = _bloque(c)
                        nueva.append(b)
                        bloques.append(b)
                        columnas = [x for x in columnas if abs(x["x0"] - c["x0"]) > ALINEA_X] + [b]
                        ult = b
                if nueva:
                    md.append(nueva)
                    hubo_filas = True
            md.append("")
    out = []
    for item in md:
        if isinstance(item, list):
            out.append("| " + " | ".join(f"{b['t']} | {b['v'] or ''}" for b in item) + " |")
        else:
            out.append(item)
    return "\n".join(out)


def carpeta_md(rfc: str) -> Path:
    """%PROGRAMDATA%\\ConvertidorBancos\\declaraciones_md\\<RFC> (local, nunca OneDrive)."""
    base = os.environ.get("PROGRAMDATA") or os.path.expanduser("~")
    return Path(base) / "ConvertidorBancos" / "declaraciones_md" / (rfc or "SIN_RFC")


def ruta_md(rfc: str, archivo) -> Path:
    return carpeta_md(rfc) / (Path(archivo).stem + ".md")


def guardar_md(rfc: str, archivo, md: str) -> Path | None:
    """Guarda el MD para consulta ("Ver MD" en el visor). Falla en silencio."""
    try:
        p = ruta_md(rfc, archivo)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(md, encoding="utf-8")
        return p
    except OSError:
        return None
