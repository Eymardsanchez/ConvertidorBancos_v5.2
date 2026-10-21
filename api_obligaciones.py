"""Módulo Obligaciones Fiscales (equivale a `_build_compliance_tab` y sus 5 pestañas,
`_cargar_y_procesar`, `_confirmar_rfcs`, `_procesar_declaraciones`, reportes,
`_persistir_declaraciones_carga` y `_DialogEnvioCompliance` de la 5.0).

Diferencia deliberada (el motivo de la 5.2): la LECTURA de declaraciones corre en
hilo con avance; en la 5.0 corría en el hilo de la ventana y la congelaba
("No responde"). La lógica de marcado/copia/alimentación es la misma.
"""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
from datetime import date
from pathlib import Path

import compliance_engine as CE
from config_email import cargar_email_cfg
from email_sender import PROVIDERS, enviar_correo
from empresas import buscar_por_rfc, listar_empresas, obtener_empresa, registrar_desde_cif

# Mapa categoría (sat_saldos) → obligación del catálogo compliance (igual a la 5.0)
_CAT_A_OBLIG = {
    "ISR_PM": "isr_declaracion",
    "ISR_RET_SUELDOS": "isr_ret_declaracion",
    "ISR_RET_ASIMILADOS": "isr_ret_declaracion",
    "IVA": "iva_declaracion",
    "IVA_RET": "iva_ret_declaracion",
}


def _f(x) -> float:
    try:
        return float(x or 0)
    except Exception:
        return 0.0


def _fecha_iso(fp) -> str:
    try:
        return fp.date().isoformat() if hasattr(fp, "date") else (str(fp)[:10] if fp else "")
    except Exception:
        return ""


def _anio_default() -> int:
    try:
        ys = CE.anios_disponibles()
        hoy = date.today().year
        return hoy if hoy in ys else (max(ys) if ys else hoy)
    except Exception:
        return date.today().year


