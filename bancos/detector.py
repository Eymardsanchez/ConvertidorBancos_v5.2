"""
Detecta automáticamente qué banco corresponde a un PDF y retorna el extractor correcto.
Para agregar un banco nuevo: crear su módulo en /bancos/ y registrarlo en EXTRACTORES,
_IBM_MAP y _RAZONES_SOCIALES.

Estrategia de detección (tres fases):
  1ª PRIORIDAD — RAZÓN SOCIAL de la institución (_RAZONES_SOCIALES, todos los bancos
     de México): "Banco Mercantil del Norte, S.A., Institución de Banca Múltiple…".
     Se busca en las 4 primeras hojas + las 2 últimas, tolerando palabras pegadas y
     letras perdidas. Banco sin parser propio → genérico. NO se usa el nombre
     comercial (las contrapartes SPEI lo engañaban: Banorte salía como BBVA).

  2ª PRIORIDAD (respaldo) — Ancla "Institución de Banca Múltiple":
     En el pie/encabezado de cada página de un estado de cuenta mexicano siempre
     aparece la leyenda:
         <NOMBRE BANCO>  S.A.,  Institución de Banca Múltiple  <GRUPO> …
     Se busca la palabra pivote "INSTITUC…" y se toma todo lo que está a su
     IZQUIERDA en la misma línea: eso es el nombre oficial del banco.
     Esta estrategia es inmune a falsos positivos por SPEIs/transferencias a
     otros bancos que aparezcan en el cuerpo de las transacciones.

  3ª PRIORIDAD — Fallback por keywords en texto completo:
     Si ninguna fase anterior identificó al banco, se corre cada
     extractor.detectar() en el orden de EXTRACTORES.
"""

import threading
import pdfplumber
from bancos.base import BancoExtractor

# ── Lock global compartido ────────────────────────────────────────────────────
# pdfminer mantiene caché de fuentes a nivel de proceso. Serializar TODA apertura
# de PDF (detección y extracción) evita corrupción cuando hay múltiples hilos.
# Se usa RLock (reentrant) para que el mismo hilo pueda adquirirlo varias veces
# sin deadlock (p.ej. cuando _detect() adquiere el lock y llama a detectar_banco
# que también lo adquiere internamente).
PDF_LOCK = threading.RLock()

from bancos.santander import SantanderExtractor
from bancos.bbva      import BBVAExtractor
from bancos.banregio  import BanregioExtractor
from bancos.inbursa   import InbursaExtractor
from bancos.banorte   import BanorteExtractor
from bancos.banbajio  import BanbajioExtractor
from bancos.hsbc      import HSBCExtractor
from bancos.banamex   import BanamexExtractor
from bancos.konfio    import KonfioExtractor

# ── Registro de extractores (fallback) ───────────────────────────────────────
# Sólo se usa si la estrategia IBM no logra identificar el banco.
# ORDEN: más específicos primero para evitar falsos positivos.
# Konfio va primero: es SOFOM (sin leyenda IBM) y usa "KONFIO"/"RED AMIGO DAL"
# que son tokens muy específicos — no confunden con ningún banco tradicional.
EXTRACTORES: list[type[BancoExtractor]] = [
    KonfioExtractor,     # "KONFIO" / "RED AMIGO DAL" — SOFOM TC, sin IBM
    InbursaExtractor,    # "CLIENTE INBURSA" + "BALANCE INICIAL" — muy específico
    BanregioExtractor,   # "BANREGIO" / "BANCO REGIONAL"
    BanorteExtractor,    # "BANCO MERCANTIL DEL NORTE" / "ENLACE NEGOCIOS/GLOBAL"
    BanbajioExtractor,   # "BANBAJIO" / "BANCO DEL BAJIO"
    SantanderExtractor,  # "BANCO SANTANDER" / "SANTANDER MEXICO"
    BBVAExtractor,       # "BBVA" — antes que Banamex para evitar falso positivo
    BanamexExtractor,    # "BANAMEX" / "CITIBANAMEX" — sólo busca en encabezado
    HSBCExtractor,       # (cid: en texto crudo — al final
]

