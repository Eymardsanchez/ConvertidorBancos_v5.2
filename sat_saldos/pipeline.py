"""Orquestación reutilizable: leer PDFs -> analizar -> generar XLSX.

Separa la LECTURA (costosa) del ANÁLISIS (barato) para que una interfaz pueda
leer una vez y re-analizar al cambiar de RFC o de saldo inicial. Lo usan tanto
la CLI (`cli.py`) como la app de carga (`app.py`, Streamlit).
"""
from __future__ import annotations

import os
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from . import dedup as _dedup
from .analyzer_isr import analizar_isr, total_remanente_nominal
from .analyzer_isr_acumulado import AnalisisISRAcumulado, analizar_isr_acumulado
from .analyzer_iva import AnalisisIVA, analizar_iva
from .analyzer_iva_acumulado import AnalisisIVAAcumulado, analizar_iva_acumulado
from .config import clasifica_concepto
from .extractor import iter_pdfs, pdf_a_textos
from .models import AcusePago, Declaracion, DetalleISR, DetalleIVA, OrigenSaldo
from .parser import parse_declaracion
from .parser_antigua import es_declaracion_antigua, parse_antigua_isr, parse_antigua_iva
from .parser_detalle import (es_declaracion_detallada, es_declaracion_detallada_isr,
                             parse_detalle_isr, parse_detalle_iva)
from .parser_md import identidad, leer_iva, regimen_de
from .pdf_a_md import guardar_md, pdf_a_md
from .parser_pago import es_acuse_pago, parse_acuse_pago
from .report_xlsx import generar_reporte


# --------------------------------------------------------------------------- #
@dataclass
class Cargados:
    """Resultado de la lectura de PDFs (independiente del RFC)."""
    declaraciones: list[Declaracion] = field(default_factory=list)
    detalles: list[DetalleIVA] = field(default_factory=list)
    detalles_isr: list[DetalleISR] = field(default_factory=list)
    pagos: list[AcusePago] = field(default_factory=list)
    no_legibles: list[str] = field(default_factory=list)
    n_pdfs: int = 0

    def rfcs(self) -> list[str]:
        s = {d.rfc for d in self.declaraciones if d.rfc}
        s |= {d.rfc for d in self.detalles if d.rfc}
        s |= {d.rfc for d in self.detalles_isr if d.rfc}
        s |= {p.rfc for p in self.pagos if p.rfc}
        return sorted(s)


def combinar_cargados(base: Cargados | None, nuevos: Cargados) -> Cargados:
    """Acumula lotes ya leídos sin volver a abrir sus PDFs.

    La UI puede recibir PDFs en varias selecciones. Se conserva una sola copia
    por archivo y el análisis posterior trabaja sobre este registro en memoria.
    """
    if base is None:
        return nuevos

    def unir(actual, agregado):
        vistos = {str(getattr(x, "archivo", "")) for x in actual}
        for item in agregado:
            clave = str(getattr(item, "archivo", ""))
            if clave not in vistos:
                actual.append(item)
                vistos.add(clave)
        return actual

    return Cargados(
        declaraciones=unir(base.declaraciones, nuevos.declaraciones),
        detalles=unir(base.detalles, nuevos.detalles),
        detalles_isr=unir(base.detalles_isr, nuevos.detalles_isr),
        pagos=unir(base.pagos, nuevos.pagos),
        no_legibles=list(dict.fromkeys(base.no_legibles + nuevos.no_legibles)),
        n_pdfs=base.n_pdfs + nuevos.n_pdfs,
    )


@dataclass
class ResultadoAnalisis:
    """Análisis para un RFC concreto (listo para reporte o UI)."""
    rfc: str
    razon_social: str
    regimen: str
    origenes_isr: list[OrigenSaldo]
    isr_acumulado: Optional[AnalisisISRAcumulado]
    iva: AnalisisIVA
    iva_acumulado: Optional[AnalisisIVAAcumulado]
    n_unicas: int
    n_vigentes: int
    n_anuales: int
    n_pdfs: int
    no_legibles: list[str]
    pagos: list[AcusePago] = field(default_factory=list)

    @property
    def remanente_isr_total(self) -> float:
        return total_remanente_nominal(self.origenes_isr)

    @property
    def total_pagado(self) -> float:
        return round(sum(p.importe_pagado or 0 for p in self.pagos), 2)


