"""Ventanas compartidas entre módulos (equivalen a DialogEmpresas, _DialogBitacora y
App._resolver_conflicto de la 5.0)."""
from __future__ import annotations

import itertools
import threading

from bitacora import listar as bitacora_listar
from bitacora import total as bitacora_total
from empresas import (actualizar_empresa, agregar_empresa, buscar_por_rfc, eliminar_empresa,
                      listar_empresas, obtener_empresa, registrar_desde_cif, validar_rfc)


def _regimen_txt(emp: dict) -> tuple[str, bool]:
    codigos = emp.get("regimenes", [])
    nombres = emp.get("regimenes_nombres", [])
    if codigos and nombres:
        return ",  ".join(f"{n} ({c})" for n, c in zip(nombres, codigos)), True
    if codigos:
        return ", ".join(codigos), True
    return "—  sin CSF", False


class ComunApi:
    _conflictos: dict = {}
    _conf_ids = itertools.count(1)

    # -- Empresas / RFC ---------------------------------------------------------------
    def emp_listar(self) -> list[dict]:
        out = []
        for rfc, nombre in listar_empresas():
            emp = obtener_empresa(rfc) or {}
            txt, con_csf = _regimen_txt(emp)
            out.append({"rfc": rfc, "nombre": nombre, "regimen": txt, "csf": con_csf,
                        "detalle": [f"{n} ({c})" for n, c in zip(emp.get("regimenes_nombres", []),
                                                                  emp.get("regimenes", []))]
                        or emp.get("regimenes", [])})
        return out

    def emp_validar_rfc(self, rfc: str) -> bool:
        return validar_rfc((rfc or "").upper())

    def emp_existe(self, rfc: str):
        return buscar_por_rfc((rfc or "").strip().upper())

    def emp_guardar(self, rfc: str, nombre: str) -> dict:
        rfc, nombre = (rfc or "").strip().upper(), (nombre or "").strip()
        if not rfc or not nombre:
            return {"ok": False, "msg": "RFC y nombre son obligatorios."}
        if not validar_rfc(rfc):
            return {"ok": False, "msg": f"El RFC '{rfc}' no tiene el formato correcto.\n"
                                        "Persona Moral: AAA000000AA0 (12 chars)\n"
                                        "Persona Física: AAAA000000AA0 (13 chars)"}
        if buscar_por_rfc(rfc):
            actualizar_empresa(rfc, nombre)
            return {"ok": True, "msg": f"✅ Empresa '{nombre}' actualizada."}
        agregar_empresa(rfc, nombre)
        return {"ok": True, "msg": f"✅ Empresa '{nombre}' registrada con RFC {rfc}."}

    def emp_eliminar(self, rfc: str) -> dict:
        eliminar_empresa(rfc)
        return {"ok": True}

    def emp_subir_csf(self) -> dict:
        sel = self._elegir_archivos(("PDF (*.pdf)", "Todos (*.*)"))
        if not sel:
            return {"ok": False, "cancelado": True}
        try:
            ok, msg, datos = registrar_desde_cif(sel[0])
            return {"ok": bool(ok and datos), "msg": msg, "rfc": getattr(datos, "rfc", None)}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    # -- Bitácora de conversiones ---------------------------------------------------
    def bit_listar(self, rfc=None, banco=None, periodo=None) -> dict:
        banco = None if banco in (None, "", "Todos") else banco
        filas = bitacora_listar(rfc=(rfc or "").strip() or None, banco=banco,
                                periodo=(periodo or "").strip() or None)
        return {"filas": filas, "total": bitacora_total()}

    # -- Conflicto al reimportar (el motor espera la decisión) -----------------------
    def _resolver_conflicto(self, conf) -> str:
        """Lo llama `reimportar` desde un hilo de trabajo. Pregunta en la pantalla y
        ESPERA la respuesta (sin congelar la ventana). Default: 'descartar'."""
        def _txt(x):
            desc = getattr(x, "concepto", None) or getattr(x, "descripcion", "")
            return {"fecha": str(getattr(x, "fecha", "")), "desc": str(desc),
                    "deposito": getattr(x, "deposito", 0), "retiro": getattr(x, "retiro", 0),
                    "uuid": getattr(x, "uuid_cfdi", "") or "—"}
        cid = next(self._conf_ids)
        ev = threading.Event()
        self._conflictos[cid] = {"ev": ev, "v": "descartar"}
        self._js("comun.conflicto", cid, {
            "tabla": conf.tabla, "id": conf.registro_id, "v_local": conf.version_local,
            "v_guardada": conf.version_guardada, "local": _txt(conf.local),
            "guardado": _txt(conf.guardado)})
        ev.wait(timeout=1800)
        return self._conflictos.pop(cid, {}).get("v", "descartar")

    def comun_conflicto_responder(self, cid, eleccion: str):
        c = self._conflictos.get(int(cid))
        if c:
            c["v"] = "sobrescribir" if eleccion == "sobrescribir" else "descartar"
            c["ev"].set()
        return True