# ── Mapa IBM: prefijos del nombre oficial → extractor ─────────────────────────
# Se compara contra el texto normalizado (mayúsculas, sin acentos) que aparece
# a la izquierda de "INSTITUC…" en el pie de página.
# Ordenado de más específico a más general para evitar coincidencias parciales.
_IBM_MAP: list[tuple[str, type[BancoExtractor]]] = [
    # Banamex  (antes que variante genérica "BANCO NACIONAL")
    ("BANCO NACIONAL DE MEXICO",   BanamexExtractor),
    ("CITIBANAMEX",                BanamexExtractor),
    ("BANAMEX",                    BanamexExtractor),
    # Banorte  (razón social completa — evita confusión con "BANCO" genérico)
    ("BANCO MERCANTIL DEL NORTE",  BanorteExtractor),
    ("BANORTE",                    BanorteExtractor),
    # Banregio
    ("BANCO REGIONAL DE MONTERREY", BanregioExtractor),
    ("BANCO REGIONAL",             BanregioExtractor),
    ("BANREGIO",                   BanregioExtractor),
    # Banbajío
    ("BANCO DEL BAJIO",            BanbajioExtractor),
    ("BANBAJIO",                   BanbajioExtractor),
    # Santander
    ("BANCO SANTANDER MEXICO",     SantanderExtractor),
    ("BANCO SANTANDER",            SantanderExtractor),
    ("SANTANDER",                  SantanderExtractor),
    # BBVA  (razón social: "BBVA MEXICO, S.A., IBM…")
    ("BBVA",                       BBVAExtractor),
    # HSBC
    ("HSBC MEXICO",                HSBCExtractor),
    ("HSBC",                       HSBCExtractor),
    # Inbursa  (algunos formatos usan IBM aunque Inbursa también tiene su leyenda propia)
    ("BANCO INBURSA",              InbursaExtractor),
    ("INBURSA",                    InbursaExtractor),
]

# ── Detección por NOMBRE COMERCIAL (estrategia principal) ─────────────────────
# Se elige el banco cuyo NOMBRE COMERCIAL aparece MÁS veces en las primeras
# páginas: el nombre propio se repite en encabezado/pie de CADA hoja, mientras
# que un banco mencionado por un SPEI aparece sólo en esa transacción. Así una
# mención aislada (p.ej. "RECIBIDO DE BANORTE") no gana sobre el banco real.
# Cada banco trae sus tokens (normalizados, sin acentos) y su extractor, o None
# si aún no hay parser propio (se detecta el nombre, la extracción cae al genérico
# en vez de enrutar mal a otro banco). `tokens`: se cuenta el de MAYOR frecuencia
# (no se suman, para no duplicar alias que se contienen, p.ej. CITIBANAMEX⊃BANAMEX).
_BANCOS_MX: list[tuple[str, tuple[str, ...], type[BancoExtractor] | None]] = [
    # — Con parser propio —
    ("Santander",   ("SANTANDER",),                         SantanderExtractor),
    ("BBVA",        ("BBVA", "BANCOMER"),                    BBVAExtractor),
    ("Banorte",     ("BANORTE",),                            BanorteExtractor),
    ("Banregio",    ("BANREGIO", "HEY BANCO"),               BanregioExtractor),
    ("Banbajío",    ("BANBAJIO", "BANCO DEL BAJIO"),         BanbajioExtractor),
    ("Inbursa",     ("INBURSA",),                            InbursaExtractor),
    ("HSBC",        ("HSBC",),                               HSBCExtractor),
    ("Banamex",     ("CITIBANAMEX", "BANAMEX"),              BanamexExtractor),
    ("Konfío",      ("KONFIO", "RED AMIGO DAL"),             KonfioExtractor),
    # — Sin parser propio (se reconoce el nombre → extracción genérica) —
    ("Scotiabank",  ("SCOTIABANK", "SCOTIA"),                None),
    ("Afirme",      ("AFIRME",),                             None),
    ("Banco Azteca",("BANCO AZTECA", "BANCOAZTECA"),         None),
    ("BanCoppel",   ("BANCOPPEL",),                          None),
    ("Mifel",       ("MIFEL",),                              None),
    ("Multiva",     ("MULTIVA",),                            None),
    ("Banjército",  ("BANJERCITO", "BANCO NACIONAL DEL EJERCITO"), None),
    ("Bansí",       ("BANSI",),                              None),
    ("CIBanco",     ("CIBANCO",),                            None),
    ("Intercam",    ("INTERCAM",),                           None),
    ("Ve por Más",  ("VE POR MAS", "BANCO VE POR MAS"),      None),
    ("Actinver",    ("ACTINVER",),                           None),
    ("Compartamos", ("COMPARTAMOS",),                        None),
    ("Monex",       ("MONEX",),                              None),
    ("Sabadell",    ("SABADELL",),                           None),
    ("Banco Base",  ("BANCO BASE",),                         None),
    ("Covalto",     ("COVALTO", "BANCREA"),                  None),
    ("Finterra",    ("FINTERRA",),                           None),
    ("Accendo",     ("ACCENDO",),                            None),
    ("Bankaool",    ("BANKAOOL",),                           None),
    ("Autofin",     ("BANCO AUTOFIN", "AUTOFIN"),            None),
    ("BanBajío BX+",("BX+",),                                None),
    ("American Express", ("AMERICAN EXPRESS",),              None),
    ("Mercado Pago",("MERCADO PAGO",),                       None),
    ("Nu",          ("NU MEXICO", "NUBANK"),                 None),
    ("STP",         ("STP", "SISTEMA DE TRANSFERENCIAS"),    None),
]