# --------------------------------------------------------------------------- #
def expandir_entradas(entradas: Iterable[Path], destino_zip: Optional[Path] = None) -> list[Path]:
    """Normaliza entradas (carpetas, PDFs, ZIPs) a una lista de rutas .pdf.

    Los ZIP se extraen a `destino_zip` (o a un temporal). Recorre carpetas de
    forma recursiva.
    """
    entradas = [Path(e) for e in entradas]
    if destino_zip is None:
        destino_zip = Path(tempfile.mkdtemp(prefix="sat_zip_"))
    pdfs: list[Path] = []
    for e in entradas:
        if e.is_dir():
            pdfs.extend(iter_pdfs(e))
            for z in e.rglob('*.zip'):        # ZIPs anidados en la carpeta
                try:
                    with zipfile.ZipFile(z) as zf:
                        sub = destino_zip / z.stem
                        zf.extractall(sub)
                        pdfs.extend(iter_pdfs(sub))
                except zipfile.BadZipFile:
                    pass
        elif e.suffix.lower() == '.zip':
            try:
                with zipfile.ZipFile(e) as zf:
                    sub = destino_zip / e.stem
                    zf.extractall(sub)
                    pdfs.extend(iter_pdfs(sub))
            except zipfile.BadZipFile:
                pass
        elif e.suffix.lower() == '.pdf':
            pdfs.append(e)
    # dedup de rutas conservando orden
    vistos: set[str] = set()
    unicas: list[Path] = []
    for p in pdfs:
        k = str(p.resolve())
        if k not in vistos:
            vistos.add(k)
            unicas.append(p)
    return unicas


def _cargar_uno_aislado(ruta: Path) -> Cargados:
    """Lee/clasifica UN PDF en su propio acumulador (sin estado compartido).

    Pensado para correr en un hilo: no toca estructuras compartidas, así el
    merge posterior es el único punto de sincronización.
    """
    c = Cargados(n_pdfs=1)
    try:
        _cargar_uno(Path(ruta), c)
    except Exception as e:  # noqa - un PDF que truene NO tumba toda la carga
        c.no_legibles.append(f"{Path(ruta).name} (error: {type(e).__name__}: {e})")
    return c


def _item_de_cargados(c: Cargados):
    """(tipo, objeto) del único ítem parseado de un Cargados de 1 PDF, o None.

    Cada PDF produce a lo más un objeto (`_cargar_uno` agrega exactamente uno o
    cae en `no_legibles`). Solo se cachean lecturas EXITOSAS; un PDF ilegible no
    se cachea para que se reintente.

    Un PDF puede producir TANTO un DetalleIVA como un DetalleISR (declaración
    combinada ISR+IVA). En ese caso se cachea como tupla "detalle_combo".
    """
    if c.detalles and c.detalles_isr:
        return ("detalle_combo", (c.detalles[0], c.detalles_isr[0]))
    if c.detalles:
        return ("detalle", c.detalles[0])
    if c.detalles_isr:
        return ("detalle_isr", c.detalles_isr[0])
    if c.declaraciones:
        return ("acuse", c.declaraciones[0])
    if c.pagos:
        return ("pago", c.pagos[0])
    return None


def _cargados_de_item(tipo: str, obj) -> Cargados:
    """Reconstruye un Cargados de 1 PDF desde un ítem cacheado (tipo, objeto)."""
    c = Cargados(n_pdfs=1)
    if tipo == "detalle_combo":
        c.detalles.append(obj[0])
        c.detalles_isr.append(obj[1])
    elif tipo == "detalle":
        c.detalles.append(obj)
    elif tipo == "detalle_isr":
        c.detalles_isr.append(obj)
    elif tipo == "acuse":
        c.declaraciones.append(obj)
    elif tipo == "pago":
        c.pagos.append(obj)
    return c


