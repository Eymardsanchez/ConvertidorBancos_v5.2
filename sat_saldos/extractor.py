"""Extracción de texto de PDF. Referencia: blueprint sección 8.

Preferencia: `pdftotext -layout` (poppler) por ser rápido y preservar columnas.
El modo raw solo se ejecuta para formatos que lo necesitan (rejilla y acuse de
pago); el resto de los PDFs evita un segundo proceso externo.
"""
from __future__ import annotations

import io
import shutil
import subprocess
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple


_FILE_ATTRIBUTE_OFFLINE = 0x1000
_FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000


def _esperar_local(ruta: Path, timeout: float = 60.0) -> None:
    """Espera a que OneDrive termine de descargar el archivo (Files On-Demand).

    Un PDF 'solo en la nube' tiene el atributo OFFLINE / RECALL_ON_DATA_ACCESS.
    OneDrive puede entregar datos ANTES de terminar la descarga, y pdftotext
    recibe un PDF truncado (texto degradado → 0 detalles). Aquí forzamos la
    descarga (leyendo un bloque) y esperamos hasta que el atributo se despeje.
    """
    import ctypes
    import time
    try:
        getatt = ctypes.windll.kernel32.GetFileAttributesW  # type: ignore[attr-defined]
    except Exception:
        return  # no-Windows: nada que esperar
    fin = time.monotonic() + timeout
    while time.monotonic() < fin:
        attr = getatt(str(ruta))
        if attr == -1:
            return
        en_nube = attr & (_FILE_ATTRIBUTE_OFFLINE | _FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS)
        if not en_nube:
            return  # ya está completamente local
        # Dispara la descarga leyendo el contenido y espera a que baje.
        try:
            with open(ruta, "rb") as fh:
                while fh.read(1024 * 1024):
                    pass
        except OSError:
            pass
        time.sleep(0.5)


def _leer_bytes(ruta: Path) -> bytes:
    """Lee el PDF COMPLETO a memoria, tras asegurar que OneDrive lo bajó entero.

    Síntoma que resuelve: 'no carga la información / 0 detalles' intermitente
    cuando los PDF están en OneDrive 'solo en la nube' y se leen a medio bajar.
    """
    import time
    _esperar_local(ruta)
    ultimo = b""
    for _ in range(4):
        try:
            data = Path(ruta).read_bytes()
        except OSError:
            time.sleep(0.5)
            continue
        # PDF íntegro: empieza en '%PDF' y trae '%%EOF' cerca del final.
        if data[:4] == b"%PDF" and b"%%EOF" in data[-2048:]:
            return data
        ultimo = data or ultimo
        time.sleep(0.5)
    return ultimo


def pdf_bytes(ruta: Path) -> bytes:
    """Bytes completos del PDF (hidrata OneDrive si es 'solo en la nube')."""
    return _leer_bytes(ruta)


def _pdf_completo(data: bytes) -> bool:
    return data[:4] == b"%PDF" and b"%%EOF" in data[-4096:]


@lru_cache(maxsize=1)
def _pdftotext_bin() -> str | None:
    """Ruta al binario pdftotext, aunque NO esté en el PATH.

    Causa de fallo real: la app lanzada por doble-clic no ve el pdftotext que sí
    está (p. ej. el que trae Git en mingw64), cae a pdfplumber y el texto sale
    'pegado' sin espacios → 0 detalles. Aquí lo buscamos en ubicaciones comunes.

    Cacheado: se llama 1-2 veces POR PDF; sin caché, cuando pdftotext no está en
    PATH (el caso del GUI por doble-clic) el glob recursivo sobre C:\\Program
    Files\\** se repetía en cada lote de PDFs y disparaba la lentitud de carga.
    La ruta del binario no cambia durante la corrida.
    """
    exe = shutil.which('pdftotext')
    if exe:
        return exe
    import glob
    candidatos = [
        r"C:\Program Files\Git\mingw64\bin\pdftotext.exe",
        r"C:\Program Files\Git\usr\bin\pdftotext.exe",
        r"C:\Program Files (x86)\Git\mingw64\bin\pdftotext.exe",
    ]
    for patron in (r"C:\Program Files\poppler*\**\pdftotext.exe",
                   r"C:\poppler*\**\pdftotext.exe",
                   r"C:\Program Files\**\pdftotext.exe"):
        try:
            candidatos += glob.glob(patron, recursive=True)
        except Exception:
            pass
    for c in candidatos:
        if Path(c).exists():
            return c
    return None


def _pdftotext(data: bytes, *args: str) -> str:
    """Corre pdftotext sobre un archivo TEMPORAL LOCAL con los bytes dados.

    Temporal local (no la ruta OneDrive) para que poppler no tome un placeholder
    a medio bajar. Usa `_pdftotext_bin()` para hallar el binario aunque no esté
    en el PATH del proceso.
    """
    exe = _pdftotext_bin()
    if not exe:
        return ""
    import os
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".pdf")
    try:
        with os.fdopen(fd, 'wb') as fh:
            fh.write(data)
        out = subprocess.run([exe, *args, tmp, '-'], capture_output=True)
        return _decodifica(out.stdout or b"")
    except Exception:
        return ""
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _decodifica(data: bytes) -> str:
    """Decodifica la salida de pdftotext probando UTF-8 y luego cp1252/latin-1.

    Algunos builds de poppler (p. ej. en Windows) emiten Latin-1/cp1252 en vez
    de UTF-8; decodificar mal corrompe los acentos y rompe los regex de parseo.
    """
    for enc in ('utf-8', 'cp1252', 'latin-1'):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode('latin-1', errors='replace')