def _detectar_por_nombre(texto_norm: str):
    """(extractor_class|None, nombre, conteo) del banco comercial DOMINANTE, o
    (None, None, 0) si ningún nombre de la lista aparece."""
    mejor = (None, None, 0)
    for nombre, tokens, extractor in _BANCOS_MX:
        cnt = max((texto_norm.count(t) for t in tokens), default=0)
        if cnt > mejor[2]:
            mejor = (extractor, nombre, cnt)
    return mejor


# ── Helpers estrategia IBM ────────────────────────────────────────────────────

def _norm(s: str) -> str:
    """Normaliza a mayúsculas y reemplaza vocales acentuadas y Ñ."""
    tr = str.maketrans(
        "ÁÉÍÓÚÜÑáéíóúüñ",
        "AEIOUUNaeiouun"
    )
    return s.upper().translate(tr)


def _detectar_por_ibm(
    page_words: list[list[dict]],
) -> type[BancoExtractor] | None:
    """
    Recorre las palabras extraídas de cada página buscando el pivote IBM.
    Retorna la CLASE del extractor (no una instancia) o None si no lo encuentra.

    Algoritmo:
      1. Buscar cualquier palabra cuyo texto normalizado empiece con "INSTITUC".
      2. Verificar que en la misma línea (y ± 3 pt) aparezcan "BANCA" y "MULTIPLE"
         (descarta coincidencias espurias con otras palabras que empiecen con "INSTITUC").
      3. Recolectar todas las palabras de esa línea cuya x0 sea MENOR que la del
         pivote (= el nombre del banco) y unirlas en un string normalizado.
      4. Buscar ese string en _IBM_MAP usando startswith para tolerancia a sufijos
         como "S.A.", comas, abreviaciones de grupo financiero, etc.
    """
    for words in page_words:
        if not words:
            continue

        for w in words:
            if not _norm(w["text"]).startswith("INSTITUC"):
                continue

            # Palabras en la misma línea (tolerancia ±3 pt en centro vertical)
            y_center = (w["top"] + w["bottom"]) / 2
            same_line = [
                x for x in words
                if abs((x["top"] + x["bottom"]) / 2 - y_center) < 3
            ]
            line_norm = " ".join(_norm(x["text"]) for x in same_line)

            # Confirmar que es realmente la leyenda IBM
            if "BANCA" not in line_norm or "MULTIPLE" not in line_norm:
                continue

            # Palabras a la IZQUIERDA del pivote (x0 < pivote_x0 con margen de 1 pt)
            pivot_x = w["x0"]
            left_words = sorted(
                [x for x in same_line if x["x0"] < pivot_x - 1],
                key=lambda x: x["x0"],
            )
            if not left_words:
                continue

            bank_raw = " ".join(_norm(x["text"]) for x in left_words)
            # Limpiar comas, puntos, "S.A." y variantes al final
            # (p. ej. "BBVA MEXICO, S.A.," → "BBVA MEXICO")
            import re as _re
            bank_clean = _re.sub(
                r"[\s,\.]*S\.?\s*A\.?[\s,\.]*$",
                "",
                bank_raw,
            ).strip(" ,.")

            # Buscar en el mapa (el más específico primero)
            for prefix, cls in _IBM_MAP:
                if bank_clean.startswith(prefix):
                    return cls

            # Mapa no reconoce el banco — seguir con fallback
            # (No retornamos None aquí; puede haber más páginas por revisar)

    return None


