"""Módulo Conciliación CFDI (equivale a `_build_conciliacion_tab` y todos los
`_concil_*`, `_abrir_fases`, `_DialogDescargaSAT` de la 5.0). MISMA lógica de
negocio; todo lo pesado en hilo con avance/bitácora hacia la pantalla.

Descarga SAT: SOLO Web Service (satcfdi). La 5.0 no lleva el canal Portal.
La contraseña de la e.firma solo vive en memoria durante la descarga.
"""
from __future__ import annotations

import os
import re as _re
import threading
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from bancos.detector import PDF_LOCK, detectar_banco
from empresas import buscar_por_rfc, listar_empresas, obtener_empresa

try:
    from cfdi_parser import clasificar_cfdis, leer_cfdis_carpetas
    from conciliacion import FASES_CONCILIACION, FASES_DEFAULT, conciliar_multibanco, mov_a_banco
    from exportar_conciliacion import exportar_conciliacion_multi as _exp_concil_multi
    _CONCIL_OK = True
except ImportError:
    _CONCIL_OK = False
    FASES_CONCILIACION, FASES_DEFAULT = [], frozenset()

try:
    from grupos_conciliacion import cargar_grupos as _cargar_grupos
    _GRUPOS_OK = True
except ImportError:
    _GRUPOS_OK = False

try:
    import sat_descarga as _SAT
    _SAT_OK = True
except ImportError:
    _SAT_OK = False

import compliance_engine as CE
from sat_config import filtrar_por_uuid_local, guardar_sat_carpeta_base, sat_carpeta_base

# Catálogo c_FormaPago del SAT (igual a la 5.0)
FORMAS_PAGO = [
    ("01", "Efectivo"), ("02", "Cheque nominativo"),
    ("03", "Transferencia electrónica de fondos"), ("04", "Tarjeta de crédito"),
    ("05", "Monedero electrónico"), ("06", "Dinero electrónico"),
    ("08", "Vales de despensa"), ("12", "Dación en pago"),
    ("13", "Pago por subrogación"), ("14", "Pago por consignación"),
    ("15", "Condonación"), ("17", "Compensación"), ("23", "Novación"),
    ("24", "Confusión"), ("25", "Remisión de deuda"),
    ("26", "Prescripción o caducidad"), ("27", "A satisfacción del acreedor"),
    ("28", "Tarjeta de débito"), ("29", "Tarjeta de servicios"),
    ("30", "Aplicación de anticipos"), ("31", "Intermediario pagos"),
    ("99", "Por definir"),
]
# Niveles de confianza de las fases (mismos colores que la columna TIPO MATCH del Excel)
_NIVEL_DE = {"exacto": 0, "multi_mov": 1, "combinatorio": 1, "grupos": 1,
             "ppd_con_rfc": 2, "ppd_con_nom": 2,
             "ppd_sin_rfc": 3, "ppd_sin_nom": 3, "solo_importe": 3}
_NIVELES = [("Directo", "#1B5FAF", "Identidad + importe + mes."),
            ("Compuesto", "#A8480F", "Sumas y agrupaciones."),
            ("Con complemento", "#0F7A57", "Respaldado por el REP."),
            ("Débil", "#4A3AA7", "Sin complemento o solo por importe."),
            ("Otras", "#5A594F", "")]
_MESNOM = {1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
           7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre",
           12: "diciembre"}
_COLORES = ["1565C0", "2E7D32", "6A1B9A", "BF360C", "00695C", "4527A0", "558B2F", "AD1457"]


def _cfdi_data(_persist, c):
    return _persist.CFDIData(
        uuid=getattr(c, "uuid", "") or "", tipo=getattr(c, "tipo", "") or "",
        rfc_emisor=getattr(c, "rfc_emisor", "") or "", rfc_receptor=getattr(c, "rfc_receptor", "") or "",
        nombre_emisor=getattr(c, "nombre_emisor", "") or "",
        nombre_receptor=getattr(c, "nombre_receptor", "") or "",
        subtotal=float(getattr(c, "subtotal", 0) or 0), total=float(getattr(c, "total", 0) or 0),
        descuento=float(getattr(c, "descuento", 0) or 0), iva=float(getattr(c, "iva16", 0) or 0),
        iva_retenido=float(getattr(c, "iva_retenido", 0) or 0),
        isr_retenido=float(getattr(c, "isr_retenido", 0) or 0),
        clave_prod_serv=getattr(c, "clave_prod_serv", "") or "",
        fecha_emision=getattr(c, "fecha_emision", "") or "")


