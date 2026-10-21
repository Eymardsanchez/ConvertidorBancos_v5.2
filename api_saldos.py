"""Módulo Saldos a favor ISR/IVA (equivale a `_build_saldos_tab` + `_saldos_*` de la 5.0).

Lectura SIEMPRE en hilo (la ventana nunca se congela), con la misma caché Firebird
(`saldos_cache.CacheDeclaracionesFDB`) y la misma persistencia del análisis
(`DECLARACION_ANALISIS` + `SALDO_IVA`) que la 5.0.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from sat_saldos import pipeline as P
from sat_saldos.analyzer_iva_acumulado import etiqueta_mes
from sat_saldos.pdf_a_md import ruta_md


def _f(v) -> float:
    return float(v or 0)


class SaldosApi:
    def _saldos_init(self):
        self._s_rutas: list[str] = []
        self._s_cargados = None
        self._s_res = None
        self._s_ocupado = threading.Lock()

    # -- archivos -----------------------------------------------------------------
    def saldos_carpetas(self):
        return self._s_sumar(self._elegir_carpetas())

    def saldos_archivos(self):
        return self._s_sumar(self._elegir_archivos(("PDF o ZIP (*.pdf;*.zip)",)))

    def saldos_fijar_rutas(self, rutas):           # usado por la prueba automática
        self._s_rutas = list(rutas)
        return self._s_rutas

    def _s_sumar(self, sel):
        for s in sel:
            if s not in self._s_rutas:
                self._s_rutas.append(s)
        return self._s_rutas

    def saldos_limpiar(self):
        self._s_rutas, self._s_cargados, self._s_res = [], None, None
        return self._s_rutas

    # -- lectura (hilo) ---------------------------------------------------------
    def saldos_analizar(self):
        if not self._s_rutas:
            return {"ok": False, "msg": "Agrega al menos una carpeta, PDF o ZIP."}
        if not self._s_ocupado.acquire(blocking=False):
            return {"ok": False, "msg": "Ya hay una lectura en curso."}
        threading.Thread(target=self._s_leer, daemon=True).start()
        return {"ok": True}

    def _s_leer(self):
        t0 = time.perf_counter()
        cache_p = None
        try:
            pdfs = P.expandir_entradas([Path(r) for r in self._s_rutas])
            cache = None
            try:   # conexión Firebird LOCAL a este hilo (igual que la 5.0)
                from persistencia import FirebirdPersistencia
                from saldos_cache import CacheDeclaracionesFDB
                cache_p = FirebirdPersistencia()
                cache_p.inicializar()
                cache = CacheDeclaracionesFDB(cache_p)
            except Exception:
                cache = None
            self._s_cargados = c = P.cargar(
                pdfs, cache=cache,
                progreso=lambda i, n, nom: self._js("saldos.progreso", i + 1, n, nom))
            rfcs = c.rfcs()
            self._js("saldos.cargado", {
                "pdfs": c.n_pdfs, "acuses": len(c.declaraciones), "detalles": len(c.detalles),
                "pagos": len(c.pagos), "no_legibles": c.no_legibles[:20], "rfcs": rfcs,
                "segundos": round(time.perf_counter() - t0, 1)})
            if rfcs:
                self._js("saldos.resultado", self.saldos_calcular(rfcs[0], None))
        except Exception as e:  # noqa
            import traceback
            self._js("saldos.error", f"{e}\n\n{traceback.format_exc()}")
        finally:
            if cache_p is not None:
                try:
                    cache_p.cerrar()
                except Exception:
                    pass
            self._s_ocupado.release()

    # -- análisis -----------------------------------------------------------------
    def saldos_calcular(self, rfc, saldo_inicial):
        if not self._s_cargados:
            return {"ok": False, "msg": "Primero lee los PDFs."}
        ini = _f(saldo_inicial) or None
        self._s_res = res = P.analizar(self._s_cargados, rfc=rfc, saldo_inicial_iva=ini)
        acum = res.iva_acumulado
        base = (ini or 0) or (acum.saldo_inicial_requerido if acum else 0)
        archivo_por_op = {d.operacion: d.archivo for d in self._s_cargados.detalles}
        filas, running = [], base
        for r in (acum.renglones if acum else []):
            running += r.a_favor_generado - r.acreditamiento
            fp = getattr(r, "fecha_presentacion", None)
            md = ruta_md(res.rfc, archivo_por_op.get(r.operacion, "")) if r.operacion in archivo_por_op else None
            filas.append({
                "periodo": etiqueta_mes(r.ejercicio, r.periodo),
                "operacion": r.operacion or "—",
                "fecha": fp.strftime("%d/%m/%Y %H:%M") if fp else "—",
                "cargo": _f(r.a_cargo_periodo), "generado": _f(r.a_favor_generado),
                "acreditado": _f(r.acreditamiento), "remanente": round(running, 2),
                "regimen": getattr(r, "regimen", "") or "",
                "revisar": bool(getattr(r, "revisar", False)),
                "md": str(md) if md and md.exists() else "",
            })
        pagos = [{
            "periodo": etiqueta_mes(p.ejercicio, p.periodo) if p.periodo else str(p.ejercicio),
            "tipo": p.tipo[:4], "operacion": p.operacion or "—", "venc": p.vencimiento or "—",
            "contrib": _f(p.contribucion), "actualiz": _f(p.actualizacion), "recargos": _f(p.recargos),
            "importe": _f(p.importe_a_pagar), "pagado": _f(p.importe_pagado),
            "fecha_pago": p.fecha_pago or "—", "ok": bool(p.pagado),
        } for p in res.pagos]
        isr_acum = getattr(res, "isr_acumulado", None)
        filas_isr = []
        if isr_acum and isr_acum.renglones:
            for r in isr_acum.renglones:
                fp = r.fecha_presentacion
                filas_isr.append({
                    "periodo": f"Anual-{r.ejercicio}" if r.es_anual
                               else etiqueta_mes(r.ejercicio, r.periodo),
                    "operacion": r.operacion or "—",
                    "fecha": fp.strftime("%d/%m/%Y %H:%M") if fp else "—",
                    "ingresos": r.ingresos, "utilidad": r.utilidad_fiscal,
                    "perdidas": r.perdidas_aplicadas, "causado": r.impuesto_causado,
                    "pagos_prov": r.pagos_prov_anteriores, "retenido": r.isr_retenido,
                    "compensado": r.compensaciones, "cargo": r.impuesto_a_cargo,
                    "favor": r.saldo_a_favor, "regimen": r.regimen or "—",
                    "es_anual": r.es_anual,
                })
        self._s_persistir(res)
        return {
            "ok": True, "rfc": res.rfc, "razon": res.razon_social, "regimen": res.regimen,
            "vigentes": res.n_vigentes, "remanente_isr": _f(res.remanente_isr_total),
            "iva": {"generado": _f(acum.total_generado) if acum else 0,
                    "acreditado": _f(acum.total_acreditado) if acum else 0,
                    "neto": _f(acum.neto) if acum else 0,
                    "cierre": round(base + (acum.neto if acum else 0), 2),
                    "nota": (acum.nota if acum else res.iva.texto_alcance)},
            "isr": {"total_pagos_prov": _f(isr_acum.total_pagos_provisionales) if isr_acum else 0,
                    "pagos_prov_anual": _f(isr_acum.pagos_prov_reportados_anual) if isr_acum else None,
                    "nota": (isr_acum.nota if isr_acum else "")},
            "filas": filas, "pagos": pagos, "filas_isr": filas_isr,
        }

    def _s_persistir(self, res):
        """Misma lógica que `_saldos_persistir` de la 5.0 (SALDO_IVA, DECLARACION_ANALISIS,
        SALDO_PAGO), pero en hilo aparte: guardar en la BD nunca detiene la pantalla."""
        def _guardar():
            rfc = (getattr(res, "rfc", "") or "").strip().upper()
            if not rfc:
                return
            try:
                from persistencia import FirebirdPersistencia
                p = FirebirdPersistencia(); p.inicializar()
            except Exception:
                return
            try:
                acum = getattr(res, "iva_acumulado", None)
                for r in (getattr(acum, "renglones", None) or []):
                    ej = getattr(r, "ejercicio", None); pe = getattr(r, "periodo", None)
                    if not ej or not pe:
                        continue
                    fp = getattr(r, "fecha_presentacion", None)
                    _ac = getattr(r, "a_cargo_periodo", 0) or 0
                    _acr = getattr(r, "acreditamiento", 0) or 0
                    p.guardar_saldo_iva(
                        rfc, ej, pe, operacion=str(getattr(r, "operacion", "") or ""),
                        fecha=(fp.strftime("%Y-%m-%d") if hasattr(fp, "strftime") else str(fp or "")),
                        a_cargo=_ac,
                        a_favor=getattr(r, "a_favor_generado", 0) or 0,
                        acreditado=_acr,
                        remanente=getattr(r, "remanente_desde_cero", 0) or 0)
                    p.guardar_analisis_declaracion(
                        rfc, ej, pe, operacion=str(getattr(r, "operacion", "") or ""),
                        tipo="IVA", subtipo=str(getattr(r, "subtipo", "") or ""),
                        fecha_presentacion=(fp.strftime("%Y-%m-%d %H:%M") if hasattr(fp, "strftime") else str(fp or "")),
                        a_cargo=_ac,
                        a_favor=getattr(r, "a_favor_generado", 0) or 0,
                        acreditamiento=_acr,
                        impuesto_cargo=max(_ac - _acr, 0),
                        remanente=getattr(r, "remanente_desde_cero", 0) or 0)
                for pg in (getattr(res, "pagos", None) or []):
                    ej = getattr(pg, "ejercicio", None); pe = getattr(pg, "periodo", None)
                    if not ej or not pe:
                        continue
                    p.guardar_saldo_pago(
                        rfc, ej, pe, str(getattr(pg, "operacion", "") or "-"),
                        tipo=str(getattr(pg, "tipo", "") or ""),
                        vencimiento=str(getattr(pg, "vencimiento", "") or ""),
                        contribucion=getattr(pg, "contribucion", 0) or 0,
                        actualizacion=getattr(pg, "actualizacion", 0) or 0,
                        recargos=getattr(pg, "recargos", 0) or 0,
                        importe_pagar=getattr(pg, "importe_a_pagar", 0) or 0,
                        importe_pagado=getattr(pg, "importe_pagado", 0) or 0,
                        fecha_pago=str(getattr(pg, "fecha_pago", "") or ""),
                        estatus=("Pagado" if getattr(pg, "pagado", False) else "Sin comprobante"))
            except Exception:
                pass
            finally:
                try:
                    p.cerrar()
                except Exception:
                    pass
        threading.Thread(target=_guardar, daemon=True).start()

    def saldos_ver_md(self, ruta):
        if ruta and Path(ruta).exists():
            os.startfile(ruta)  # noqa: S606 - abre el MD con el programa del usuario
            return True
        return False

    def saldos_excel(self, saldo_inicial):
        if not self._s_res:
            return {"ok": False, "msg": "Primero analiza."}
        ruta = self._guardar_como(f"SaldosFavor_{self._s_res.rfc}.xlsx", ("Excel (*.xlsx)",))
        if not ruta:
            return {"ok": False, "msg": "Cancelado."}
        P.generar_xlsx(self._s_res, Path(ruta), saldo_inicial_iva=_f(saldo_inicial) or None)
        return {"ok": True, "ruta": ruta}