# ── Detección por RAZÓN SOCIAL de la institución (estrategia 1) ─────────────────
# El banco emisor del estado de cuenta imprime su denominación completa
# ("Banco Mercantil del Norte, S.A., Institución de Banca Múltiple, Grupo
# Financiero Banorte"); los bancos de las contrapartes (SPEI, CLABE) aparecen solo
# con su nombre corto ("BCO:0012 BBVA MEXICO"), NUNCA seguido de ", S.A.". Por eso
# se busca la denominación + "S.A." (o "Sociedad Nacional de Crédito" en banca de
# desarrollo). Fuente: Catálogo de bancos (gob.mx) + padrón vigente de banca múltiple
# (CNBV, 54 instituciones) y banca de desarrollo. Incluye denominaciones anteriores
# (BBVA Bancomer, Banco Regional de Monterrey, IXE, etc.) para estados de cuenta
# viejos. Sin parser propio → None (el llamador usa el genérico).
_RAZONES_SOCIALES: list[tuple[str, tuple[str, ...], type[BancoExtractor] | None]] = [
    # — Con parser propio —
    ("Banorte",     ("BANCO MERCANTIL DEL NORTE",),                       BanorteExtractor),
    ("BBVA",        ("BBVA MEXICO", "BBVA BANCOMER"),                     BBVAExtractor),
    ("Santander",   ("BANCO SANTANDER MEXICO", "BANCO SANTANDER"),        SantanderExtractor),
    ("Banamex",     ("BANCO NACIONAL DE MEXICO",),                        BanamexExtractor),
    ("HSBC",        ("HSBC MEXICO",),                                     HSBCExtractor),
    ("Banbajío",    ("BANCO DEL BAJIO",),                                 BanbajioExtractor),
    ("Inbursa",     ("BANCO INBURSA",),                                   InbursaExtractor),
    ("Banregio",    ("BANCO REGIONAL DE MONTERREY", "BANCO REGIONAL"),    BanregioExtractor),
    # — Banca múltiple sin parser propio → genérico —
    ("Scotiabank",  ("SCOTIABANK INVERLAT",),                             None),
    ("Citi México", ("BANCO CITI MEXICO",),                               None),
    ("Banco Azteca", ("BANCO AZTECA",),                                   None),
    ("Afirme",      ("BANCA AFIRME", "BANCO DE INVERSION AFIRME"),        None),
    ("Monex",       ("BANCO MONEX",),                                     None),
    ("Invex",       ("BANCO INVEX",),                                     None),
    ("Mifel",       ("BANCA MIFEL",),                                     None),
    ("J.P. Morgan", ("BANCO J P MORGAN",),                                None),
    ("Banco Base",  ("BANCO BASE",),                                      None),
    ("Multiva",     ("BANCO MULTIVA",),                                   None),
    ("BanCoppel",   ("BANCOPPEL",),                                       None),
    ("Bank of America", ("BANK OF AMERICA MEXICO",),                      None),
    ("Sabadell",    ("BANCO SABADELL",),                                  None),
    ("Ve por Más",  ("BANCO VE POR MAS",),                                None),
    ("Barclays",    ("BARCLAYS BANK MEXICO",),                            None),
    ("Compartamos", ("BANCO COMPARTAMOS",),                               None),
    ("KPTL",        ("KPTL MEXICO BANK",),                                None),
    ("Bansí",       ("BANSI",),                                           None),
    ("Bancrea",     ("BANCO BANCREA",),                                   None),
    ("Actinver",    ("BANCO ACTINVER",),                                  None),
    ("Consubanco",  ("CONSUBANCO",),                                      None),
    ("MUFG",        ("MUFG BANK MEXICO", "BANK OF TOKYO MITSUBISHI UFJ MEXICO"), None),
    ("Bankaool",    ("BANKAOOL",),                                        None),
    ("BNP Paribas", ("BNP PARIBAS MEXICO",),                              None),
    ("Openbank",    ("OPENBANK MEXICO",),                                 None),
    ("Banco Plata", ("BANCO PLATA",),                                     None),
    ("Banco Inmobiliario", ("BANCO INMOBILIARIO MEXICANO",),              None),
    ("Hey Banco",   ("HEY BANCO",),                                       None),
    ("Mizuho",      ("MIZUHO BANK MEXICO",),                              None),
    ("ICBC",        ("INDUSTRIAL AND COMMERCIAL BANK OF CHINA MEXICO",),  None),
    ("Covalto",     ("BANCO COVALTO",),                                   None),
    ("Volkswagen Bank", ("VOLKSWAGEN BANK",),                             None),
    ("S3 Caceis",   ("BANCO S3 CACEIS MEXICO",),                          None),
    ("Shinhan",     ("BANCO SHINHAN DE MEXICO",),                         None),
    ("Bank of China", ("BANK OF CHINA MEXICO",),                          None),
    ("Ualá",        ("UALA BANK", "BANCO UALA"),                          None),
    ("KEB Hana",    ("KEB HANA MEXICO",),                                 None),
    ("Revolut",     ("REVOLUT BANK",),                                    None),
    ("Intercam",    ("INTERCAM BANCO",),                                  None),
    ("Dondé",       ("FUNDACION DONDE BANCO",),                           None),
    ("Bineo",       ("BANCO BINEO",),                                     None),
    ("Credit Suisse", ("BANCO CREDIT SUISSE MEXICO",),                    None),
    ("Banfeliz",    ("BANCO BANFELIZ",),                                  None),
    ("PagaTodo",    ("BANCO PAGATODO",),                                  None),
    ("Nu",          ("NUBANK",),                                          None),
    ("CIBanco",     ("CIBANCO",),                                         None),
    ("Finterra",    ("BANCO FINTERRA",),                                  None),
    ("Accendo",     ("ACCENDO BANCO", "BANCO ACCENDO"),                   None),
    ("Autofin",     ("BANCO AUTOFIN MEXICO",),                            None),
    ("American Express", ("AMERICAN EXPRESS BANK MEXICO",),               None),
    ("Deutsche Bank", ("DEUTSCHE BANK MEXICO",),                          None),
    ("UBS",         ("UBS BANK MEXICO",),                                 None),
    ("ABC Capital", ("ABC CAPITAL",),                                     None),
    ("Inter Banco", ("INTER BANCO",),                                     None),
    ("Forjadores",  ("BANCO FORJADORES",),                                None),
    # — Denominaciones anteriores (estados de cuenta viejos) —
    ("IXE",         ("IXE BANCO",),                                       None),
    ("Interacciones", ("BANCO INTERACCIONES",),                           None),
    ("Famsa",       ("BANCO AHORRO FAMSA",),                              None),
    ("Wal-Mart",    ("BANCO WAL MART DE MEXICO ADELANTE",),               None),
    ("ING",         ("ING BANK MEXICO",),                                 None),
    # — Banca de desarrollo (Sociedad Nacional de Crédito) —
    ("Banobras",    ("BANCO NACIONAL DE OBRAS Y SERVICIOS PUBLICOS",),    None),
    ("Nafin",       ("NACIONAL FINANCIERA",),                             None),
    ("Bancomext",   ("BANCO NACIONAL DE COMERCIO EXTERIOR",),             None),
    ("Banjército",  ("BANCO NACIONAL DEL EJERCITO FUERZA AEREA Y ARMADA",), None),
    ("Banco del Bienestar", ("BANCO DEL BIENESTAR", "BANCO DEL AHORRO NACIONAL Y SERVICIOS FINANCIEROS"), None),
    ("SHF",         ("SOCIEDAD HIPOTECARIA FEDERAL",),                    None),
]