def cargar(pdf_paths: Iterable[Path], progreso=None, max_workers: Optional[int] = None,
           cache=None) -> Cargados:
    """Lee y parsea una lista de rutas PDF, en paralelo con hilos, con caché opcional.

    El trabajo pesado (pdftotext como subproceso, pdfplumber en C) libera el GIL,
    así que los hilos escalan casi lineal con los núcleos. Cada PDF se lee en su
    propio `Cargados` y se fusionan EN ORDEN DE ENTRADA — el resultado es idéntico
    (bit a bit) al recorrido secuencial, incluido el orden que usan luego el dedup
    y la vigencia por fecha.

    `cache` (opcional): objeto con
        get(ruta:str, tamano:int, mtime:float) -> (tipo, objeto) | None
        put(ruta:str, tamano:int, mtime:float, tipo:str, objeto) -> None
    Con caché, un PDF cuya identidad (ruta+tamaño+mtime) ya está guardada se
    reconstruye de la caché SIN abrirlo. La caché se consulta y se guarda en el
    HILO PRINCIPAL (una conexión de BD no es segura entre hilos); solo la LECTURA
    de los PDF faltantes va en paralelo. El resultado final es idéntico (mismo
    contenido y orden) al de sin caché.

    `progreso`: callback opcional (i, total, nombre). Se invoca SIEMPRE desde el
    hilo que llamó a `cargar` (no desde los workers), para no romper tkinter.
    `max_workers`: tope del pool; por defecto min(#faltantes, núcleos).
    """
    pdf_paths = [Path(p) for p in pdf_paths]
    total = len(pdf_paths)
    c = Cargados(n_pdfs=total)
    if total == 0:
        return c

    resultados: list[Optional[Cargados]] = [None] * total
    # 1) HILO PRINCIPAL: identidad de archivo + consulta de caché → HIT vs FALTA.
    faltantes: list[tuple[int, Path]] = []
    if cache is not None:
        for i, ruta in enumerate(pdf_paths):
            hit = None
            try:
                st = os.stat(ruta)
                hit = cache.get(str(ruta), st.st_size, st.st_mtime)
            except Exception:  # noqa - stat/caché que falle → leer el PDF
                hit = None
            if hit is not None:
                resultados[i] = _cargados_de_item(hit[0], hit[1])
            else:
                faltantes.append((i, ruta))
    else:
        faltantes = list(enumerate(pdf_paths))

    # 2) PARALELO: leer solo los faltantes.
    hechos = total - len(faltantes)
    if faltantes:
        workers = max_workers or min(len(faltantes), (os.cpu_count() or 4))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            fut_idx = {ex.submit(_cargar_uno_aislado, ruta): i for i, ruta in faltantes}
            for fut in as_completed(fut_idx):
                i = fut_idx[fut]
                resultados[i] = fut.result()
                if progreso:
                    try:
                        progreso(hechos, total, pdf_paths[i].name)
                    except Exception:  # noqa - un fallo de UI no debe abortar la carga
                        pass
                hechos += 1

    # 3) HILO PRINCIPAL: guardar en caché los faltantes que sí parsearon.
    if cache is not None:
        for i, ruta in faltantes:
            item = _item_de_cargados(resultados[i]) if resultados[i] else None
            if item is None:
                continue
            try:
                st = os.stat(ruta)
                cache.put(str(ruta), st.st_size, st.st_mtime, item[0], item[1])
            except Exception:  # noqa - una falla de caché nunca aborta la carga
                pass

    # 4) Merge determinista en orden de entrada (idéntico al secuencial/sin caché).
    for r in resultados:
        if r is None:
            continue
        c.declaraciones.extend(r.declaraciones)
        c.detalles.extend(r.detalles)
        c.detalles_isr.extend(r.detalles_isr)
        c.pagos.extend(r.pagos)
        c.no_legibles.extend(r.no_legibles)
    return c


