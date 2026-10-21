"""
Extractor para estados de cuenta BBVA México (Cuenta Maestra PYME y similares).
Formato: DD/MMM  DD/MMM  COD  DESCRIPCION  [CARGO|ABONO]  [SALDO_OPER]  [SALDO_LIQ]
La página 1 es imagen (sin texto). Encabezado en página 2 (HEADER_PAGE = 1).
Hereda de BancoEstandar (bancos/estandar.py).
"""

import re
from typing import Optional

import pdfplumber

from bancos.estandar import BancoEstandar, _agrupar_renglones, _norm_hdr
from bancos.base import Movimiento, InfoCuenta

AMOUNT_RE = re.compile(r"([\d,]+\.\d{2})")
_MONTO_WORD_RE = re.compile(r"\d[\d,]*\.\d{2}")
_FECHA_WORD_RE = re.compile(r"^\d{2}/[A-Z]{3}$")


def _lados_por_columna(pdf_path: str) -> list[tuple[int, str]]:
    """[(centavos, 'retiro'|'deposito')] de cada renglón de movimiento, en orden
    del documento, según la COLUMNA donde BBVA imprime el importe (CARGOS/ABONOS).
    Las columnas se ubican con el renglón de encabezado que trae CARGOS y ABONOS
    juntos (el resumen de la pág. 2 también dice "Cargos"/"Abonos" y engañaba).
    Nunca lanza: ante cualquier problema devuelve [] y se clasifica como antes."""
    lados: list[tuple[int, str]] = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                words = page.extract_words(x_tolerance=1.5, y_tolerance=3,
                                           use_text_flow=False)
                cols = None
                for row in _agrupar_renglones(words or []):
                    hdr = {_norm_hdr(w["text"]): (w["x0"] + w["x1"]) / 2 for w in row}
                    if "CARGOS" in hdr and "ABONOS" in hdr:
                        cols = [("retiro", hdr["CARGOS"]), ("deposito", hdr["ABONOS"])]
                        cols += [("saldo", cx) for h, cx in hdr.items()
                                 if h in ("OPERACIÓN", "OPERACION", "LIQUIDACIÓN", "LIQUIDACION")]
                        continue
                    if not cols or len(row) < 2 or not all(
                            _FECHA_WORD_RE.match(w["text"]) for w in row[:2]):
                        continue
                    for w in row[2:]:
                        t = w["text"].replace(",", "")
                        if not _MONTO_WORD_RE.fullmatch(t):
                            continue
                        cx = (w["x0"] + w["x1"]) / 2
                        lado, cc = min(cols, key=lambda c: abs(cx - c[1]))
                        if lado != "saldo" and abs(cx - cc) < 45:
                            lados.append((int(round(float(t) * 100)), lado))
                            break
    except Exception:
        return []
    return lados

MESES = {
    "ENE": "01", "FEB": "02", "MAR": "03", "ABR": "04", "MAY": "05",
    "JUN": "06", "JUL": "07", "AGO": "08", "SEP": "09", "OCT": "10",
    "NOV": "11", "DIC": "12",
}

# ABONO = depósito / crédito
ABONO_KW = {
    "VENTAS", "ABONO", "DEPOSITO", "BONIFICACION",
    "VENTA NAL", "VENTAS TDC", "VENTA INTER",
    "RECIBIDO",   # T20: SPEI RECIBIDO = transferencia entrante
    "DEVUELTO",   # T22: SPEI devuelto por banco destino
}
# CARGO = retiro / débito
CARGO_KW = {
    "ENVIADO", "PAGO", "APLI TASA", "IVA COM", "IVA TASA",
    "SERV BANCA", "ANUALIDAD", "COMISION", "CARGO", "RETIRO",
    "COBRANZA", "NETFLIX", "SPOTIFY", "AMAZON",
    "COM VTAS",   # I73: comisión sobre ventas TDC internacional
    "COM. VTA",   # K59/K65: comisión AMEX
}

SKIP_PATTERNS = [
    "ESTADO DE CUENTA", "MAESTRA PYME", "PAGINA", "PERIODO DEL",
    "RENDIMIENTO", "COMPORTAMIENTO", "INFORMACION FINANCIERA",
    "SALDO PROMEDIO", "DIAS DEL PERIODO", "TASA BRUTA",
    "INTERESES A FAVOR", "ISR RETENIDO", "COMISIONES",
    "DEPOSITOS / ABONOS", "RETIROS / CARGOS", "SALDO FINAL",
    # _es_skip compara en MAYÚSCULAS: todo patrón debe ir en mayúsculas.
    "NO. DE CUENTA", "NO. DE CLIENTE", "R.F.C", "SUCURSAL",
    "DOMICILIO FISCAL", "PLAZA:", "TELEFONO", "ESTIMADO CLIENTE",
    "SU ESTADO DE CUENTA", "LA GAT REAL",
    "FECHA SALDO", "OPER LIQ COD",
    # Pie de página y encabezado corto de las páginas 3+ (se pegaban a la
    # descripción del último movimiento de la página anterior).
    "LE INFORMAMOS QUE SU CONTRATO", "CONSULTARLO EN CUALQUIER SUCURSAL",
    "CON BBVA ADELANTE", "INSTITUCION DE BANCA MULTIPLE",
    "NO. CUENTA", "NO. CLIENTE",
]

SALDO_INI_RE = re.compile(
    r"Saldo de (?:Liquidaci[oó]n|Operaci[oó]n) Inicial\s+([\d,]+\.\d{2})"
)