_SUFIJO_RS = r"\s+(?:S\s+A\b|SOCIEDAD\s+NACIONAL\s+DE\s+CREDITO)"


def _norm_rs(s: str) -> str:
    """Mayúsculas, sin acentos y sin puntuación (la razón social viene con comas,
    puntos y paréntesis variables: "Banco Santander (México), S.A.")."""
    import re as _re
    import unicodedata as _ud
    s = _ud.normalize("NFKD", s)
    s = "".join(c for c in s if not _ud.combining(c))
    s = _re.sub(r"[^A-Z0-9]+", " ", s.upper())
    # Letras acentuadas que el PDF entrega como carácter inválido: "M�XICO" → "M XICO".
    s = _re.sub(r"\bM XICO\b", "MEXICO", s)
    return _re.sub(r"\bINSTITUCI N\b", "INSTITUCION", s)


# Texto con palabras PEGADAS ("BANCOSANTANDERMEXICO S A INSTITUTIONDEBANCA…", pasa
# en algunos PDF): se busca la razón social sin espacios, exigiendo "SA" + "INSTITU"
# (o "SOCIEDADNACIONALDECREDITO") para no casar con texto pegado de un movimiento.
_SUFIJO_RS_PEGADO = r"(?:SAINSTITU|SOCIEDADNACIONALDECREDITO)"