class TextosPDF(NamedTuple):
    """Las dos vistas de texto que usan los parsers del módulo SAT."""
    layout: str
    raw: str
    uso_ocr: bool = False


def _texto_suficiente(texto: str) -> bool:
    """Detecta una capa de texto utilizable antes de intentar OCR.

    Los acuses SAT tienen texto digital aunque incluyan logotipos o firmas como
    imágenes. Se exige contenido y dos identificadores SAT para no clasificar
    como válido un PDF con una capa corrupta o meramente decorativa.
    """
    limpio = ' '.join(texto.split())
    if len(limpio) < 200:
        return False
    marcas = (
        'RFC', 'DECLARACIÓN', 'DECLARACION', 'NÚMERO DE OPERACIÓN',
        'NUMERO DE OPERACION', 'IMPUESTO', 'SALDO', 'PERÍODO', 'PERIODO',
        'PAGO', 'ACUSE',
    )
    return sum(1 for marca in marcas if marca in limpio.upper()) >= 2


def _requiere_raw(layout: str) -> bool:
    """Indica si el PDF usa campos cuya lectura depende del orden de flujo."""
    normalizado = unicodedata.normalize('NFKD', layout)
    normalizado = ''.join(c for c in normalizado if not unicodedata.combining(c))
    upper = normalizado.upper()
    es_pago = (
        'REGISTRADA DE PAGOS DE CONTRIBUCIONES' in upper
        and 'LINEA DE CAPTURA' in upper
    )
    es_rejilla = (
        'CONCEPTO DE PAGO' in upper
        and ('A CARGO' in upper or 'A FAVOR' in upper)
    )
    return es_pago or es_rejilla


def _extraer_vistas(data: bytes) -> tuple[str, str]:
    """Extrae layout siempre y raw solo si el parser SAT lo requiere."""
    layout = _pdftotext(data, '-layout')
    raw = _pdftotext(data) if layout.strip() and _requiere_raw(layout) else ""
    return layout, raw


def _extraer_con_ocr(ruta: Path) -> TextosPDF | None:
    """OCR de respaldo para un PDF sin capa de texto SAT utilizable."""
    try:
        # El OCR existente genera un PDF buscable, conservando la geometría
        # que esperan pdfplumber y los parsers actuales.
        from ocr_pdf import ocr_a_pdf_buscable
    except ImportError:
        return None
    temporal = ocr_a_pdf_buscable(str(ruta), dpi=300)
    if not temporal:
        return None
    try:
        data = Path(temporal).read_bytes()
        if not _pdf_completo(data):
            return None
        layout, raw = _extraer_vistas(data)
        return TextosPDF(layout, raw, True) if layout.strip() else None
    finally:
        try:
            Path(temporal).unlink()
        except OSError:
            pass


def pdf_a_textos(ruta: Path) -> TextosPDF:
    """Extrae layout/raw con pdftotext y usa OCR únicamente como respaldo.

    Lanza excepción solo si ninguna vía está disponible; un PDF sin capa de
    texto devuelve cadena vacía (el llamador decide cómo reportarlo).
    """
    data = _leer_bytes(ruta)
    # Si el PDF no llegó completo (OneDrive a medio bajar), NO lo leas a medias:
    # devolver "" hace que el pipeline lo marque 'no legible' en vez de clasificarlo mal.
    if not _pdf_completo(data):
        return TextosPDF("", "")
    layout, raw = _extraer_vistas(data)
    # Respaldo pdfplumber (si no hay pdftotext): x_tolerance evita que pegue las
    # palabras (sin espacios rompe la detección → 0 detalles).
    if not layout.strip():
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(data)) as pdf:
                layout = '\n'.join((p.extract_text(x_tolerance=1.5) or '')
                                   for p in pdf.pages)
                raw = layout
        except Exception:
            pass
    layout = unicodedata.normalize('NFKC', layout)
    raw = unicodedata.normalize('NFKC', raw)
    if _texto_suficiente(layout):
        return TextosPDF(layout, raw)
    ocr = _extraer_con_ocr(ruta)
    return ocr or TextosPDF(layout, raw)


def pdf_a_texto(ruta: Path) -> str:
    """Compatibilidad: devuelve la vista layout de un PDF."""
    return pdf_a_textos(ruta).layout


def pdf_a_texto_raw(ruta: Path) -> str:
    """Texto de pdftotext SIN -layout (modo de flujo).

    Algunos acuses del SAT tienen las columnas de conceptos en una rejilla que
    `-layout` entrelaza y vuelve ambigua; el modo de flujo las devuelve como
    'línea de etiquetas' + 'línea de datos', mucho más fácil de parsear.
    """
    data = _leer_bytes(ruta)
    if not _pdf_completo(data):
        return ""
    return unicodedata.normalize('NFKC', _pdftotext(data))  # sin -layout


def iter_pdfs(carpeta: Path):
    """Itera recursivamente los .pdf de una carpeta (orden estable)."""
    yield from sorted(carpeta.rglob('*.pdf'))
