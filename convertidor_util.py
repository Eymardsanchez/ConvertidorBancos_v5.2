"""Helpers del Convertidor extraídos TAL CUAL de ConvertidorSantander.py 5.0
(eran funciones de módulo junto a la interfaz tkinter)."""
from __future__ import annotations

import re as _re
from datetime import date

_FECHA_RE = _re.compile(r'FECHA\s+DE\s+CORTE\s+(\d{1,2})/(\d{2})/(\d{4})', _re.IGNORECASE)
_MESES_NUM = {"ENE": "01", "FEB": "02", "MAR": "03", "ABR": "04", "MAY": "05", "JUN": "06",
              "JUL": "07", "AGO": "08", "SEP": "09", "OCT": "10", "NOV": "11", "DIC": "12"}


def buscar_fecha_corte(pdf_path: str) -> str:
    import pdfplumber
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages[:4]:
                m = _FECHA_RE.search(page.extract_text() or "")
                if m:
                    return f"{m.group(3)}-{m.group(2)}"
    except Exception:
        pass
    return ""


def año_mes_fallback(periodo: str) -> str:
    m = _re.findall(r'(\d{1,2})/(\d{2})/(\d{4})', periodo)
    if m:
        _, mes, año = m[-1]
        return f"{año}-{mes}"
    m = _re.findall(r'(\d{1,2})/([A-Za-z]{3})/(\d{4})', periodo)
    if m:
        _, mt, año = m[-1]
        return f"{año}-{_MESES_NUM.get(mt.upper(), '01')}"
    m = _re.search(r'(\d{4})-(\d{2})', periodo)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    # 5.2 (alternativa agregada): "DEL 01-AGO-2026 AL 31-AGO-2026" (Santander, con
    # guiones). Sin esto caía a la fecha de HOY y el Excel iba al mes equivocado.
    m = _re.findall(r'(\d{1,2})-([A-Za-z]{3})-(\d{4})', periodo)
    if m:
        _, mt, año = m[-1]
        return f"{año}-{_MESES_NUM.get(mt.upper(), '01')}"
    return date.today().strftime("%Y-%m")


def safe_folder(name: str) -> str:
    s = _re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip('. ')
    return s or "Empresa"


if __name__ == "__main__":
    assert año_mes_fallback("PERIODO DEL 01-AGO-2026 AL 31-AGO-2026") == "2026-08"
    assert año_mes_fallback("DEL 01/07/2026 AL 31/07/2026") == "2026-07"
    assert año_mes_fallback("01/JUN/2026 al 30/JUN/2026") == "2026-06"
    assert safe_folder("A<B>:C") == "A_B__C"
    print("convertidor_util OK")