def _detectar_por_razon_social(texto: str):
    """(extractor_class|None, nombre) del banco cuya RAZÓN SOCIAL + "S.A." aparece
    MÁS veces; (None, None) si ninguna aparece o hay empate."""
    import re as _re
    t = _norm_rs(texto)
    pegado = t.replace(" ", "")
    conteo: dict[str, int] = {}
    for nombre, razones, _ext in _RAZONES_SOCIALES:
        n = max(sum(len(_re.findall(r"\b" + _re.escape(r) + _SUFIJO_RS, t)) for r in razones),
                sum(len(_re.findall(_re.escape(r.replace(" ", "")) + _SUFIJO_RS_PEGADO, pegado))
                    for r in razones))
        if n:
            conteo[nombre] = n
    if not conteo:
        return None, None
    orden = sorted(conteo.items(), key=lambda kv: -kv[1])
    if len(orden) > 1 and orden[0][1] == orden[1][1]:
        return None, None
    nombre = orden[0][0]
    return next(ext for n, _r, ext in _RAZONES_SOCIALES if n == nombre), nombre


# ── API pública ───────────────────────────────────────────────────────────────

def detectar_banco(pdf_path: str) -> BancoExtractor | None:
    """
    Lee las primeras páginas del PDF y retorna una instancia del extractor correcto.
    Retorna None si no se reconoce el banco (o si se reconoce el nombre pero no hay
    parser propio → el llamador usa el genérico).
    Serializado con PDF_LOCK para evitar corrupción del caché global de pdfminer.
    """
    try:
        with PDF_LOCK:
            with pdfplumber.open(pdf_path) as pdf:
                # 4 páginas: BBVA tiene la página 1 como imagen y el encabezado
                # real en pág. 2; 4 páginas garantizan cubrir ese caso.
                sample_pages = min(4, len(pdf.pages))
                page_words = []
                page_texts = []
                for i in range(sample_pages):
                    page = pdf.pages[i]
                    page_words.append(page.extract_words() or [])
                    page_texts.append(page.extract_text() or "")
                # La leyenda legal (razón social) a veces solo va al final del
                # estado de cuenta: se agregan las 2 últimas hojas para buscarla.
                textos_finales = [(pdf.pages[i].extract_text() or "")
                                  for i in range(max(sample_pages, len(pdf.pages) - 2), len(pdf.pages))]
    except Exception:
        return None

    # ── Estrategia 1: RAZÓN SOCIAL de la institución + "S.A." ─────────────────
    extractor_cls, nombre = _detectar_por_razon_social("\n".join(page_texts + textos_finales))
    if nombre is not None:
        return extractor_cls() if extractor_cls is not None else None

    # Por instrucción del usuario NO se detecta por NOMBRE COMERCIAL dominante
    # (_detectar_por_nombre queda solo como referencia): las menciones de los bancos
    # de las contrapartes (SPEI de BBVA en un estado de Banorte) lo engañaban.

    # ── Estrategia 2 (respaldo): ancla "Institución de Banca Múltiple" ────────
    cls = _detectar_por_ibm(page_words)
    if cls is not None:
        return cls()

    # ── Estrategia 3 (respaldo): keywords detectar() en texto ─────────────────
    texto_upper = "\n".join(page_texts).upper()
    for cls in EXTRACTORES:
        if cls.detectar(texto_upper):
            return cls()

    return None