def _con_md(ruta: Path, texto: str, det: Optional[DetalleIVA]) -> Optional[DetalleIVA]:
    """Lectura vía MD: PDF → Markdown con el formato del PDF → determinación de IVA
    por ruta (impuesto › sección › etiqueta) con el perfil del régimen de ESTA
    declaración. Si la identidad fiscal del formulario cuadra, las cifras del MD
    sustituyen a las del parser de texto (`lectura="md"`); si no cuadra, se
    conservan las del parser y se marca `revisar`. Sin IVA en el MD (retenciones,
    escaneado sin texto) → `det` sin cambios. El MD se guarda para "Ver MD"."""
    try:
        md = pdf_a_md(ruta)
    except Exception:  # noqa - el MD es una mejora; nunca tumba la carga
        return det
    reg = regimen_de(md)
    v = leer_iva(md, reg)
    if det is None:
        if not v:
            return None
        from .parser_antigua import _meta
        m = _meta(texto)
        if not m.get("rfc"):
            return None
        det = DetalleIVA(
            archivo=str(ruta), rfc=m.get("rfc") or "", ejercicio=m.get("ejercicio"),
            periodo=m.get("periodo"), operacion=m.get("operacion"),
            fecha_presentacion=m.get("fecha_presentacion"),
            subtipo=m.get("subtipo") or "normal", a_cargo_periodo=None,
            a_favor_periodo=None, acreditamiento_anterior=0.0,
            impuesto_a_cargo_final=None, cantidad_a_pagar=None)
    det.regimen = reg
    guardar_md(det.rfc, ruta, md)
    if not v:
        return det
    idt = identidad(v)
    if idt and all(idt):
        fav = v.get("a_favor") or 0
        det.a_favor_periodo = fav if fav > 0 else None
        det.acreditamiento_anterior = v.get("acreditamiento") or 0.0
        if "cantidad_cargo" in v:
            det.a_cargo_periodo = v["cantidad_cargo"]
        if "impuesto_cargo" in v:
            det.impuesto_a_cargo_final = v["impuesto_cargo"]
            if det.cantidad_a_pagar is None:
                det.cantidad_a_pagar = v["impuesto_cargo"]
        det.lectura = "md"
    elif idt:
        det.revisar = True
    return det


def _cargar_uno(ruta: Path, c: Cargados) -> None:
    """Lee y clasifica UN PDF, agregándolo al acumulador `c`."""
    vistas = pdf_a_textos(ruta)
    texto = vistas.layout
    if not texto.strip():
        c.no_legibles.append(ruta.name)
        return
    raw = vistas.raw
    if es_acuse_pago(texto):
        pago = parse_acuse_pago(ruta, texto, texto_raw=raw)
        if pago is not None:
            c.pagos.append(pago)
        return
    if es_declaracion_detallada(texto):
        det = _con_md(ruta, texto, parse_detalle_iva(texto, archivo=str(ruta)))
        if det is not None:
            c.detalles.append(det)
        det_isr = parse_detalle_isr(texto, archivo=str(ruta))
        if det_isr is not None:
            c.detalles_isr.append(det_isr)
        if det is not None or det_isr is not None:
            return
    elif es_declaracion_detallada_isr(texto):
        det_isr = parse_detalle_isr(texto, archivo=str(ruta))
        if det_isr is not None:
            c.detalles_isr.append(det_isr)
            return
    if es_declaracion_antigua(texto):
        det = _con_md(ruta, texto, parse_antigua_iva(ruta, texto))
        det_isr = parse_antigua_isr(ruta, texto)
        if det is not None:
            c.detalles.append(det)
        if det_isr is not None:
            c.detalles_isr.append(det_isr)
        if det is not None or det_isr is not None:
            return
        # Algunos PDFs antiguos tienen una estructura válida de declaración,
        # pero no permiten reconstruir sus coordenadas de IVA. No descartarlos:
        # el parser general conserva RFC, periodo, operación y demás conceptos.
    declaracion = parse_declaracion(texto, archivo=str(ruta), texto_raw=raw)
    if es_declaracion_antigua(texto):
        # En el formato antiguo los encabezados están partidos en columnas y
        # `pdftotext -layout` coloca el valor en otra línea. Reutilizar su
        # extracción de metadatos evita perder RFC/periodo/operación cuando no
        # fue posible reconstruir el detalle IVA.
        from .parser_antigua import _meta as _meta_antigua
        meta = _meta_antigua(texto)
        if not declaracion.rfc:
            declaracion.rfc = meta.get("rfc") or ""
        if declaracion.ejercicio is None:
            declaracion.ejercicio = meta.get("ejercicio")
        if declaracion.periodo is None:
            declaracion.periodo = meta.get("periodo")
        if not declaracion.operacion:
            declaracion.operacion = meta.get("operacion")
        if declaracion.fecha_presentacion is None:
            declaracion.fecha_presentacion = meta.get("fecha_presentacion")
    c.declaraciones.append(declaracion)


