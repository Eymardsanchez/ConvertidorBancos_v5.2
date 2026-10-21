"""Módulo Convertidor PDF → Excel (equivale a `_build_convertidor_tab`, `_agregar_pdf`,
`_auto_detect`, `_run_conversion`, `_finish`, `_generar_parser_banco` y
`_reimportar_movimientos` de la 5.0). MISMA lógica de conversión, línea por línea:
OCR si el PDF es imagen → detectar banco → extraer → candado RFC → carpeta
Empresa/AAAA-MM → registrar movimientos en BD (IDs) → Excel → bitácora."""
from __future__ import annotations

import os
import threading
from pathlib import Path

from bancos.detector import PDF_LOCK, detectar_o_generico
from bitacora import registrar as bitacora_registrar
from convertidor_util import año_mes_fallback, buscar_fecha_corte, safe_folder
from empresas import buscar_por_rfc
from exportar_excel import export_to_excel

_ESTADO_TXT = {"pendiente": "⏳ Pendiente", "procesando": "⚙ Procesando…"}


class ConvertidorApi:
    def _conv_init(self):
        self._c_archivos: list[dict] = []
        self._c_outdir = ""
        self._c_running = False
        self._c_stop_detect = threading.Event()
        self._c_bancos_nuevos: list[str] = []

    # -- lista ------------------------------------------------------------------------
    def _c_vista(self):
        out = []
        for a in self._c_archivos:
            est = {"ok": f"✔ OK ({a['movimientos']})", "error": f"✘ {a['mensaje'][:30]}"}.get(
                a["estado"], _ESTADO_TXT.get(a["estado"], a["estado"]))
            out.append({"nombre": a["nombre"], "banco": a["banco"], "estado": a["estado"],
                        "estado_txt": est, "movs": a["movimientos"], "mensaje": a["mensaje"]})
        return out

    def _c_refrescar(self):
        self._js("conv.lista", self._c_vista())

    def conv_lista(self):
        return {"archivos": self._c_vista(), "outdir": self._c_outdir, "running": self._c_running}

    def conv_agregar(self):
        paths = self._elegir_archivos(("PDF (*.pdf)", "Todos (*.*)"))
        return self.conv_agregar_rutas(paths)

    def conv_agregar_rutas(self, paths):
        existentes = {a["path"] for a in self._c_archivos}
        for p in paths:
            if p not in existentes:
                self._c_archivos.append({"path": p, "nombre": Path(p).name, "banco": "Detectando…",
                                         "estado": "pendiente", "movimientos": 0, "mensaje": ""})
        self._c_stop_detect.clear()
        threading.Thread(target=self._c_auto_detect, daemon=True).start()
        return self._c_vista()

    def _c_auto_detect(self):
        for item in list(self._c_archivos):
            if self._c_stop_detect.is_set():
                break
            if item["banco"] in ("Detectando…", ""):
                try:
                    with PDF_LOCK:
                        ext = detectar_o_generico(item["path"])
                    item["banco"] = ext.NOMBRE if ext else "Desconocido"
                except Exception:
                    item["banco"] = "Error"
                self._c_refrescar()

    def conv_limpiar(self):
        if not self._c_running:
            self._c_archivos.clear()
        return self._c_vista()

    def conv_eliminar(self, indices):
        if not self._c_running:
            quitar = {int(i) for i in indices}
            self._c_archivos = [a for i, a in enumerate(self._c_archivos) if i not in quitar]
        return self._c_vista()

    def conv_elegir_salida(self):
        sel = self._elegir_carpetas()
        if sel:
            self._c_outdir = sel[0]
        return self._c_outdir

    def conv_reset_salida(self):
        self._c_outdir = ""
        return ""

    # -- conversión (hilo) -------------------------------------------------------------
    def conv_convertir(self, reconvertir: bool = False):
        if self._c_running:
            return {"ok": False, "msg": "Ya hay una conversión en curso."}
        if not self._c_archivos:
            return {"ok": False, "msg": "Agrega al menos un PDF."}
        if all(a["estado"] == "ok" for a in self._c_archivos):
            if not reconvertir:
                return {"ok": False, "confirmar": True, "msg": "Todos ya convertidos. ¿Reconvertir?"}
            for a in self._c_archivos:
                a["estado"], a["movimientos"] = "pendiente", 0
        self._c_running = True
        self._c_stop_detect.set()
        threading.Thread(target=self._c_run, daemon=True).start()
        return {"ok": True}

    def _c_log(self, msg, tag=""):
        self._js("conv.log", msg, tag)

    def _c_run(self):
        outputs = []
        self._c_bancos_nuevos = []
        total = len(self._c_archivos)
        for fi, item in enumerate(self._c_archivos):
            item["estado"] = "procesando"
            self._c_refrescar()
            ruta_pdf = item["path"]
            _ocr_tmp = None
            try:
                self._c_log(f"  Detectando: {item['nombre']}", "info")
                import ocr_pdf as _ocr
                with PDF_LOCK:
                    _sin_texto = not _ocr.pdf_tiene_texto(item["path"])
                if _sin_texto:
                    if _ocr.ocr_disponible():
                        self._c_log("  PDF escaneado (imagen) — aplicando OCR…", "info")
                        with PDF_LOCK:
                            _res = _ocr.ocr_a_pdf_buscable(item["path"], log=self._c_log)
                        if _res:
                            ruta_pdf = _ocr_tmp = _res
                            self._c_log("  ✔ OCR aplicado (PDF convertido a texto).", "ok")
                        else:
                            raise ValueError("PDF escaneado y el OCR falló. Revisa que "
                                             "el archivo no esté dañado o usa el PDF digital.")
                    else:
                        raise ValueError("PDF sin texto (escaneo). Instala Tesseract OCR "
                                         "(idioma español) o usa el PDF digital del banco.")
                with PDF_LOCK:
                    extractor = detectar_o_generico(ruta_pdf)
                item["banco"] = extractor.NOMBRE
                self._c_refrescar()
                if getattr(extractor, "ES_GENERICO", False):
                    self._c_log(f"[{item['banco']}] {item['nombre']}  —  banco NUEVO (genérico)", "warn")
                    self._c_bancos_nuevos.append(item["path"])
                else:
                    self._c_log(f"[{item['banco']}] {item['nombre']}", "bank")

                def progress(cur, tot, fi=fi, banco=item["banco"]):
                    pct = (fi / total) * 100 + (100 / total) * (cur / max(tot, 1))
                    self._js("conv.progreso", pct, f"Pág {cur}/{tot}  [{banco}] {fi + 1}/{total}")

                with PDF_LOCK:
                    movs, info = extractor.extraer(ruta_pdf, progress_callback=progress)
                if not movs:
                    raise ValueError("Sin movimientos en el PDF.")
                if not info.rfc:
                    raise ValueError("PDF sin RFC. Registra la empresa en 🏢 Empresas / RFC.")
                empresa_nombre = buscar_por_rfc(info.rfc)
                if empresa_nombre is None:
                    raise ValueError(f"RFC {info.rfc} no registrado.\n"
                                     "Ve a 🏢 Empresas / RFC en la pestaña Convertidor.")
                self._c_log(f"  🏢  {empresa_nombre}  ({info.rfc})", "info")

                with PDF_LOCK:
                    año_mes = buscar_fecha_corte(ruta_pdf)
                if not año_mes:
                    año_mes = año_mes_fallback(info.periodo)
                base_dir = self._c_outdir or str(Path(item["path"]).parent)
                out_dir = os.path.join(base_dir, safe_folder(empresa_nombre), año_mes)
                os.makedirs(out_dir, exist_ok=True)
                out_name = Path(item["path"]).stem + "_movimientos.xlsx"
                out_path = os.path.join(out_dir, out_name)
                self._c_log(f"  📁  {safe_folder(empresa_nombre)}/{año_mes}/", "info")

                try:   # IDs estables en la BD → columna A del Excel (reimportación)
                    import persistencia as _pers
                    _mb = [_pers.MovimientoBanco(
                        banco=extractor.NOMBRE, fecha=str(m.fecha or ""),
                        folio=str(m.folio or ""), descripcion=m.descripcion or "",
                        deposito=float(m.deposito or 0), retiro=float(m.retiro or 0),
                        saldo=float(m.saldo or 0)) for m in movs]
                    _p = _pers.FirebirdPersistencia(); _p.inicializar()
                    try:
                        _p.guardar_conversion(item["path"], extractor.NOMBRE,
                                              info.rfc or "", info.periodo or "", _mb)
                        for _m, _row in zip(movs, _mb):
                            _m.id_mov = _row.id
                    finally:
                        _p.cerrar()
                    self._c_log(f"  BD: {len(_mb)} movimientos registrados.", "info")
                except Exception as _e_bd:
                    self._c_log(f"  ⚠ BD no disponible ({_e_bd}); Excel sin IDs.", "info")

                export_to_excel(movs, out_path, info,
                                empresa_nombre=empresa_nombre, usuario=self._usuario)
                bitacora_registrar(
                    rfc=info.rfc, empresa=empresa_nombre, banco=extractor.NOMBRE,
                    periodo=año_mes, fecha_corte=info.periodo, movimientos=len(movs),
                    usuario=self._usuario, archivo_origen=item["path"], archivo_excel=out_path)
                outputs.append(out_path)
                item["estado"], item["movimientos"] = "ok", len(movs)
                self._c_log(f"  ✔  {len(movs)} movimientos → {out_name}", "ok")
            except Exception as exc:
                item["estado"], item["mensaje"] = "error", str(exc)
                self._c_log(f"  ✘  ERROR: {exc}", "err")
            finally:
                if _ocr_tmp:
                    try:
                        os.remove(_ocr_tmp)
                    except Exception:
                        pass
            self._c_refrescar()

        self._c_running = False
        vistos, nuevos = set(), []
        for p in self._c_bancos_nuevos:
            if p not in vistos:
                vistos.add(p)
                nuevos.append(p)
        self._js("conv.fin", {
            "ok": sum(1 for a in self._c_archivos if a["estado"] == "ok"),
            "err": sum(1 for a in self._c_archivos if a["estado"] == "error"),
            "outputs": outputs, "nuevos": nuevos})

    def conv_abrir(self, ruta):
        if ruta and Path(ruta).exists():
            os.startfile(ruta)  # noqa: S606
            return True
        return False

    # -- banco nuevo: generar parser específico ---------------------------------------
    def conv_parser_analizar(self, pdf_path: str) -> dict:
        try:
            from bancos import generador
            return {"ok": True, "info": generador.analizar(pdf_path),
                    "pdf": os.path.basename(pdf_path)}
        except Exception as e:
            return {"ok": False, "msg": f"No se pudo analizar el PDF:\n{e}"}

    def conv_parser_crear(self, pdf_path: str, info: dict) -> dict:
        from bancos import generador as _g
        try:
            original = _g.analizar(pdf_path)
            info = {**original, **{k: v for k, v in (info or {}).items() if v}}
            info["keyword"] = (info.get("keyword") or original["keyword"]).strip().upper()
            info["slug"] = _g._slug(info["nombre"])
            info["clase"] = _g._clase(info["slug"])
            # Carpeta ESCRIBIBLE (%PROGRAMDATA%\...\bancos_custom): en el .exe el paquete
            # bancos/ vive en el PYZ y no admite archivos nuevos.
            carpeta = _g.carpeta_bancos_custom()
            ruta = os.path.join(carpeta, f"{info['slug']}.py")
            n = 2
            while os.path.exists(ruta):
                ruta = os.path.join(carpeta, f"{info['slug']}_{n}.py")
                n += 1
            codigo = _g._PLANTILLA.format(
                nombre=info["nombre"].replace('"', "'"),
                pdf_base=os.path.basename(pdf_path).replace('"', "'"),
                date_src=info["date_src"], clase=info["clase"], keyword=info["keyword"])
            with open(ruta, "w", encoding="utf-8") as fh:
                fh.write(codigo)
        except Exception as e:
            return {"ok": False, "msg": str(e)}
        return {"ok": True, "ruta": ruta, "nombre": info["nombre"]}

    # -- reimportar Excel de movimientos -----------------------------------------------
    def conv_reimportar(self) -> dict:
        sel = self._elegir_archivos(("Excel (*.xlsx;*.xlsm)", "Todos (*.*)"))
        if not sel:
            return {"ok": False, "cancelado": True}
        try:
            import reimportar
            st = reimportar.reimportar_movimientos(sel[0], resolver=self._resolver_conflicto,
                                                   usuario=self._usuario)
        except Exception as e:
            return {"ok": False, "msg": str(e)}
        return {"ok": True, "st": st}