class BBVAExtractor(BancoEstandar):
    NOMBRE        = "BBVA"
    COLOR_HEX     = "004481"
    # Sólo captura los tres tokens de encabezado; el resto queda en `resto`
    DATE_RE       = re.compile(
        r"^(\d{2}/[A-Z]{3})\s+(\d{2}/[A-Z]{3})\s+([A-Z0-9]{2,3})\s+"
    )
    SECTION_RE    = re.compile(r"OPER\s+LIQ\s+COD")
    SKIP_PATTERNS = SKIP_PATTERNS
    END_PATTERNS  = [
        "Total de Movimientos",   # encabezado de la sección de totales BBVA
        "TOTAL IMPORTE CARGOS",   # líneas de totales (por si aparecen antes)
    ]
    HEADER_PAGE   = 1   # página 1 tiene el encabezado; página 0 es imagen

    @classmethod
    def detectar(cls, texto: str) -> bool:
        header = texto[:800]
        return (
            "BBVA" in header
            and ("MAESTRA PYME" in header
                 or "GRUPO FINANCIERO BBVA" in header
                 or "ESTADO DE CUENTA" in header)
            and "INBURSA" not in header
            and "SANTANDER" not in header
        )

    def extraer(self, pdf_path, progress_callback=None):
        self._lados, self._i_lado = _lados_por_columna(pdf_path), 0
        return super().extraer(pdf_path, progress_callback)

    def _lado_columna(self, monto: float) -> Optional[str]:
        """Columna real del importe (siguiente renglón de movimiento). Exige que
        el importe coincida; si un renglón no casó, busca hasta 3 adelante."""
        lados, i = getattr(self, "_lados", []), getattr(self, "_i_lado", 0)
        cents = int(round(monto * 100))
        for j in range(i, min(i + 4, len(lados))):
            if lados[j][0] == cents:
                self._i_lado = j + 1
                return lados[j][1]
        return None

    # ── Hooks ────────────────────────────────────────────────────────────────

    def _parse_fecha(self, match: re.Match) -> str:
        """Convierte DD/MMM (fecha operación) a DD/MM."""
        parts = match.group(1).split("/")
        if len(parts) == 2:
            mes_num = MESES.get(parts[1], parts[1])
            return f"{parts[0]}/{mes_num}"
        return match.group(1)

    def _es_saldo_anterior(self, linea: str) -> Optional[float]:
        m = SALDO_INI_RE.search(linea)
        if m:
            return float(m.group(1).replace(",", ""))
        return None

    def _parse_linea(self, match: re.Match, resto: str,
                     prev_saldo: Optional[float]) -> Optional[Movimiento]:
        """BBVA puede tener 3 importes: monto + saldo_operación + saldo_liquidación."""
        fecha = self._parse_fecha(match)
        code  = match.group(3)

        amounts = AMOUNT_RE.findall(resto)
        saldo_liq = None

        if len(amounts) >= 3:
            amount_val = float(amounts[-3].replace(",", ""))
            saldo_oper = float(amounts[-2].replace(",", ""))
            saldo_liq  = float(amounts[-1].replace(",", ""))
            last_pos   = resto.rfind(amounts[-3])
            desc_raw   = resto[:last_pos].strip()
            saldo_final = saldo_oper
        elif len(amounts) == 2:
            amount_val  = float(amounts[-2].replace(",", ""))
            saldo_final = float(amounts[-1].replace(",", ""))
            last_pos    = resto.rfind(amounts[-2])
            desc_raw    = resto[:last_pos].strip()
        elif len(amounts) == 1:
            amount_val  = float(amounts[0].replace(",", ""))
            saldo_final = None
            last_pos    = resto.rfind(amounts[0])
            desc_raw    = resto[:last_pos].strip()
        else:
            return Movimiento(fecha=fecha, folio=code, descripcion=resto)

        desc_raw = re.sub(r"\s+", " ", desc_raw).strip()
        # La COLUMNA donde el banco imprimió el importe manda; si no se pudo
        # leer, se clasifica como antes (balance → mapa → palabras clave).
        kind = (self._lado_columna(amount_val)
                or self._clasificar(amount_val, prev_saldo, saldo_final,
                                    code + " " + desc_raw, fecha=fecha))

        liq = match.group(2).split("/")
        mov = Movimiento(fecha=fecha, folio=code, descripcion=desc_raw,
                         saldo=saldo_final, saldo_liq=saldo_liq,
                         fecha_liq=f"{liq[0]}/{MESES.get(liq[1], liq[1])}")
        if kind == "deposito":
            mov.deposito = amount_val
        else:
            mov.retiro = amount_val
        return mov

    def _clasificar_keywords(self, desc: str) -> str:
        upper = desc.upper()
        for kw in ABONO_KW:
            if kw in upper:
                return "deposito"
        for kw in CARGO_KW:
            if kw in upper:
                return "retiro"
        return "retiro"

    def _parse_encabezado(self, texto: str, info: InfoCuenta) -> None:
        for line in texto.splitlines():
            line = line.strip()
            if not info.periodo and "PERIODO DEL" in line.upper():
                info.periodo = line
            if not info.numero_cuenta and "No. de Cuenta" in line:
                m = re.search(r"No\.\s*de\s*Cuenta\s+(\d+)", line)
                if m:
                    info.numero_cuenta = m.group(1)
            if not info.rfc and "R.F.C" in line.upper():
                m = re.search(r"R\.F\.C\s+([A-Z0-9]{10,13})", line.upper())
                if m:
                    info.rfc = m.group(1)
            if not info.clabe and "CLABE" in line.upper():
                m = re.search(r"\b(\d{18})\b", line)
                if m:
                    info.clabe = m.group(1)
