"""Licenciamiento + usuarios (equivale a DialogActivacion, _DialogActivarEnApp,
DialogLogin, _DialogMostrarCodigo, _DialogRecuperar y _DialogCambiarPwd de la 5.0).
Misma lógica offline (activacion.py / usuarios.py), sin cambios."""
from __future__ import annotations

from activacion import (TRIAL_DAYS, activar, codigo_equipo, esta_activado,
                        is_trial_valid, trial_info)
from usuarios import (cambiar_password, crear_usuario, hay_usuarios, recuperar_password,
                      tomar_nuevo_codigo, verificar_usuario)


class AuthApi:
    _usuario: str = ""

    # -- licencia ---------------------------------------------------------------
    def auth_estado(self) -> dict:
        return {
            "requiere_activacion": not is_trial_valid(),
            "primer_usuario": not hay_usuarios(),
            "trial_days": TRIAL_DAYS,
            "usuario": self._usuario,
            "licencia": self.lic_texto(),
        }

    def lic_texto(self) -> str:
        if esta_activado():
            return "🔓 Licencia activada"
        ti = trial_info()
        if ti["valid"]:
            return f"⏳ Prueba: {ti['days_left']} días  ·  Activar"
        return "🔑 Activar licencia"

    def lic_estado_detalle(self) -> dict:
        if esta_activado():
            return {"texto": "✓ Esta máquina ya está activada.", "activado": True}
        ti = trial_info()
        if ti["valid"]:
            return {"texto": f"Prueba: quedan {ti['days_left']} de {TRIAL_DAYS} días.",
                    "activado": False}
        return {"texto": "Tu periodo de prueba terminó.", "activado": False}

    def lic_activar(self, serial: str) -> bool:
        return bool(activar((serial or "").strip()))

    def lic_codigo_equipo(self) -> str:
        return codigo_equipo()

    # -- usuarios ---------------------------------------------------------------
    def auth_login(self, user: str, pwd: str) -> dict:
        if verificar_usuario(user or "", pwd or ""):
            self._usuario = (user or "").strip().lower()
            return {"ok": True, "usuario": self._usuario}
        return {"ok": False, "msg": "Usuario o contraseña incorrectos."}

    def auth_crear(self, user: str, pwd: str, pwd2: str) -> dict:
        if pwd != pwd2:
            return {"ok": False, "msg": "Las contraseñas no coinciden."}
        ok, msg, code = crear_usuario((user or "").strip(), pwd or "")
        if not ok:
            return {"ok": False, "msg": msg}
        self._usuario = user.strip().lower()
        return {"ok": True, "usuario": self._usuario, "codigo": code}

    def auth_recuperar(self, user: str, codigo: str, nueva: str) -> dict:
        ok, msg = recuperar_password(user or "", codigo or "", nueva or "")
        if not ok:
            return {"ok": False, "msg": msg}
        return {"ok": True, "msg": msg, "nuevo_codigo": tomar_nuevo_codigo((user or "").strip().lower())}

    def auth_cambiar(self, actual: str, nueva: str, confirma: str) -> dict:
        if nueva != confirma:
            return {"ok": False, "msg": "Las contraseñas no coinciden."}
        ok, msg = cambiar_password(self._usuario, actual or "", nueva or "")
        return {"ok": ok, "msg": msg}