def banco_nombre(pdf_path: str) -> str:
    """Retorna el nombre del banco o 'Desconocido' si no se reconoce."""
    extractor = detectar_banco(pdf_path)
    return extractor.NOMBRE if extractor else "Desconocido"


# ── Cargador dinámico de extractores generados ────────────────────────────────
# Recoge automáticamente cualquier módulo bancos/<x>.py que declare una subclase
# de BancoExtractor (p.ej. los generados por bancos/generador.py) y la agrega al
# registro. Así un banco "aprendido" queda disponible sin editar este archivo.
_MODULOS_BASE = {"base", "estandar", "detector", "generico", "generador", "__init__"}


def _cargar_extractores_dinamicos() -> None:
    import os
    import importlib
    import inspect
    ya = set(EXTRACTORES)

    def _registrar(mod, mod_name):
        for _, obj in inspect.getmembers(mod, inspect.isclass):
            if (issubclass(obj, BancoExtractor) and obj is not BancoExtractor
                    and getattr(obj, "__module__", "") == mod_name
                    and obj not in ya):
                EXTRACTORES.append(obj)
                ya.add(obj)

    # 1) Módulos junto al paquete (modo desarrollo: corriendo desde el fuente).
    #    En el .exe congelado esta carpeta no existe en disco y se omite.
    carpeta_pkg = os.path.dirname(__file__)
    if os.path.isdir(carpeta_pkg):
        for fn in sorted(os.listdir(carpeta_pkg)):
            if not fn.endswith(".py") or fn[:-3] in _MODULOS_BASE:
                continue
            mod_name = f"bancos.{fn[:-3]}"
            try:
                mod = importlib.import_module(mod_name)
            except Exception:
                continue
            _registrar(mod, mod_name)

    # 2) Parsers aprendidos en runtime (carpeta escribible en %PROGRAMDATA%,
    #    agregada a sys.path por carpeta_bancos_custom): se importan como
    #    módulo top-level.
    from bancos.generador import carpeta_bancos_custom
    try:
        carpeta_cust = carpeta_bancos_custom()
    except Exception:
        carpeta_cust = None
    if carpeta_cust and os.path.isdir(carpeta_cust):
        for fn in sorted(os.listdir(carpeta_cust)):
            if not fn.endswith(".py") or fn.startswith("_"):
                continue
            mod_name = fn[:-3]
            try:
                mod = importlib.import_module(mod_name)
            except Exception:
                continue
            _registrar(mod, mod_name)


try:
    _cargar_extractores_dinamicos()
except Exception:
    pass


def detectar_o_generico(pdf_path: str):
    """Como detectar_banco, pero si NINGÚN banco casa devuelve el ExtractorGenerico
    (best-effort) en vez de None. El genérico trae ``ES_GENERICO = True`` para que
    la UI ofrezca generar el parser específico."""
    ext = detectar_banco(pdf_path)
    if ext is not None:
        return ext
    from bancos.generico import ExtractorGenerico
    return ExtractorGenerico()