class ObligacionesApi:
    def _oblig_init(self):
        self._o_cargados = None
        self._o_mapa: dict = {}
        self._o_ocupado = threading.Lock()
        self._o_rep = None

    # -- datos generales ------------------------------------------------------------
    def compl_meta(self) -> dict:
        return {"meses": CE.MESES_ES, "anios": [int(y) for y in CE.anios_disponibles()],
                "anio_default": _anio_default(), "mes_actual": date.today().month,
                "empresas": [{"rfc": r, "nombre": n} for r, n in listar_empresas()]}

    # -- Panel General ---------------------------------------------------------------
    def compl_panel(self, mes, anio) -> list[dict]:
        mes, anio = int(mes), int(anio)
        out = []
        for rfc, nombre in listar_empresas():
            cfg = CE.obtener_config(rfc)
            obs = CE.obligaciones_del_mes(cfg, mes)
            arcs = CE.listar_archivos_mes(cfg, anio, mes)
            dest = cfg.get("destinatario", "")
            if not dest:
                estado, tag = "⚠ Sin destinatario", "err"
            elif not cfg.get("carpeta_raiz"):
                estado, tag = "⚠ Sin carpeta", "warn"
            elif not obs:
                estado, tag = "⚠ Sin obligaciones", "warn"
            else:
                estado, tag = "✅ Listo", "ok"
            out.append({"nombre": nombre, "rfc": rfc, "dest": dest, "obs": len(obs),
                        "carpeta": "✅" if cfg.get("carpeta_raiz") else "⚠",
                        "archivos": str(len(arcs)) if cfg.get("carpeta_raiz") else "–",
                        "estado": estado, "tag": tag})
        return out

    def compl_envio_masivo_lista(self) -> list[dict]:
        return [{"rfc": r, "nombre": n} for r, n in listar_empresas()
                if CE.obtener_config(r).get("destinatario")]

    # -- Obligaciones por empresa -----------------------------------------------------
    def compl_obligs(self, rfc, mes, anio) -> dict:
        rfc = (rfc or "").strip().upper()
        nombre = buscar_por_rfc(rfc) if rfc else None
        activas = set(CE.obtener_config(rfc).get("obligaciones_activas", CE.TODOS_IDS)) if nombre \
            else set(CE.TODOS_IDS)
        presentadas = {}
        try:
            if nombre:
                CE.sincronizar_presentaciones(rfc, int(anio), int(mes))
                presentadas = CE.obtener_presentaciones(rfc, int(anio), int(mes))
        except Exception:
            presentadas = {}
        filas = []
        for o in CE.OBLIGACIONES_CATALOGO:
            pr = presentadas.get(o["id"])
            filas.append({"id": o["id"], "nombre": o["nombre"], "periodicidad": o["periodicidad"],
                          "meses": ",  ".join(CE.MESES_ES[m][:3] for m in o["meses_aplica"]),
                          "activa": o["id"] in activas,
                          "presentada": (f"✅ {pr.get('fecha_presentacion', '')}  ·  op "
                                         f"{pr.get('numero_operacion', '')}") if pr else ""})
        return {"nombre": nombre, "registrado": bool(nombre), "filas": filas}

    def compl_obligs_guardar(self, rfc, activas) -> dict:
        rfc = (rfc or "").strip().upper()
        if not rfc:
            return {"ok": False, "msg": "Selecciona primero una empresa."}
        if not buscar_por_rfc(rfc):
            return {"ok": False, "msg": "Registra la empresa primero en el catálogo de empresas."}
        cfg = CE.obtener_config(rfc)
        cfg["obligaciones_activas"] = list(activas)
        CE.guardar_config(rfc, cfg)
        return {"ok": True, "msg": "✅ Obligaciones guardadas."}

    # -- Archivos ---------------------------------------------------------------------
    def compl_archivos(self, rfc, mes, anio) -> dict:
        rfc = (rfc or "").strip().upper()
        mes, anio = int(mes), int(anio)
        cfg = CE.obtener_config(rfc)
        ruta = CE.carpeta_mes(cfg, anio, mes)
        if not ruta:
            return {"ruta": None, "esperada": os.path.join(cfg.get("carpeta_raiz", ""),
                                                            f"{anio:04d}-{mes:02d}"), "archivos": []}
        return {"ruta": ruta, "archivos": [
            {"nombre": a["nombre"], "tam": CE.formato_tamano(a["tamano"]), "mtime": a["mtime"],
             "ext": os.path.splitext(a["nombre"])[1].lower()}
            for a in CE.listar_archivos_mes(cfg, anio, mes)]}

    def compl_abrir_carpeta(self, rfc, mes, anio) -> dict:
        cfg = CE.obtener_config((rfc or "").strip().upper())
        ruta = CE.carpeta_mes(cfg, int(anio), int(mes))
        if ruta:
            os.startfile(ruta)  # noqa: S606
            return {"ok": True}
        raiz = cfg.get("carpeta_raiz", "")
        if raiz and os.path.isdir(raiz):
            os.startfile(raiz)  # noqa: S606
            return {"ok": True}
        return {"ok": False, "msg": "Carpeta no encontrada. Verifica la configuración."}

    # -- Config Empresa ---------------------------------------------------------------
    def compl_cc_cargar(self, rfc) -> dict:
        rfc = (rfc or "").strip().upper()
        nombre = buscar_por_rfc(rfc) if rfc else None
        emp = obtener_empresa(rfc) if rfc else None
        reg, reg_ok = "", None
        if emp:
            codigos, nombres = emp.get("regimenes", []), emp.get("regimenes_nombres", [])
            if codigos and nombres:
                reg, reg_ok = "✔  Régimen(es): " + ",  ".join(f"{n} ({c})" for n, c in zip(nombres, codigos)), True
            elif codigos:
                reg, reg_ok = "Régimen(es): " + ", ".join(codigos), True
            else:
                reg, reg_ok = "Sin CSF registrada — sube la Constancia de Situación Fiscal", False
        cfg = CE.obtener_config(rfc) if nombre else {}
        return {"nombre": nombre, "regimen": reg, "regimen_ok": reg_ok,
                "cfg": {k: cfg.get(k, "") for k in ("destinatario", "cc", "asunto_template",
                                                     "carpeta_raiz", "notas_adicionales")}}

    def compl_cc_guardar(self, rfc, datos) -> dict:
        rfc = (rfc or "").strip().upper()
        if not rfc:
            return {"ok": False, "msg": "Selecciona una empresa."}
        cfg = CE.obtener_config(rfc)
        for k in ("destinatario", "cc", "asunto_template", "carpeta_raiz", "notas_adicionales"):
            cfg[k] = (datos or {}).get(k, "")
        CE.guardar_config(rfc, cfg)
        return {"ok": True, "msg": "✅ Configuración compliance guardada."}

    def compl_cc_subir_csf(self) -> dict:
        sel = self._elegir_archivos(("PDF (*.pdf)", "Todos (*.*)"))
        if not sel:
            return {"ok": False, "cancelado": True}
        try:
            ok, msg, datos = registrar_desde_cif(sel[0])
            return {"ok": bool(ok and datos), "msg": msg, "rfc": getattr(datos, "rfc", None)}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def compl_cc_buscar_carpeta(self):
        sel = self._elegir_carpetas()
        return sel[0] if sel else None

    def compl_anios(self, texto=None) -> dict:
        if texto is None:
            texto = CE.formatear_anios(CE.cargar_anios())
        ys = CE.parsear_anios(texto)
        return {"texto": texto, "validos": ys, "fmt": CE.formatear_anios(ys) if ys else "",
                "min": CE.ANIO_MIN, "max": CE.ANIO_MAX, "hoy": date.today().year}

    def compl_anios_guardar(self, texto) -> dict:
        ys = CE.parsear_anios(texto or "")
        CE.guardar_anios(ys)
        return {"ok": True, "msg": ("Años guardados: " + CE.formatear_anios(ys)) if ys else
                "Sin años válidos: se usará el rango completo 2015–2040.",
                "anios": [int(y) for y in CE.anios_disponibles()]}

    # -- Carga de declaraciones (EN HILO) -------------------------------------------
    def compl_cargar_archivos(self):
        sel = self._elegir_archivos(("PDF/ZIP (*.pdf;*.zip)", "Todos (*.*)"))
        return self._o_iniciar_carga(sel)

    def compl_cargar_carpeta(self):
        return self._o_iniciar_carga(self._elegir_carpetas()[:1])

    def compl_cargar_rutas(self, rutas):            # usado por la prueba automática
        return self._o_iniciar_carga(list(rutas))

    def _o_iniciar_carga(self, entradas):
        if not entradas:
            return {"ok": False, "cancelado": True}
        if not self._o_ocupado.acquire(blocking=False):
            return {"ok": False, "msg": "Ya hay una carga en curso."}
        threading.Thread(target=self._o_leer, args=(entradas,), daemon=True).start()
        return {"ok": True}

    def _o_leer(self, entradas):
        from sat_saldos import pipeline as P
        t0 = time.perf_counter()
        cache_p = None
        try:
            pdfs = P.expandir_entradas([Path(x) for x in entradas])
            cache = None
            try:   # misma caché Firebird que Saldos: lo ya leído no se vuelve a leer
                from persistencia import FirebirdPersistencia
                from saldos_cache import CacheDeclaracionesFDB
                cache_p = FirebirdPersistencia()
                cache_p.inicializar()
                cache = CacheDeclaracionesFDB(cache_p)
            except Exception:
                cache = None
            self._o_cargados = c = P.cargar(
                pdfs, cache=cache,
                progreso=lambda i, n, nom: self._js("compl.progreso", i + 1, n, nom))
            self._o_persistir_carga(c)
            mapa: dict = {}

            def _reg(rfc, archivo):
                rfc = (rfc or "").strip().upper()
                if not rfc:
                    return
                d = mapa.setdefault(rfc, {"docs": 0, "archivos": set(), "nombre": None})
                d["docs"] += 1
                if archivo:
                    d["archivos"].add(str(archivo))
            for dec in c.declaraciones:
                _reg(dec.rfc, dec.archivo)
            for pg in c.pagos:
                _reg(getattr(pg, "rfc", None), getattr(pg, "archivo", None))
            for det in c.detalles:
                _reg(getattr(det, "rfc", None), getattr(det, "archivo", None))
            for r in mapa:
                mapa[r]["nombre"] = buscar_por_rfc(r)
            self._o_mapa = mapa
            self._js("compl.leido", {
                "segundos": round(time.perf_counter() - t0, 1), "pdfs": c.n_pdfs,
                "rfcs": [{"rfc": r, "docs": d["docs"], "nombre": d["nombre"]}
                         for r, d in sorted(mapa.items())]})
        except Exception as e:  # noqa
            import traceback
            self._js("compl.error", f"Error al leer: {e}\n\n{traceback.format_exc()}")
        finally:
            if cache_p is not None:
                try:
                    cache_p.cerrar()
                except Exception:
                    pass
            self._o_ocupado.release()

    def _o_persistir_carga(self, cargados):
        """Igual que `_persistir_declaraciones_carga` de la 5.0 (tabla DECLARACION_DYP)."""
        try:
            from persistencia import FirebirdPersistencia
            p = FirebirdPersistencia(); p.inicializar()
        except Exception:
            return
        try:
            for dec in cargados.declaraciones:
                rfc = (getattr(dec, "rfc", "") or "").strip().upper()
                ej, per = getattr(dec, "ejercicio", None), getattr(dec, "periodo", None)
                op = getattr(dec, "operacion", None) or "-"
                if not rfc or not ej or not per:
                    continue
                cjs = ""
                try:
                    cjs = json.dumps([{"nombre": getattr(c, "nombre", ""),
                                       "a_cargo": getattr(c, "a_cargo", None),
                                       "a_favor": getattr(c, "a_favor", None),
                                       "cantidad_pagar": getattr(c, "cantidad_pagar", None),
                                       "cantidad_cargo": getattr(c, "cantidad_cargo", None)}
                                      for c in (dec.conceptos or [])], ensure_ascii=False)
                except Exception:
                    pass
                p.guardar_declaracion_dyp(
                    rfc, ej, per, op, tipo=getattr(dec, "tipo", "") or "",
                    subtipo=getattr(dec, "subtipo", "") or "",
                    fecha_pres=getattr(dec, "fecha_presentacion", None),
                    archivo=getattr(dec, "archivo", "") or "",
                    razon_social=getattr(dec, "razon_social", "") or "",
                    es_anual=bool(getattr(dec, "es_anual", False)),
                    origen="declaracion", conceptos_json=cjs)
            for det in cargados.detalles:
                rfc = (getattr(det, "rfc", "") or "").strip().upper()
                ej, per = getattr(det, "ejercicio", None), getattr(det, "periodo", None)
                op = getattr(det, "operacion", None) or "-"
                if not rfc or not ej or not per:
                    continue
                p.guardar_declaracion_dyp(
                    rfc, ej, per, op, subtipo=getattr(det, "subtipo", "") or "",
                    fecha_pres=getattr(det, "fecha_presentacion", None),
                    archivo=getattr(det, "archivo", "") or "", origen="detalle_iva",
                    iva_a_cargo=getattr(det, "a_cargo_periodo", None),
                    iva_a_favor=getattr(det, "a_favor_periodo", None),
                    iva_acredit_ant=getattr(det, "acreditamiento_anterior", None),
                    iva_cargo_final=getattr(det, "impuesto_a_cargo_final", None))
            for pg in cargados.pagos:
                rfc = (getattr(pg, "rfc", "") or "").strip().upper()
                ej, per = getattr(pg, "ejercicio", None), getattr(pg, "periodo", None)
                op = getattr(pg, "operacion", None) or "-"
                if not rfc or not ej or not per:
                    continue
                p.guardar_declaracion_dyp(
                    rfc, ej, per, op, tipo=getattr(pg, "tipo", "") or "",
                    subtipo=getattr(pg, "subtipo", "") or "",
                    fecha_pres=getattr(pg, "fecha_presentacion", None),
                    archivo=getattr(pg, "archivo", "") or "",
                    razon_social=getattr(pg, "razon_social", "") or "", origen="pago")
        except Exception:
            pass
        finally:
            try:
                p.cerrar()
            except Exception:
                pass

    def compl_procesar(self, seleccion) -> dict:
        """Tras confirmar los RFC: alimenta Saldos y marca/copia (5.0:
        `_cargar_y_procesar` 2ª mitad + `_procesar_declaraciones`). Corre en el hilo
        de la llamada de pywebview, no en el de la ventana."""
        seleccion = {s.strip().upper() for s in (seleccion or [])}
        if not seleccion or not self._o_cargados:
            return {"ok": False, "msg": "Nada seleccionado."}
        archivos_ok = set()
        for r in seleccion:
            archivos_ok |= self._o_mapa.get(r, {}).get("archivos", set())
        if archivos_ok:
            self._s_sumar(sorted(archivos_ok))
        resumen = self._o_procesar(self._o_cargados, seleccion)
        self._js("saldos.pintarRutas", self._s_rutas)
        return {"ok": True, "msg": resumen, "rfcs": sorted(seleccion)}

    def _o_procesar(self, cargados, rfcs_permitidos) -> str:
        from sat_saldos.config import clasifica_concepto
        hechas, rutas_saldos = set(), set()
        marcadas = 0
        empresas, no_reg = set(), set()
        omit = {"no_reg": 0, "anual": 0, "sin_periodo": 0, "no_clasif": 0}

        def _copiar(rfc, anio, mes, archivo):
            destino_dir = CE.asegurar_carpeta_mes(CE.obtener_config(rfc), anio, mes)
            if destino_dir and archivo and os.path.isfile(archivo):
                try:
                    dest = os.path.join(destino_dir, os.path.basename(archivo))
                    if os.path.abspath(dest) != os.path.abspath(archivo):
                        shutil.copy2(archivo, dest)
                    return dest
                except Exception:
                    return archivo
            return archivo or ""

        def _procesa(rfc, ejercicio, periodo, es_anual, operacion, fp, archivo, conceptos):
            nonlocal marcadas
            rfc = (rfc or "").strip().upper()
            if not rfc or (rfcs_permitidos is not None and rfc not in rfcs_permitidos):
                return
            if not buscar_por_rfc(rfc):
                omit["no_reg"] += 1; no_reg.add(rfc); return
            if es_anual:
                omit["anual"] += 1; return
            if not periodo or not (1 <= int(periodo) <= 12) or not ejercicio:
                omit["sin_periodo"] += 1; return
            anio, mes = int(ejercicio), int(periodo)
            tiene_amt, obligs = False, set()
            for c in conceptos or []:
                ob = _CAT_A_OBLIG.get(clasifica_concepto(getattr(c, "nombre", "") or ""))
                if not ob:
                    continue
                obligs.add(ob)
                if (_f(getattr(c, "a_cargo", None)) or _f(getattr(c, "a_favor", None))
                        or _f(getattr(c, "cantidad_pagar", None))
                        or _f(getattr(c, "cantidad_a_pagar", None))
                        or _f(getattr(c, "cantidad_cargo", None))
                        or _f(getattr(c, "cantidad_a_cargo", None))):
                    tiene_amt = True
            if not obligs:
                omit["no_clasif"] += 1; return
            guardado = _copiar(rfc, anio, mes, archivo)
            fecha = _fecha_iso(fp)
            for ob in obligs:
                clave = (rfc, anio, mes, ob)
                if clave in hechas:
                    continue
                hechas.add(clave)
                try:
                    CE.marcar_presentacion(rfc, anio, mes, ob, archivo=guardado,
                                           fecha_presentacion=fecha,
                                           numero_operacion=operacion or "",
                                           usuario=self._usuario)
                    marcadas += 1; empresas.add(rfc)
                except Exception:
                    pass
            if tiene_amt and guardado:
                rutas_saldos.add(guardado)

        for dec in cargados.declaraciones:
            _procesa(dec.rfc, dec.ejercicio, dec.periodo, getattr(dec, "es_anual", False),
                     dec.operacion, dec.fecha_presentacion, dec.archivo, dec.conceptos)
        for pg in cargados.pagos:
            _procesa(getattr(pg, "rfc", None), getattr(pg, "ejercicio", None),
                     getattr(pg, "periodo", None), False, getattr(pg, "operacion", None),
                     getattr(pg, "fecha_presentacion", None), getattr(pg, "archivo", None),
                     getattr(pg, "conceptos", None))
        for det in cargados.detalles:
            _rfc, _ej, _per = getattr(det, "rfc", None), getattr(det, "ejercicio", None), getattr(det, "periodo", None)
            if _rfc and _ej and _per and rfcs_permitidos and _rfc.upper() in rfcs_permitidos \
                    and buscar_por_rfc(_rfc):
                clave = (_rfc.upper(), int(_ej), int(_per), "IVA")
                if clave in hechas:
                    continue
                hechas.add(clave)
                guardado = _copiar(_rfc, int(_ej), int(_per), getattr(det, "archivo", None) or "")
                try:
                    CE.marcar_presentacion(_rfc, int(_ej), int(_per), "IVA", archivo=guardado,
                                           fecha_presentacion=_fecha_iso(getattr(det, "fecha_presentacion", None)),
                                           numero_operacion=getattr(det, "operacion", "") or "",
                                           usuario=self._usuario)
                    marcadas += 1; empresas.add(_rfc.upper())
                except Exception:
                    pass
                if guardado:
                    rutas_saldos.add(guardado)

        alimentadas = 0
        if rutas_saldos:
            self._s_sumar(sorted(rutas_saldos))
            alimentadas = len(rutas_saldos)
        partes = [f"✅ {marcadas} obligación(es) marcada(s) en {len(empresas)} empresa(s)."]
        if alimentadas:
            partes.append(f"{alimentadas} con ISR/IVA → «Saldos a favor ISR/IVA» (pulsa ANALIZAR ahí).")
        if omit["no_reg"]:
            partes.append(f"{omit['no_reg']} de RFC no registrado ({', '.join(sorted(no_reg))}) "
                          "— regístralo en el catálogo de empresas.")
        if omit["anual"]:
            partes.append(f"{omit['anual']} anual(es) — no se marcan automáticamente.")
        if omit["sin_periodo"]:
            partes.append(f"{omit['sin_periodo']} sin periodo mensual claro.")
        if omit["no_clasif"]:
            partes.append(f"{omit['no_clasif']} no reconocida(s) como ISR/IVA/retención — revísalas.")
        if not any((marcadas, alimentadas, *omit.values())):
            partes = ["No se leyó ninguna declaración/acuse en la selección."]
        return "\n".join(partes)

    # -- Reportes (Excel / PDF / CSV / TXT) ------------------------------------------
    def compl_reporte(self, tipo, p) -> dict:
        import reportes as RP
        mes, anio = int(p.get("mes")), int(p.get("anio"))
        rep = None
        if tipo == "panel":
            filas, tot_ob, tot_pres = [], 0, 0
            for rfc, nombre in listar_empresas():
                cfg = CE.obtener_config(rfc)
                obs = CE.obligaciones_del_mes(cfg, mes)
                try:
                    pres = CE.obtener_presentaciones(rfc, anio, mes)
                except Exception:
                    pres = {}
                n_pres = sum(1 for o in obs if o["id"] in pres)
                arcs = CE.listar_archivos_mes(cfg, anio, mes)
                tot_ob += len(obs); tot_pres += n_pres
                filas.append([nombre, rfc, cfg.get("destinatario", ""), len(obs), n_pres,
                              len(obs) - n_pres, len(arcs),
                              f"{(n_pres / len(obs) * 100):.0f}%" if obs else "—"])
            rep = RP.Reporte(
                titulo="Panel General de Obligaciones", subtitulo="Cumplimiento por empresa del periodo",
                periodo=f"{CE.MESES_ES[mes]} {anio}",
                encabezados=["Empresa", "RFC", "Destinatario", "Obligaciones", "Presentadas",
                             "Pendientes", "Archivos", "Cumplimiento"],
                filas=filas, resumen=[("Empresas", len(filas)), ("Obligaciones totales", tot_ob),
                                      ("Presentadas", tot_pres), ("Pendientes", tot_ob - tot_pres)])
        elif tipo == "obligaciones":
            rfc = (p.get("rfc") or "").strip().upper()
            nombre = buscar_por_rfc(rfc) if rfc else None
            if not nombre:
                return {"ok": False, "msg": "Selecciona una empresa registrada."}
            activas = set(CE.obtener_config(rfc).get("obligaciones_activas", CE.TODOS_IDS))
            try:
                CE.sincronizar_presentaciones(rfc, anio, mes)
            except Exception:
                pass
            pres = CE.obtener_presentaciones(rfc, anio, mes)
            filas, n_pres = [], 0
            for o in CE.OBLIGACIONES_CATALOGO:
                if o["id"] not in activas or mes not in o["meses_aplica"]:
                    continue
                pr = pres.get(o["id"])
                n_pres += bool(pr)
                filas.append([o["nombre"], o["periodicidad"], "Sí" if pr else "No",
                              (pr or {}).get("fecha_presentacion", ""), (pr or {}).get("numero_operacion", ""),
                              os.path.basename((pr or {}).get("archivo", "") or "")])
            rep = RP.Reporte(
                titulo="Obligaciones", subtitulo="Estatus de cumplimiento del periodo",
                empresa=nombre, rfc=rfc, periodo=f"{CE.MESES_ES[mes]} {anio}",
                encabezados=["Obligación", "Periodicidad", "Presentada", "Fecha presentación",
                             "No. operación", "Archivo"],
                filas=filas, resumen=[("Obligaciones del mes", len(filas)), ("Presentadas", n_pres),
                                      ("Pendientes", len(filas) - n_pres),
                                      ("Cumplimiento", f"{(n_pres / len(filas) * 100):.0f}%" if filas else "—")])
        elif tipo == "saldos":
            rfc = (p.get("rfc") or "").strip().upper()
            if not rfc:
                return {"ok": False, "msg": "Elige el RFC (o analiza primero en Saldos a favor)."}
            filas = []
            try:
                from persistencia import FirebirdPersistencia
                bd = FirebirdPersistencia(); bd.inicializar()
                try:
                    for d in bd.leer_saldos_iva(rfc, anio, mes):
                        filas.append(["IVA", CE.MESES_ES[int(d["mes"])], d.get("operacion", ""),
                                      d.get("fecha", ""), d.get("a_cargo", 0), d.get("a_favor", 0),
                                      d.get("acreditado", 0), d.get("remanente", 0)])
                    for d in bd.leer_saldos_pago(rfc, anio, mes):
                        filas.append(["Pago " + (d.get("tipo") or ""), CE.MESES_ES[int(d["mes"])],
                                      d.get("operacion", ""), d.get("fecha_pago", ""),
                                      d.get("contribucion", 0), 0, 0, d.get("importe_pagado", 0)])
                finally:
                    bd.cerrar()
            except Exception:
                pass
            # ISR acumulado desde el último análisis en memoria
            isr_acum = None
            try:
                s_res = getattr(self, "_s_res", None)
                if s_res and getattr(s_res, "rfc", "") == rfc:
                    isr_acum = getattr(s_res, "isr_acumulado", None)
            except Exception:
                pass
            if isr_acum and isr_acum.renglones:
                for r in isr_acum.renglones:
                    per = f"Anual-{r.ejercicio}" if r.es_anual else (
                        CE.MESES_ES.get(r.periodo, str(r.periodo)) if r.periodo else "")
                    fp = r.fecha_presentacion
                    filas.append([f"ISR {'Anual' if r.es_anual else 'Mensual'}",
                                  per, r.operacion or "",
                                  fp.strftime("%d/%m/%Y") if fp else "",
                                  r.impuesto_a_cargo, r.saldo_a_favor,
                                  r.compensaciones, r.impuesto_causado])
            resumen = [("Renglones", len(filas))]
            if isr_acum and isr_acum.nota:
                resumen.append(("ISR nota", isr_acum.nota))
            rep = RP.Reporte(
                titulo="Contribuciones, Pagos y Saldos a Favor",
                subtitulo="IVA acumulado, ISR acumulado y pagos del periodo",
                empresa=buscar_por_rfc(rfc) or "", rfc=rfc, periodo=f"{CE.MESES_ES[mes]} {anio}",
                encabezados=["Concepto", "Mes", "No. operación", "Fecha", "A cargo", "A favor",
                             "Acreditado/Compensado", "Remanente/Causado"],
                filas=filas, resumen=resumen)
        elif tipo == "archivos":
            rfc = (p.get("rfc") or "").strip().upper()
            nombre = buscar_por_rfc(rfc) if rfc else None
            if not nombre:
                return {"ok": False, "msg": "Selecciona una empresa registrada."}
            cfg = CE.obtener_config(rfc)
            arcs = CE.listar_archivos_mes(cfg, anio, mes)
            ruta = CE.carpeta_mes(cfg, anio, mes) or ""
            filas = [[a["nombre"], os.path.splitext(a["nombre"])[1].lower().lstrip("."),
                      CE.formato_tamano(a["tamano"]), a["mtime"]] for a in arcs]
            rep = RP.Reporte(
                titulo="Archivos", subtitulo=f"Inventario de la carpeta del periodo. {ruta}",
                empresa=nombre, rfc=rfc, periodo=f"{CE.MESES_ES[mes]} {anio}",
                encabezados=["Archivo", "Tipo", "Tamaño", "Fecha modificación"], filas=filas,
                resumen=[("Archivos", len(filas)),
                         ("Tamaño total", CE.formato_tamano(sum(a["tamano"] for a in arcs)))])
        if rep is None:
            return {"ok": False, "msg": "Tipo de reporte desconocido."}
        self._o_rep = rep
        return {"ok": True, "titulo": rep.titulo, "meta": "  ·  ".join(rep.meta_lineas()[:2]),
                "n": len(rep.filas), "formatos": [{"id": f, "nombre": RP.NOMBRE_FORMATO[f]}
                                                  for f in RP.FORMATOS]}

    def compl_reporte_exportar(self, fmt) -> dict:
        import reportes as RP
        rep = self._o_rep
        if rep is None:
            return {"ok": False, "msg": "Genera el reporte primero."}
        ruta = self._guardar_como(RP.nombre_sugerido(rep, fmt),
                                  (f"{RP.NOMBRE_FORMATO[fmt]} (*{RP.EXT_FORMATO[fmt]})", "Todos (*.*)"))
        if not ruta:
            return {"ok": False, "cancelado": True}
        try:
            RP.exportar(rep, ruta, fmt)
        except Exception as e:
            return {"ok": False, "msg": str(e)}
        return {"ok": True, "ruta": ruta}

    def compl_abrir(self, ruta):
        if ruta and os.path.exists(ruta):
            os.startfile(ruta)  # noqa: S606
        return True

    # -- Preparar envío de correo (_DialogEnvioCompliance) ---------------------------
    def compl_envio_abrir(self, rfc, mes, anio) -> dict:
        rfc = (rfc or "").strip().upper()
        nombre = buscar_por_rfc(rfc) if rfc else None
        if not nombre:
            return {"ok": False, "msg": "Selecciona y carga una empresa."}
        cfg = CE.obtener_config(rfc)
        mes, anio = int(mes), int(anio)
        return {"ok": True, "empresa": nombre, "rfc": rfc, "mes": mes, "anio": anio,
                "mes_txt": CE.MESES_ES[mes], "carpeta": CE.carpeta_mes(cfg, anio, mes),
                "archivos": [{"nombre": a["nombre"], "ruta": a["ruta"], "tamano": a["tamano"],
                              "tam": CE.formato_tamano(a["tamano"])}
                             for a in CE.listar_archivos_mes(cfg, anio, mes)]}

    def compl_envio_agregar(self) -> list[dict]:
        out = []
        for r in self._elegir_archivos(("Todos (*.*)", "PDF (*.pdf)", "XML (*.xml)",
                                        "Excel (*.xlsx;*.xls)", "ZIP (*.zip)")):
            sz = os.path.getsize(r)
            out.append({"nombre": os.path.basename(r), "ruta": r, "tamano": sz,
                        "tam": CE.formato_tamano(sz)})
        return out

    def compl_envio_preview(self, rfc, mes, anio, rutas) -> dict:
        rfc = rfc.strip().upper()
        cfg = CE.obtener_config(rfc)
        tam = sum(os.path.getsize(r) for r in rutas if os.path.exists(r))
        return {"cuerpo": CE.generar_cuerpo(buscar_por_rfc(rfc), rfc, cfg, int(mes), int(anio),
                                            rutas or None),
                "cuenta": f"📎 {len(rutas)} archivo(s)  |  {CE.formato_tamano(tam)} total"}

    def compl_envio_confirmacion(self, rfc, mes, anio, rutas) -> dict:
        email_cfg = cargar_email_cfg()
        if not email_cfg.get("remitente") or not email_cfg.get("password"):
            return {"ok": False, "msg": "Configura el correo en  ⚙ Configuración → 📧 Email."}
        cfg = CE.obtener_config(rfc)
        dest_raw = cfg.get("destinatario", "").strip()
        if not dest_raw:
            return {"ok": False, "msg": "Esta empresa no tiene correo de destinatario configurado.\n"
                                        "Ve a ⚖ Obligaciones → Config Empresa."}
        asunto = CE.generar_asunto(cfg, buscar_por_rfc(rfc), int(mes), int(anio))
        prov = PROVIDERS.get(email_cfg.get("proveedor", "smtp"), {})
        return {"ok": True, "texto": f"¿Enviar correo?\n\nPara: {dest_raw}\nCC: {cfg.get('cc', '') or '(ninguno)'}\n"
                                     f"Asunto: {asunto}\nAdjuntos: {len(rutas)}\nProveedor: {prov.get('nombre', 'SMTP')}"}

    def compl_envio_enviar(self, rfc, mes, anio, rutas) -> dict:
        """Corre en el hilo de la llamada de pywebview (no bloquea la ventana)."""
        email_cfg = cargar_email_cfg()
        cfg = CE.obtener_config(rfc)
        empresa = buscar_por_rfc(rfc)
        mes, anio = int(mes), int(anio)
        dest_raw = cfg.get("destinatario", "").strip()
        asunto = CE.generar_asunto(cfg, empresa, mes, anio)
        cuerpo = CE.generar_cuerpo(empresa, rfc, cfg, mes, anio, rutas or None)
        dests = [d.strip() for d in dest_raw.split(",") if d.strip()]
        ccs = [c.strip() for c in cfg.get("cc", "").split(",") if c.strip()]
        try:
            enviar_correo(email_cfg, asunto, cuerpo, dests, cc=ccs, adjuntos=rutas)
        except Exception as e:
            return {"ok": False, "msg": str(e),
                    "log": f"❌ Error envío compliance: {empresa} — {e}"}
        return {"ok": True, "msg": f"✅ Correo enviado a {dest_raw}\nAdjuntos: {len(rutas)}",
                "log": f"✅ Compliance enviado: {empresa} – {CE.MESES_ES[mes]} {anio} ({len(rutas)} adj.)"}
