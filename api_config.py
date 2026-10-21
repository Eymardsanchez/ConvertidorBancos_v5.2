"""Módulo Configuración (equivale a `_build_config_tab` y sus 4 pestañas en la 5.0):
correo multi-proveedor, usuarios, base de datos Firebird, palabras clave y emisores
bancarios. Misma lógica y mismos archivos que la 5.0."""
from __future__ import annotations

import db_config as _dc
from config_email import cargar_email_cfg, guardar_email_cfg
from email_sender import PROVIDERS, config_proveedor, detectar_proveedor, probar_conexion
from usuarios import crear_usuario, eliminar_usuario, listar_usuarios


class ConfigApi:
    # -- correo -------------------------------------------------------------------
    def cfg_email_cargar(self) -> dict:
        cfg = cargar_email_cfg()
        return {"cfg": cfg, "proveedores": {k: {"nota": v.get("nota", "")} for k, v in PROVIDERS.items()}}

    def cfg_email_proveedor(self, proveedor: str) -> dict:
        return {"nota": PROVIDERS.get(proveedor, {}).get("nota", ""), **config_proveedor(proveedor)}

    def cfg_email_detectar(self, email: str) -> str:
        return detectar_proveedor(email or "")

    def cfg_email_guardar(self, cfg: dict) -> dict:
        actual = cargar_email_cfg()
        actual.update({k: cfg.get(k, actual.get(k)) for k in
                       ("proveedor", "remitente", "password", "host_smtp", "puerto", "ssl")})
        try:
            actual["puerto"] = int(actual.get("puerto") or 587)
        except ValueError:
            pass
        actual["ssl"] = bool(actual.get("ssl"))
        guardar_email_cfg(actual)
        return {"ok": True, "msg": "✅ Configuración de email guardada."}

    def cfg_email_probar(self, cfg: dict) -> dict:       # corre en hilo de pywebview
        try:
            puerto = int(cfg.get("puerto") or 587)
        except ValueError:
            puerto = 587
        ok, msg = probar_conexion({"remitente": cfg.get("remitente", ""),
                                   "password": cfg.get("password", ""),
                                   "host_smtp": cfg.get("host_smtp", ""),
                                   "puerto": puerto, "ssl": bool(cfg.get("ssl"))})
        return {"ok": ok, "msg": msg}

    # -- usuarios -----------------------------------------------------------------
    def cfg_usuarios(self) -> list[str]:
        return listar_usuarios()

    def cfg_usuario_crear(self, user: str, pwd: str, pwd2: str) -> dict:
        if pwd != pwd2:
            return {"ok": False, "msg": "Las contraseñas no coinciden."}
        ok, msg, code = crear_usuario((user or "").strip(), pwd or "", creado_por=self._usuario)
        return {"ok": ok, "msg": msg, "codigo": code, "usuarios": listar_usuarios()}

    def cfg_usuario_eliminar(self, user: str) -> dict:
        if (user or "").strip().lower() == self._usuario:
            return {"ok": False, "msg": "No puedes eliminar tu propio usuario."}
        ok, msg = eliminar_usuario(user)
        return {"ok": ok, "msg": msg, "usuarios": listar_usuarios()}

    # -- base de datos ------------------------------------------------------------
    def cfg_db_cargar(self) -> dict:
        try:
            return _dc.cargar()
        except Exception:
            return {"motor": "firebird", "host": "localhost", "port": 3050, "database": "",
                    "user": "SYSDBA", "password": "", "charset": "UTF8", "fbclient": ""}

    def cfg_db_probar(self, cfg: dict) -> dict:          # corre en hilo de pywebview
        ok, msg = _dc.probar_conexion({k: str(v).strip() for k, v in cfg.items()})
        return {"ok": ok, "msg": msg}

    def cfg_db_guardar(self, cfg: dict) -> dict:
        try:
            _dc.guardar({k: str(v).strip() for k, v in cfg.items()})
            return {"ok": True, "msg": f"Se guardó en:\n{_dc.RUTA_CONFIG}"}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def cfg_db_buscar_fdb(self):
        return self._guardar_como("CONCILIACION.FDB", ("Firebird (*.fdb)", "Todos (*.*)"))

    def cfg_db_buscar_fbclient(self):
        r = self._elegir_archivos(("DLL (*.dll)", "Todos (*.*)"))
        return r[0] if r else None

    # -- palabras clave y emisores bancarios -----------------------------------
    def cfg_kw_cargar(self) -> dict:
        try:
            from conciliacion import (CATEGORIAS_KW, cargar_emisores_banco_usuario,
                                      cargar_kw_usuario_raw)
        except ImportError:
            return {"categorias": [], "emisores": []}
        return {"categorias": [{"id": c, "desc": d, "kws": cargar_kw_usuario_raw(c)}
                               for c, d in CATEGORIAS_KW.items()],
                "emisores": cargar_emisores_banco_usuario()}

    def cfg_kw_guardar(self, por_categoria: dict) -> dict:
        from conciliacion import guardar_kw_usuario
        total = 0
        for cat, texto in (por_categoria or {}).items():
            kws = [ln.strip() for ln in str(texto).splitlines() if ln.strip()]
            guardar_kw_usuario(cat, kws)
            total += len(kws)
        return {"ok": True, "msg": f"✔ {total} palabra(s) guardada(s)"}

    def cfg_emisores_guardar(self, emisores: list) -> dict:
        from conciliacion import guardar_emisores_banco_usuario
        lista = [{"nombre": (e.get("nombre") or "").strip(), "rfc": (e.get("rfc") or "").strip().upper()}
                 for e in (emisores or []) if (e.get("nombre") or e.get("rfc"))]
        guardar_emisores_banco_usuario(lista)
        return {"ok": True, "msg": f"✔ {len(lista)} emisor(es) guardado(s)"}