def detectar_regimen(vigentes: list[Declaracion], detalles: list[DetalleIVA]) -> str:
    nombres = " ".join(cc.nombre.upper() for d in vigentes for cc in d.conceptos)
    if 'SIMPLIFICADO DE CONFIANZA' in nombres or detalles:
        return "RESICO PM (Cap. XII Tít. VII LISR)"
    return "Régimen General (Tít. II LISR)"


def analizar(cargados: Cargados, rfc: Optional[str] = None,
             saldo_inicial_iva: Optional[float] = None) -> ResultadoAnalisis:
    """Analiza los datos cargados para un RFC (o el único presente)."""
    declaraciones = cargados.declaraciones
    detalles = cargados.detalles
    detalles_isr = cargados.detalles_isr
    pagos = cargados.pagos
    if rfc:
        declaraciones = [d for d in declaraciones if d.rfc == rfc]
        detalles = [d for d in detalles if d.rfc == rfc]
        detalles_isr = [d for d in detalles_isr if d.rfc == rfc]
        pagos = [p for p in pagos if p.rfc == rfc]
    pagos = _pagos_vigentes(pagos)

    unicas = _dedup.deduplicar(declaraciones)
    vig_map = _dedup.vigentes_mensuales(unicas)
    vigentes = [d for d in vig_map.values() if not _dedup.esta_sin_efecto(d)]
    anuales = _dedup.anuales(unicas)

    origenes = analizar_isr(vigentes, anuales)
    isr_acum = analizar_isr_acumulado(detalles_isr) if detalles_isr else None
    iva = analizar_iva(vigentes)
    iva_acum = (analizar_iva_acumulado(detalles, saldo_inicial=saldo_inicial_iva or 0.0)
                if detalles else None)
    if iva_acum is not None and iva_acum.renglones:
        iva.remanente_iva_determinable = True

    razon = next((d.razon_social for d in unicas if d.razon_social), "")
    rfc_final = rfc or (cargados.rfcs()[0] if cargados.rfcs() else "")
    regimen = detectar_regimen(vigentes, detalles)

    return ResultadoAnalisis(
        rfc=rfc_final, razon_social=razon, regimen=regimen,
        origenes_isr=origenes, isr_acumulado=isr_acum, iva=iva, iva_acumulado=iva_acum,
        n_unicas=len(unicas), n_vigentes=len(vig_map), n_anuales=len(anuales),
        n_pdfs=cargados.n_pdfs, no_legibles=cargados.no_legibles, pagos=pagos,
    )


def _pagos_vigentes(pagos: list[AcusePago]) -> list[AcusePago]:
    """Dedup por operación y vigente por (ejercicio, periodo) = mayor fecha de
    presentación (una complementaria de pago sustituye a la normal)."""
    byop: dict[str, AcusePago] = {}
    for p in pagos:
        byop.setdefault(p.operacion or p.archivo, p)
    grupos: dict[tuple, list[AcusePago]] = {}
    for p in byop.values():
        grupos.setdefault((p.ejercicio, p.periodo), []).append(p)
    vig = [max(g, key=lambda x: x.fecha_presentacion or datetime(1900, 1, 1))
           for g in grupos.values()]
    return sorted(vig, key=lambda x: (x.ejercicio or 0, x.periodo or 0))


def generar_xlsx(res: ResultadoAnalisis, ruta_salida: Path,
                 saldo_inicial_iva: Optional[float] = None) -> Path:
    """Genera el papel de trabajo XLSX a partir de un ResultadoAnalisis."""
    return generar_reporte(
        Path(ruta_salida), razon_social=res.razon_social, rfc=res.rfc,
        regimen=res.regimen, origenes_isr=res.origenes_isr, analisis_iva=res.iva,
        iva_acumulado=res.iva_acumulado, isr_acumulado=res.isr_acumulado,
        saldo_inicial_iva=saldo_inicial_iva, pagos=res.pagos,
    )