class ConciliacionApi:
    def _concil_init(self):
        self._k_carpetas: list[str] = []
        self._k_carpetas_txt: dict[str, str] = {}
        self._k_pdfs: list[dict] = []
        self._k_fases = set(FASES_DEFAULT)
        self._k_cancel = threading.Event()
        self._k_running = False
        self._k_ultimo = None
        self._k_recon = None
        self._k_anio = None

    # -- metadatos / empresa ------------------------------------------------------------
    def concil_meta(self) -> dict:
        try:
            anio_def = date.today().year if date.today().year in CE.anios_disponibles() \
                else max(CE.anios_disponibles())
        except Exception:
            anio_def = date.today().year
        niveles = []
        for ix, (nom, color, desc) in enumerate(_NIVELES):
            fases = [{"id": f, "etq": e} for f, e in FASES_CONCILIACION if _NIVEL_DE.get(f, 4) == ix]
            if fases:
                niveles.append({"nombre": nom, "color": color, "desc": desc, "fases": fases})
        return {"ok": _CONCIL_OK, "sat_ok": _SAT_OK, "grupos_ok": _GRUPOS_OK,
                "empresas": [{"rfc": r, "nombre": n} for r, n in listar_empresas()],
                "anios": [int(y) for y in CE.anios_disponibles()], "anio_default": anio_def,
                "niveles": niveles, "fases_activas": sorted(self._k_fases),
                "formas_pago": FORMAS_PAGO,
                "destino": f"Conciliacion_{datetime.now().strftime('%Y%m%d')}.xlsx"}

    def concil_empresa(self, rfc) -> dict:
        emp = obtener_empresa(rfc) if rfc else None
        if not emp:
            return {"txt": "", "ok": None}
        codigos, nombres = emp.get("regimenes", []), emp.get("regimenes_nombres", [])
        if codigos and nombres:
            return {"txt": "✔  Régimen(es): " + ",  ".join(f"{n} ({c})" for n, c in zip(nombres, codigos)), "ok": True}
        if codigos:
            return {"txt": "Régimen(es): " + ", ".join(codigos), "ok": True}
        return {"txt": "Sin CSF registrada — sube la Constancia para validar régimen fiscal", "ok": False}

    def concil_fases(self, activas):
        self._k_fases = {f for f in activas}
        return sorted(self._k_fases)

    # -- Paso 1: XML ------------------------------------------------------------------
    def _k_vista_xml(self):
        return [self._k_carpetas_txt.get(c, c) for c in self._k_carpetas]

    def concil_add_carpeta(self):
        for c in self._elegir_carpetas():
            if c not in self._k_carpetas:
                self._k_carpetas.append(c)
        return self._k_vista_xml()

    def concil_add_xml(self):
        for r in self._elegir_archivos(("XML (CFDI) (*.xml)", "Todos (*.*)")):
            if r not in self._k_carpetas:
                self._k_carpetas.append(r)
        return self._k_vista_xml()

    def concil_add_rutas_xml(self, rutas):           # usado por la prueba automática
        for r in rutas:
            if r not in self._k_carpetas:
                self._k_carpetas.append(r)
        return self._k_vista_xml()

    def concil_clear_carpetas(self):
        self._k_carpetas.clear()
        self._k_carpetas_txt.clear()
        return []

    # -- Paso 2: PDF ------------------------------------------------------------------
    def _k_vista_pdf(self):
        return [{"nombre": d["nombre"], "banco": d["banco"], "movs": d["movs"], "estado": d["estado"]}
                for d in self._k_pdfs]

    def concil_add_pdf(self):
        return self.concil_add_rutas_pdf(self._elegir_archivos(("PDF (*.pdf)", "Todos (*.*)")))

    def concil_add_rutas_pdf(self, rutas):
        existentes = {d["path"] for d in self._k_pdfs}
        for p in rutas:
            if p not in existentes:
                self._k_pdfs.append({"path": p, "nombre": Path(p).name, "banco": "—",
                                     "movs": 0, "info": None, "estado": "listo"})
        return self._k_vista_pdf()

    def concil_clear_pdfs(self):
        self._k_pdfs.clear()
        return []

    def concil_elegir_destino(self):
        return self._guardar_como(f"Conciliacion_{datetime.now().strftime('%Y%m%d')}.xlsx",
                                  ("Excel (*.xlsx)",))

    def _k_log(self, msg, tag=""):
        self._js("concil.log", msg, tag)

    # -- CONCILIAR (hilo) — misma lógica que App._concil_run ------------------------------
    def concil_ejecutar(self, p) -> dict:
        if not _CONCIL_OK:
            return {"ok": False, "msg": "Módulos de conciliación no disponibles."}
        rfc = (p.get("rfc") or "").strip().upper()
        if not rfc:
            return {"ok": False, "msg": "Ingresa el RFC de tu empresa."}
        if not self._k_carpetas:
            return {"ok": False, "msg": "Selecciona al menos una carpeta con archivos XML (CFDIs)."}
        if not self._k_pdfs:
            return {"ok": False, "msg": "Agrega al menos un estado de cuenta PDF."}
        destino = (p.get("destino") or "").strip()
        if not destino:
            return {"ok": False, "msg": "Selecciona dónde guardar el archivo Excel de conciliación."}
        if self._k_running:
            return {"ok": False, "msg": "Ya hay una conciliación en curso."}
        self._k_cancel = threading.Event()
        self._k_running = True
        threading.Thread(target=self._k_run, daemon=True, args=(
            rfc, destino, p.get("anio"), set(p.get("formas") or []),
            [int(m) for m in (p.get("meses_iva") or [])])).start()
        return {"ok": True}

    def concil_detener(self):
        self._k_cancel.set()
        self._k_log("⛔ Cancelando… (terminando el paso actual)", "warn")
        return True

    def _k_run(self, rfc, destino, anio, sel_fp, meses_iva):
        fin = {"ok": False}
        try:
            all_movs = []
            self._k_log(f"Escaneando {len(self._k_carpetas)} carpeta(s) de XMLs…", "info")
            cfdis = leer_cfdis_carpetas(*self._k_carpetas)
            recibidos, emitidos, descartados = clasificar_cfdis(cfdis, rfc)
            self._k_log(f"  {len(cfdis)} CFDIs  ({len(recibidos)} recibidos, {len(emitidos)} emitidos"
                        + (f", {len(descartados)} descartados (RFC no coincide)" if descartados else "")
                        + ")", "ok")
            self._js("concil.xmlCuenta", f"{len(self._k_carpetas)} carpeta(s)  |  {len(cfdis)} XMLs cargados")
            if sel_fp:   # filtro Forma de pago: PPD y forma '99'/vacía se conservan
                def _pasa_fp(c):
                    if getattr(c, "metodo_pago", "") == "PPD":
                        return True
                    fp = (getattr(c, "forma_pago", "") or "").strip()
                    return fp in ("", "99") or fp in sel_fp
                _nr0, _ne0 = len(recibidos), len(emitidos)
                recibidos = [c for c in recibidos if _pasa_fp(c)]
                emitidos = [c for c in emitidos if _pasa_fp(c)]
                self._k_log(f"  Filtro Forma de pago {', '.join(sorted(sel_fp))}: se omitieron "
                            f"{(_nr0 - len(recibidos)) + (_ne0 - len(emitidos))} CFDI PUE con otra forma"
                            "  (PPD/REP/'99' conservados)", "info")
            bancos_input, colores_banco, cuentas_banco, nombres_usados = [], {}, {}, {}
            try:
                anio_sel = int(anio)
            except (TypeError, ValueError):
                anio_sel = None
            self._k_log(f"► Conciliando AÑO {anio_sel}", "info")

            def _periodo_de(movs, info):
                from conciliacion import _mes_fecha as _mf
                cnt = Counter()
                for m in movs:
                    mm = getattr(m, "mes", 0) or _mf(getattr(m, "fecha", "") or "")
                    if mm:
                        cnt[mm] += 1
                mes = cnt.most_common(1)[0][0] if cnt else 0
                a = 0
                m1 = _re.search(r"\b(20\d{2})\b", getattr(info, "periodo", "") or "")
                if m1:
                    a = int(m1.group(1))
                if not a:
                    for mv in movs:
                        m2 = _re.search(r"\b(20\d{2})\b", getattr(mv, "fecha", "") or "")
                        if m2:
                            a = int(m2.group(1))
                            break
                return a, mes

            leidos = []
            for d in self._k_pdfs:
                if self._k_cancel.is_set():
                    self._k_log("⛔ Proceso detenido por el usuario.", "warn")
                    return
                self._k_log(f"Leyendo PDF: {d['nombre']}", "info")
                try:
                    with PDF_LOCK:
                        extractor = detectar_banco(d["path"])
                    if extractor is None:
                        raise ValueError("Banco no reconocido")
                    d["banco"] = extractor.NOMBRE
                    with PDF_LOCK:
                        movs, info = extractor.extraer(d["path"])
                    if not movs:
                        raise ValueError("Sin movimientos en el PDF")
                    d["movs"], d["info"], d["estado"] = len(movs), info, "ok"
                    pa, _pm = _periodo_de(movs, info)
                    leidos.append((d, movs, info, extractor.NOMBRE, pa))
                except Exception as e:
                    d["estado"] = "error"
                    self._k_log(f"  ERROR: {e}", "err")
                self._js("concil.pdfs", self._k_vista_pdf())
            coinciden = [t for t in leidos if not (anio_sel and t[4] and t[4] != anio_sel)]
            if anio_sel and leidos and not coinciden:
                self._k_log(f"  ⚠ Ningún estado de cuenta coincide con el año {anio_sel}; "
                            "se concilian TODOS los cargados.", "warn")
                usar = leidos
            else:
                usar = coinciden
                keep = {id(t[0]) for t in usar}
                for t in leidos:
                    if id(t[0]) not in keep:
                        t[0]["estado"] = "omitido"
                        self._k_log(f"  ⏭ Omitido (año {t[4]} ≠ {anio_sel}): {t[0]['nombre']}", "warn")
            for d, movs, info, banco_nom, _pa in usar:
                base = banco_nom[:28]
                nombres_usados[base] = nombres_usados.get(base, 0) + 1
                nombre_banco = base if nombres_usados[base] == 1 else f"{base} ({nombres_usados[base]})"
                bancos_input.append((nombre_banco, [mov_a_banco(m, anio=anio_sel or 0) for m in movs]))
                all_movs.extend(movs)
                colores_banco[nombre_banco] = _COLORES[(len(bancos_input) - 1) % len(_COLORES)]
                cuentas_banco[nombre_banco] = getattr(info, "numero_cuenta", "") or ""
                self._k_log(f"  [{nombre_banco}] {len(movs)} movimientos", "ok")
            self._js("concil.pdfs", self._k_vista_pdf())
            if not bancos_input:
                raise ValueError("No se extrajeron movimientos de ningún PDF.")
            self._k_log(f"Total: {len(bancos_input)} banco(s), {len(all_movs)} movimientos", "info")
            if self._k_cancel.is_set():
                self._k_log("⛔ Proceso detenido por el usuario.", "warn")
                return
            self._k_log("Ejecutando conciliacion multi-banco...", "info")
            grupos_activos = None
            if _GRUPOS_OK:
                activos = [g for g in _cargar_grupos(rfc) if g.activo]
                if activos:
                    self._k_log(f"Grupos RFC: {len(activos)} activo(s) — Fase 5 habilitada", "info")
                    grupos_activos = activos
            fases_sel = set(self._k_fases)
            self._k_log("Fases activas: " + ", ".join(f for f, _ in FASES_CONCILIACION if f in fases_sel), "info")
            resultados = conciliar_multibanco(bancos_input, recibidos, emitidos, grupos=grupos_activos,
                                              fases=fases_sel, log=self._k_log)
            total_conc = sum(len(r.conciliados) for r in resultados)
            total_pend = sum(len(r.sin_cfdi) for r in resultados)
            total_rev = sum(sum(1 for mc in r.conciliados if mc.revisar) for r in resultados)
            pct = round(total_conc / len(all_movs) * 100, 1) if all_movs else 0
            for res in resultados:
                self._k_log(f"  {res.nombre}: {len(res.conciliados)} conciliados, {len(res.sin_cfdi)} sin CFDI", "ok")
            self._k_log(f"  TOTAL: {total_conc} conciliados ({pct}%), {total_pend} sin CFDI"
                        + (f", {total_rev} requieren revision" if total_rev else ""),
                        "ok" if not total_pend else "warn")
            try:
                self._k_anio = anio
                self._k_guardar_bd(rfc, resultados, recibidos, emitidos)
            except Exception as e_bd:
                self._k_log(f"  ⚠ BD no disponible ({e_bd}); el reporte sale sin IDs.", "warn")
            self._k_log("Generando Excel...", "info")
            destino = _exp_concil_multi(
                resultados=resultados, todos_recibidos=recibidos, todos_emitidos=emitidos,
                output_path=destino, colores_banco=colores_banco, rfc_empresa=rfc,
                cuentas_banco=cuentas_banco, meses_iva=meses_iva or None) or destino
            self._k_log("Archivo generado:", "ok")
            self._k_log(f"  {destino}", "ok")
            self._k_ultimo = {"resultados": resultados, "recibidos": recibidos,
                              "emitidos": emitidos, "destino": destino, "rfc": rfc}
            fin = {"ok": True, "destino": destino, "bancos": len(resultados), "movs": len(all_movs),
                   "conc": total_conc, "pct": pct, "pend": total_pend, "rev": total_rev}
        except Exception as exc:
            import traceback
            self._k_log(f"ERROR: {exc}", "err")
            self._k_log(traceback.format_exc(), "err")
            fin = {"ok": False, "msg": str(exc)}
        finally:
            self._k_running = False
            self._js("concil.fin", fin)

    def _k_guardar_bd(self, rfc, resultados, recibidos=None, emitidos=None):
        """Igual que `_concil_guardar_bd` de la 5.0: filas en orden del PDF con ID
        estable (col A del Excel) + todos los CFDI."""
        import persistencia as _persist
        periodo = str(self._k_anio or "")

        def _tipo_mov(mb):
            return "recibido" if (mb.retiro or 0) else ("emitido" if (mb.deposito or 0) else "")
        pares = []
        for res in resultados:
            bloque = []
            for mc in res.conciliados:
                mb = mc.banco
                suma = ",".join(getattr(c, "uuid", "") for c in getattr(mc, "cfdi_suma", []) if getattr(c, "uuid", ""))
                bloque.append((mb, _persist.FilaConciliacion(
                    rfc=rfc, banco=res.nombre, fecha=str(mb.fecha or ""),
                    importe=float(mb.deposito or 0) - float(mb.retiro or 0),
                    concepto=mb.descripcion or "", uuid_cfdi=mb.uuid or "",
                    uuid_rep=getattr(mb, "uuid_rep", "") or "", tipo_match=mc.tipo_match or "",
                    revisar=bool(mc.revisar), tipo=mc.tipo or _tipo_mov(mb), uuid_suma=suma,
                    deposito=float(mb.deposito or 0), retiro=float(mb.retiro or 0))))
            for mb in res.sin_cfdi:
                bloque.append((mb, _persist.FilaConciliacion(
                    rfc=rfc, banco=res.nombre, fecha=str(mb.fecha or ""),
                    importe=float(mb.deposito or 0) - float(mb.retiro or 0),
                    concepto=mb.descripcion or "", tipo=_tipo_mov(mb),
                    deposito=float(mb.deposito or 0), retiro=float(mb.retiro or 0))))
            bloque.sort(key=lambda pr: getattr(pr[0], "orden", 0))
            pares.extend(bloque)
        if not pares:
            return
        p = _persist.FirebirdPersistencia()
        p.inicializar()
        try:
            filas = [f for _, f in pares]
            p.guardar_conciliacion(rfc, periodo, filas)
            for mb, f in pares:
                mb.id_fila = f.id
            cfdis = [_cfdi_data(_persist, c) for c in (list(recibidos or []) + list(emitidos or []))]
            if cfdis:
                p.guardar_cfdis(cfdis)
            self._k_log(f"  BD Firebird: {len(filas)} filas + {len(cfdis)} CFDI guardados "
                        "(ID estable en col A).", "info")
        finally:
            p.cerrar()

    def concil_abrir(self, ruta):
        if ruta and os.path.exists(ruta):
            os.startfile(ruta)  # noqa: S606
        return True

    # -- Actualizar XML (solo sube CFDI a la BD) -------------------------------------------
    def concil_subir_xml(self, rfc) -> dict:
        rfc = (rfc or "").strip().upper()
        if not rfc:
            return {"ok": False, "msg": "Ingresa el RFC de tu empresa."}
        if not self._k_carpetas:
            return {"ok": False, "msg": "Selecciona al menos una carpeta con archivos XML (CFDIs)."}
        threading.Thread(target=self._k_subir_xml_run, args=(rfc,), daemon=True).start()
        return {"ok": True}

    def _k_subir_xml_run(self, rfc):
        try:
            self._k_log(f"Escaneando {len(self._k_carpetas)} carpeta(s) de XMLs…", "info")
            cfdis = leer_cfdis_carpetas(*self._k_carpetas)
            recibidos, emitidos, descartados = clasificar_cfdis(cfdis, rfc)
            self._k_log(f"  {len(cfdis)} CFDIs ({len(recibidos)} recibidos, {len(emitidos)} emitidos"
                        + (f", {len(descartados)} descartados (RFC no coincide)" if descartados else "") + ")", "ok")
            self._js("concil.xmlCuenta", f"{len(self._k_carpetas)} carpeta(s)  |  {len(cfdis)} XMLs cargados")
            import persistencia as _persist
            datos = [_cfdi_data(_persist, c) for c in list(recibidos) + list(emitidos)]
            px = _persist.FirebirdPersistencia(); px.inicializar()
            try:
                st = px.guardar_cfdis(datos, solo_nuevos=True)
            finally:
                px.cerrar()
            self._k_log(f"  XML en BD: {st.get('nuevos', 0)} nuevos, {st.get('omitidos', 0)} ya existian (omitidos).", "ok")
            self._js("concil.aviso", "XML actualizados",
                     f"XML nuevos agregados : {st.get('nuevos', 0)}\nYa existían (omitidos) : "
                     f"{st.get('omitidos', 0)}\n\nUsa \"Reconciliar (sin CFDI)\" para conciliar contra los "
                     "estados de cuenta guardados.")
        except Exception as exc:
            import traceback
            self._k_log(f"ERROR: {exc}", "err")
            self._k_log(traceback.format_exc(), "err")
            self._js("concil.aviso", "Error al actualizar XML", str(exc))
        finally:
            self._js("concil.ocupado", False)

    # -- Reconciliar (solo filas 'sin CFDI') ---------------------------------------------
    def concil_reconciliar_prep(self, rfc) -> dict:
        rfc = (rfc or "").strip().upper()
        if not rfc:
            return {"ok": False, "msg": "Ingresa el RFC de tu empresa."}
        if not self._k_carpetas:
            return {"ok": False, "msg": "Selecciona la(s) carpeta(s) de XML a conciliar."}
        threading.Thread(target=self._k_recon_prep, args=(rfc,), daemon=True).start()
        return {"ok": True}

    def _k_recon_prep(self, rfc):
        try:
            from conciliacion import _mes_fecha as _mf
            self._k_log("Escaneando XML y leyendo estados de cuenta guardados…", "info")
            cfdis = leer_cfdis_carpetas(*self._k_carpetas)
            recibidos, emitidos, _d = clasificar_cfdis(cfdis, rfc)
            xml_cnt = Counter()
            for c in list(recibidos) + list(emitidos):
                m = _mf(getattr(c, "fecha_emision", "") or "")
                if m:
                    xml_cnt[m] += 1
            import persistencia as _persist
            px = _persist.FirebirdPersistencia(); px.inicializar()
            try:
                filas = px.leer_filas_por_rfc(rfc)
            finally:
                px.cerrar()
            bank_cnt, bank_sin = Counter(), Counter()
            for f in filas:
                m = _mf(f.fecha)
                if not m:
                    continue
                bank_cnt[m] += 1
                if not (f.uuid_cfdi and f.tipo_match):
                    bank_sin[m] += 1
            self._k_recon = (rfc, recibidos, emitidos)
            if not bank_cnt:
                self._js("concil.aviso", "Sin estados de cuenta",
                         "No hay estados de cuenta guardados en la BD para este RFC.\n\nConcilia primero con "
                         "PDF (botón de conciliación) para tener movimientos bancarios que reconciliar.")
                return
            if not xml_cnt:
                self._js("concil.aviso", "Sin XML", "Las carpetas seleccionadas no tienen XML con fecha para conciliar.")
                return
            self._js("concil.reconciliarElegir",
                     [{"mes": m, "nombre": _MESNOM.get(m, str(m)), "sin": bank_sin.get(m, 0)} for m in sorted(bank_cnt)],
                     [{"mes": m, "nombre": _MESNOM.get(m, str(m)), "n": xml_cnt[m]} for m in sorted(xml_cnt)])
        except Exception as exc:
            import traceback
            self._k_log(traceback.format_exc(), "err")
            self._js("concil.aviso", "Error", str(exc))
        finally:
            self._js("concil.ocupado", False)

    def concil_reconciliar_run(self, bank_meses, xml_meses) -> dict:
        if not self._k_recon:
            return {"ok": False, "msg": "Vuelve a pulsar Reconciliar."}
        threading.Thread(target=self._k_recon_run, daemon=True,
                         args=({int(m) for m in bank_meses}, {int(m) for m in xml_meses})).start()
        return {"ok": True}

    def _k_recon_run(self, bank_meses, xml_meses):
        rfc, recibidos, emitidos = self._k_recon
        try:
            from conciliacion import _mes_fecha as _mf
            rec = [c for c in recibidos if _mf(getattr(c, "fecha_emision", "") or "") in xml_meses]
            emi = [c for c in emitidos if _mf(getattr(c, "fecha_emision", "") or "") in xml_meses]
            self._k_log("Reconciliando: estados de cuenta "
                        f"[{', '.join(_MESNOM.get(m, str(m)) for m in sorted(bank_meses))}] vs XML "
                        f"[{', '.join(_MESNOM.get(m, str(m)) for m in sorted(xml_meses))}] …", "info")
            grp = None
            if _GRUPOS_OK:
                ga = [g for g in _cargar_grupos(rfc) if g.activo]
                grp = ga or None
            import reimportar as _reimp
            rst = _reimp.reconciliar_desde_bd(
                rfc, meses=list(bank_meses), fases=set(self._k_fases), grupos=grp,
                usuario=self._usuario, recibidos=rec, emitidos=emi, log=self._k_log, regenerar=True)
            r = rst.get("reconciliadas", 0)
            self._k_log(f"  Re-conciliación: {r} fila(s) 'sin CFDI' ahora conciliadas.", "ok")
            self._js("concil.aviso", "Reconciliación" if r else "Sin cambios",
                     f"{r} fila(s) 'sin CFDI' ahora conciliadas." if r else
                     "No hubo cambios: ninguna fila 'sin CFDI' de los meses elegidos encontró su CFDI.")
        except Exception as exc:
            import traceback
            self._k_log(f"ERROR: {exc}", "err")
            self._k_log(traceback.format_exc(), "err")
            self._js("concil.aviso", "Error al reconciliar", str(exc))
        finally:
            self._js("concil.ocupado", False)

    # -- Administrador de Conciliaciones ---------------------------------------------------
    def concil_lista_bd(self, rfc) -> dict:
        try:
            import persistencia as _persist
            p = _persist.FirebirdPersistencia(); p.inicializar()
            try:
                concs = p.leer_conciliaciones((rfc or "").strip().upper())
            finally:
                p.cerrar()
        except Exception as e:
            return {"ok": False, "msg": str(e)}
        return {"ok": True, "empresa": buscar_por_rfc(rfc) or rfc, "lista": [
            {"id": c["id"], "periodo": c.get("periodo") or "—", "meses": c.get("meses") or "—",
             "creado": str(c.get("creado") or "")[:19], "filas": c["n_filas"], "conc": c["n_conciliadas"]}
            for c in concs]}

    def concil_detalle(self, cid) -> dict:
        try:
            import persistencia as _persist
            p = _persist.FirebirdPersistencia(); p.inicializar()
            try:
                filas = p.leer_filas(int(cid))
            finally:
                p.cerrar()
        except Exception as e:
            return {"ok": False, "msg": str(e)}
        return {"ok": True, "filas": [
            {"id": f.id, "banco": f.banco, "fecha": f.fecha, "concepto": (f.concepto or "")[:160],
             "retiro": f.retiro or 0, "deposito": f.deposito or 0, "uuid": f.uuid_cfdi or "",
             "tipo": f.tipo or "", "match": f.tipo_match or ""} for f in filas]}

    def concil_eliminar_bd(self, cid) -> dict:
        try:
            import persistencia as _persist
            p = _persist.FirebirdPersistencia(); p.inicializar()
            try:
                n = p.eliminar_conciliacion(int(cid))
            finally:
                p.cerrar()
        except Exception as e:
            return {"ok": False, "msg": str(e)}
        return {"ok": True, "msg": f"Conciliación #{cid} eliminada ({n} fila[s])."}

    def concil_subir_excel(self, rfc) -> dict:
        rfc = (rfc or "").strip().upper()
        if not rfc:
            return {"ok": False, "msg": "Selecciona una empresa en el Paso 3 primero."}
        sel = self._elegir_archivos(("Excel (*.xlsm;*.xlsx)", "Todos (*.*)"))
        if not sel:
            return {"ok": False, "cancelado": True}
        try:
            import reimportar
            st = reimportar.subir_excel(sel[0], rfc, resolver=self._resolver_conflicto, usuario=self._usuario)
        except Exception as e:
            return {"ok": False, "msg": str(e)}
        cid = st.get("conciliacion_id")
        msg = ("Filas leidas: " + str(st.get("filas", 0)) + "\n" +
               ("Conciliación identificada: #" + str(cid) + "\n" if cid else
                "Conciliación: no identificada (sin ID en propiedades del archivo)\n") +
               "Guardadas/actualizadas en la BD: " + str(st.get("upsert", 0)) + "\n")
        if st.get("conflictos"):
            msg += ("Conflictos de concurrencia: " + str(st["conflictos"]) + "  (descartados: "
                    + str(st.get("descartados", 0)) + "; en bitacora)\n")
        sin = st.get("sin_id", 0)
        if sin:
            msg += ("\n⚠ " + str(sin) + " fila(s) NO se actualizaron: no casaron con la base.\n"
                    "• Formato NUEVO: su ID (columna A) no existe en esta conciliación.\n"
                    "• Formato VIEJO (sin columna ID): no coincidió por fecha/monto/descripción, o el "
                    "Excel abarca más movimientos que la conciliación.\nPara máxima precisión usa "
                    "'Reimprimir → Excel' (trae la columna ID y el identificador de la conciliación en "
                    "las propiedades), edítalo y vuelve a subirlo.")
        elif st.get("upsert"):
            msg += "\nTus correcciones quedaron guardadas."
        return {"ok": True, "msg": msg}

    def concil_reimprimir_generar(self, rfc, ids) -> dict:
        rfc = (rfc or "").strip().upper()
        ids = [int(i) for i in ids or []]
        if not ids:
            return {"ok": False, "msg": "Marca al menos una conciliacion."}
        try:
            import reimportar
            resultados, recibidos, emitidos, _st = reimportar.construir_desde_bd(rfc, conciliacion_ids=ids)
        except Exception as e:
            return {"ok": False, "msg": f"Error al reconstruir desde la BD:\n{e}"}
        if not resultados or not any((r.conciliados or r.sin_cfdi) for r in resultados):
            return {"ok": False, "msg": "Las conciliaciones elegidas no tienen filas."}
        ruta = self._guardar_como(f"Conciliaciones_{rfc}.xlsm" if len(ids) > 1 else f"Conciliacion_{rfc}.xlsm",
                                  ("Excel con macros (*.xlsm)", "Excel (*.xlsx)", "Todos (*.*)"))
        if not ruta:
            return {"ok": False, "cancelado": True}
        try:
            destino = _exp_concil_multi(resultados=resultados, todos_recibidos=recibidos,
                                        todos_emitidos=emitidos, output_path=ruta, rfc_empresa=rfc) or ruta
        except Exception as e:
            return {"ok": False, "msg": f"Error al generar el Excel:\n{e}"}
        return {"ok": True, "destino": destino, "n": len(ids)}

    # -- Descarga Masiva SAT (solo Web Service) --------------------------------------------
    def sat_meta(self) -> dict:
        return {"ok": _SAT_OK, "carpeta": str(sat_carpeta_base()),
                "max": _SAT.MAX_SOLICITUDES_DIA if _SAT_OK else 10,
                "rfcs": [r for r, _ in listar_empresas()],
                "f_ini": date.today().replace(day=1).isoformat(), "f_fin": date.today().isoformat()}

    def sat_elegir_archivo(self, ext):
        r = self._elegir_archivos((f"{ext} (*{ext})", "Todos (*.*)"))
        return r[0] if r else None

    def sat_elegir_carpeta(self):
        sel = self._elegir_carpetas()
        if sel:
            guardar_sat_carpeta_base(sel[0])
            return sel[0]
        return None

    def sat_descargar(self, p) -> dict:
        if not _SAT_OK:
            return {"ok": False, "msg": "Falta el paquete 'satcfdi'. Instala con: pip install satcfdi"}
        rfc = (p.get("rfc") or "").strip().upper()
        cer, key, pwd = (p.get("cer") or "").strip(), (p.get("key") or "").strip(), p.get("pwd") or ""
        carpeta_base = (p.get("carpeta") or "").strip() or str(sat_carpeta_base())
        if not rfc:
            return {"ok": False, "msg": "Selecciona o escribe el RFC."}
        if not cer or not key:
            return {"ok": False, "msg": "Selecciona los archivos .cer y .key."}
        if not pwd:
            return {"ok": False, "msg": "Ingresa la contraseña de la clave privada."}
        modo, tipos = p.get("modo", "fecha"), None
        if modo == "fecha":
            try:
                f_ini, f_fin = date.fromisoformat(p.get("f_ini", "").strip()), date.fromisoformat(p.get("f_fin", "").strip())
            except ValueError:
                return {"ok": False, "msg": "Usa el formato AAAA-MM-DD."}
            if f_ini > f_fin:
                return {"ok": False, "msg": "La fecha inicial debe ser anterior a la final."}
            tipos = {t for t in ("emitidos", "recibidos") if p.get(t)}
            if not tipos:
                return {"ok": False, "msg": "Marca al menos Emitidos o Recibidos."}
            extra = [u.strip() for u in (p.get("filtro") or "").splitlines() if u.strip()]
        else:
            f_ini = f_fin = None
            extra = [u.strip() for u in (p.get("uuids") or "").splitlines() if u.strip()]
            if not extra:
                return {"ok": False, "msg": "Ingresa al menos un UUID."}
        threading.Thread(target=self._sat_run, daemon=True,
                         args=(rfc, cer, key, pwd, modo, f_ini, f_fin, extra, carpeta_base, tipos)).start()
        return {"ok": True}

    def _sat_run(self, rfc, cer, key, pwd, modo, f_ini, f_fin, extra, carpeta_base, tipos):
        log = lambda m: self._js("sat.log", m)  # noqa: E731
        try:
            carpeta = Path(carpeta_base) / rfc / datetime.now().strftime("%Y%m%d_%H%M%S")
            signer = _SAT.cargar_fiel(cer, key, pwd)
            if signer.rfc.upper() != rfc:
                log(f"⚠ Aviso: la e.firma pertenece a {signer.rfc}, distinto del RFC seleccionado ({rfc}).")
            if modo == "fecha":
                resultado = _SAT.descargar_rango(signer=signer, fecha_inicial=f_ini, fecha_final=f_fin,
                                                 carpeta_destino=carpeta, callback=log, tipos=tipos)
                carpeta_final = carpeta
                if extra:
                    log(f"Filtrando localmente por {len(extra)} UUID(s)...")
                    carpeta_final = filtrar_por_uuid_local(carpeta, extra, log)
            else:
                resultado = _SAT.descargar_por_uuid(signer=signer, uuids=extra,
                                                    carpeta_destino=carpeta, callback=log)
                carpeta_final = carpeta / "por_uuid"
            if resultado.total_cfdi == 0:
                self._js("sat.fin", {"ok": False, "msg": "\n".join(resultado.errores) if resultado.errores
                                     else "El SAT no devolvió CFDIs para los criterios indicados."})
                return
            ruta = str(carpeta_final)
            if ruta not in self._k_carpetas:
                self._k_carpetas.append(ruta)
                self._k_carpetas_txt[ruta] = f"{ruta}  (SAT: {resultado.total_cfdi} CFDIs)"
            self._js("sat.fin", {"ok": True, "msg": f"{resultado.resumen()}\n\nSe agregaron a Conciliación CFDI (Paso 1).",
                                 "xml": self._k_vista_xml()})
        except Exception as exc:  # DescargaSATError incluido
            es_sat = _SAT_OK and isinstance(exc, _SAT.DescargaSATError)
            self._js("sat.fin", {"ok": False, "msg": str(exc) if es_sat else f"Error inesperado: {exc}"})
        finally:
            pwd = None  # noqa: F841 - la contraseña no sobrevive a la descarga
