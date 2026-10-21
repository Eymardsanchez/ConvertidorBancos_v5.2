"""
activacion.py — ConvertidorBancos v5.0
=======================================
Serial key HMAC-SHA256 (offline, sin red) + hardware binding multifactor.

Híbrido de dos versiones anteriores de este mismo proyecto:
  - v2 (serial-key-hmac): flujo simple — el usuario pega un serial de 24
    caracteres, se valida localmente contra la clave HMAC embebida. Sin
    trial, sin servidor, sin API.
  - v4 (hardware-binding): fingerprint de máquina de 6 factores (en vez de
    solo la MAC address de v2) para que la licencia guardada no sea
    trivialmente copiable a otra PC.

Deliberadamente NO se portó de v4: el sistema de trial (30 días / 10
conversiones-mes) ni la activación online vía API 2FA (correo + OTP,
requiere desplegar api_licencias.py con Flask) — no se pidieron para esta
edición. Si se necesitan después, el código de referencia ya probado está
en versiones/codigo/v4-hardware-binding/activacion.py.

Fingerprint de hardware (6 factores combinados, igual a v4):
  1. Dirección MAC de red
  2. Serial del disco duro / SSD físico
  3. ID del procesador (CPU)
  4. Serial de la placa base
  5. Serial del BIOS
  6. Nombre del equipo (factor extra, no hardware pero estable)

Clave HMAC propia de esta edición (NO coincide con v2/v4 a propósito — un
serial generado para v2/v4 no activa esta edición, y viceversa; son
productos/ediciones distintos con licenciamiento separado).

Hardware binding "duro" (13 jul 2026): a diferencia del esquema original
de v2 (donde cualquier serial válido se auto-ataba a la primera PC que lo
usara), aquí el serial se genera YA atado a un equipo específico — el HMAC
se calcula sobre codigo_equipo() + seed, no solo sobre seed. El cliente
copia su código de equipo desde DialogActivacion ("Copiar código de
equipo") y lo envía a soporte; soporte lo pega en el generador privado
(versiones/licencias-privado-v5.0/) para emitir un serial que SOLO
valida en ese equipo.
"""

import hmac
import hashlib
import base64
import json
import os
import socket
import subprocess
import sys
import uuid
from datetime import date
from pathlib import Path
from typing import Optional

try:
    import winreg
except ImportError:
    winreg = None

# Días del periodo de prueba antes de exigir activación (serial atado a equipo).
TRIAL_DAYS = 30

# Clave secreta (fragmentada para dificultar extracción del bytecode).
# DEBE coincidir EXACTAMENTE con generar_serial.py.
_S1 = b"\x7a\x6a\x4f\xba\x08\xf4"
_S2 = b"\x4d\x04\x10\x3d\xae\xe4"
_S3 = b"\xfe\x95\xa2\x7e\xf8\x3a"
_SECRET: bytes = _S1 + _S2 + _S3

_SEED_LEN = 7
_MAC_LEN  = 8
_PAYLOAD  = _SEED_LEN + _MAC_LEN   # 15 bytes -> 24 chars Base32

# Suprime la ventana de consola en las llamadas WMIC (Windows).
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


# ─────────────────────────────────────────────────────────────────────────────
#  FINGERPRINT DE HARDWARE — 6 factores (idéntico a v4-hardware-binding)
# ─────────────────────────────────────────────────────────────────────────────

def _wmic(query: str) -> str:
    """Ejecuta una consulta WMIC y retorna el primer valor no vacío."""
    try:
        r = subprocess.run(
            query, capture_output=True, text=True,
            shell=True, timeout=6,
            creationflags=_NO_WINDOW,
        )
        for line in r.stdout.splitlines():
            line = line.strip()
            if not line or line.lower() in (
                "serialnumber", "processorid", "volumeserialnumber",
                "to be filled by o.e.m.", "default string",
                "none", "n/a", "0", "00000000",
            ):
                continue
            if len(line) >= 4:
                return line
    except Exception:
        pass
    return ""


def _hw_disk()  -> str: return _wmic("wmic diskdrive get SerialNumber")
def _hw_cpu()   -> str: return _wmic("wmic cpu get ProcessorId")
def _hw_board() -> str: return _wmic("wmic baseboard get SerialNumber")
def _hw_bios()  -> str: return _wmic("wmic bios get SerialNumber")
def _hw_mac()   -> str: return str(uuid.getnode())

def _hw_hostname() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return ""


def _machine_id() -> str:
    """
    Identificador único de la máquina combinando los 6 factores.
    Formato: MAC|DISK|CPU|BOARD|BIOS|HOST
    Resistente a: cambio de IP, spoofing de MAC, reinstalación de Windows.
    """
    parts = [_hw_mac(), _hw_disk(), _hw_cpu(), _hw_board(), _hw_bios(), _hw_hostname()]
    return "|".join(p.strip() for p in parts)


def codigo_equipo() -> str:
    """
    Cadena exacta que identifica esta máquina ("código de equipo"). Es lo
    que el cliente copia y envía a soporte para que se le genere un serial
    atado a SU equipo (ver botón "Copiar código de equipo" en
    DialogActivacion, y el generador privado en
    versiones/licencias-privado-v5.0/).
    Si falla la lectura de hardware (WMIC bloqueado, VM rara, etc.), cae a
    solo MAC + hostname para no dejar al usuario sin poder activar.
    """
    mid = _machine_id()
    if mid.count("|") < 2 or len(mid.replace("|", "")) < 8:
        mid = f"{_hw_mac()}|{_hw_hostname()}"
    return mid


def _fingerprint() -> bytes:
    """SHA-256-compatible: bytes del código de equipo, usados como clave de
    cifrado de la licencia Y como parte del HMAC del serial (hardware
    binding "duro" — ver validar_serial)."""
    return codigo_equipo().encode("utf-8")


# ─────────────────────────────────────────────────────────────────────────────
#  Persistencia cifrada de la licencia
# ─────────────────────────────────────────────────────────────────────────────

def _app_dir() -> Path:
    p = Path(os.environ.get("APPDATA", Path.home())) / "ConvertidorBancos"
    p.mkdir(parents=True, exist_ok=True)
    return p

def _lic_path() -> Path:
    return _app_dir() / "licencia.bin"

def _trial_path() -> Path:
    return _app_dir() / "trial.bin"

def _xor(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))

def _save(path: Path, obj: dict) -> None:
    key = hashlib.sha256(_fingerprint()).digest()
    path.write_bytes(_xor(json.dumps(obj).encode("utf-8"), key))

def _load(path: Path) -> dict:
    key = hashlib.sha256(_fingerprint()).digest()
    return json.loads(_xor(path.read_bytes(), key).decode("utf-8"))


def _trial_sig(first_run: str, last_seen: str) -> str:
    machine_id = codigo_equipo()
    data = f"{first_run}|{last_seen}|{machine_id}".encode("utf-8")
    return hmac.new(_SECRET, data, hashlib.sha256).hexdigest()


def _reg_leer() -> dict:
    """Lee el espejo del trial; falla silenciosamente fuera de Windows."""
    if winreg is None:
        return {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\ConvertidorBancos") as key:
            first_run, _ = winreg.QueryValueEx(key, "first_run")
            last_seen, _ = winreg.QueryValueEx(key, "last_seen")
        return {"first_run": str(first_run), "last_seen": str(last_seen)}
    except Exception:
        return {}


def _reg_escribir(first_run: str, last_seen: str) -> None:
    """Actualiza el espejo del trial; no impide usar la persistencia en archivo."""
    if winreg is None:
        return
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\ConvertidorBancos") as key:
            winreg.SetValueEx(key, "first_run", 0, winreg.REG_SZ, first_run)
            winreg.SetValueEx(key, "last_seen", 0, winreg.REG_SZ, last_seen)
    except Exception:
        pass


def _save_trial(d: dict) -> None:
    first_run = d["first_run"]
    last_seen = d["last_seen"]
    trial = dict(d)
    trial["sig"] = _trial_sig(first_run, last_seen)
    _save(_trial_path(), trial)
    _reg_escribir(first_run, last_seen)


def _load_trial() -> Optional[dict]:
    """Carga y valida el trial, combinándolo con su espejo en el Registro."""
    archivo = {}
    if _trial_path().exists():
        try:
            archivo = _load(_trial_path())
            first_run = archivo["first_run"]
            last_seen = archivo["last_seen"]
            sig = archivo["sig"]
            if not all(isinstance(x, str) for x in (first_run, last_seen, sig)):
                raise ValueError("campos de trial inválidos")
            if not hmac.compare_digest(sig, _trial_sig(first_run, last_seen)):
                raise ValueError("firma de trial inválida")
            date.fromisoformat(first_run)
            date.fromisoformat(last_seen)
        except Exception:
            return {"_invalido": True}

    registro = _reg_leer()
    fuentes = [d for d in (archivo, registro) if d]
    if not fuentes:
        return None
    try:
        first_run = min(date.fromisoformat(d["first_run"]) for d in fuentes)
        last_seen = max(date.fromisoformat(d["last_seen"]) for d in fuentes)
    except Exception:
        return {"_invalido": True}
    return {"first_run": first_run.isoformat(), "last_seen": last_seen.isoformat()}


# ─────────────────────────────────────────────────────────────────────────────
#  SERIAL — validación y activación
# ─────────────────────────────────────────────────────────────────────────────

def validar_serial(serial: str) -> bool:
    """
    Verifica criptográficamente el serial (offline, sin red) Y que haya
    sido generado específicamente para EL CÓDIGO DE EQUIPO de esta máquina
    (hardware binding "duro" desde la generación, no solo al activar): el
    HMAC se calcula sobre fingerprint + seed, así que un serial generado
    para otro equipo no valida aquí aunque conozca la clave secreta.
    """
    try:
        clean = serial.replace("-", "").replace(" ", "").upper().strip()
        if len(clean) != 24:
            return False
        payload = base64.b32decode(clean)
        if len(payload) != _PAYLOAD:
            return False
        seed       = payload[:_SEED_LEN]
        mac_stored = payload[_SEED_LEN:]
        mac_calc   = hmac.new(_SECRET, _fingerprint() + seed, hashlib.sha256).digest()[:_MAC_LEN]
        return hmac.compare_digest(mac_stored, mac_calc)
    except Exception:
        return False


def esta_activado() -> bool:
    """True si hay una licencia válida guardada, cifrada para ESTA máquina."""
    if not _lic_path().exists():
        return False
    try:
        return validar_serial(_load(_lic_path()).get("serial", ""))
    except Exception:
        return False


def activar(serial: str) -> bool:
    """
    Valida el serial y, si es válido, lo guarda cifrado con el fingerprint
    de hardware de esta máquina (hardware binding). Retorna True si activó.
    """
    if not validar_serial(serial):
        return False
    clean = serial.replace("-", "").replace(" ", "").upper()
    fmt   = "-".join(clean[i:i + 6] for i in range(0, 24, 6))
    _save(_lic_path(), {"serial": fmt})
    return True


def serial_guardado() -> Optional[str]:
    """Retorna el serial guardado o None si no hay activación válida."""
    if not _lic_path().exists():
        return None
    try:
        s = _load(_lic_path()).get("serial", "")
        return s if validar_serial(s) else None
    except Exception:
        return None


def desactivar() -> None:
    """Borra la licencia guardada en esta máquina (para pruebas/soporte)."""
    p = _lic_path()
    if p.exists():
        p.unlink()


# ─────────────────────────────────────────────────────────────────────────────
#  TRIAL — periodo de prueba de 30 días (portado de v4, solo la parte de tiempo)
# ─────────────────────────────────────────────────────────────────────────────
#
#  Flujo de venta: el cliente instala, configura y usa TODO durante TRIAL_DAYS
#  días. Al expirar, la app exige activación: copia su "código de equipo" desde
#  DialogActivacion, lo envía a soporte, y recibe un serial atado a ESE equipo.
#
#  El archivo trial.bin se guarda cifrado con el fingerprint de hardware en
#  %APPDATA%\ConvertidorBancos\ (sobrevive a reinstalar la app, porque el
#  instalador solo borra Program Files, no APPDATA). Guarda 'first_run' y una
#  marca de agua 'last_seen': si el cliente atrasa el reloj del sistema para
#  extender la prueba, la fecha de referencia nunca retrocede por debajo de la
#  más avanzada ya vista, así que atrasar el reloj no regala días.

def init_trial() -> None:
    """Crea el contador de prueba en el primer arranque (idempotente)."""
    d = _load_trial()
    if d is None:
        hoy = date.today().isoformat()
        _save_trial({"first_run": hoy, "last_seen": hoy})


def registrar_arranque() -> None:
    """Avanza la marca de agua 'last_seen' (anti-retroceso de reloj). Se llama
    una vez por arranque desde main()."""
    d = _load_trial()
    if not d or d.get("_invalido"):
        return
    hoy = date.today()
    last = date.fromisoformat(d.get("last_seen", d.get("first_run", hoy.isoformat())))
    if hoy > last:
        d["last_seen"] = hoy.isoformat()
    _save_trial(d)


def trial_info() -> dict:
    """
    Retorna dict con:
      days_left : días de prueba restantes (0 si ya expiró)
      expired   : True si la prueba terminó
      valid     : True si la prueba sigue vigente (days_left > 0)
    Lector puro: usa max(hoy, last_seen) como referencia para que atrasar el
    reloj no reviva la prueba.
    """
    d = _load_trial()
    if d and d.get("_invalido"):
        return {"days_left": 0, "expired": True, "valid": False}
    if d is None:
        # Sin archivo aún = como si fuera el primer día.
        return {"days_left": TRIAL_DAYS, "expired": False, "valid": True}
    first = date.fromisoformat(d.get("first_run", date.today().isoformat()))
    last  = date.fromisoformat(d.get("last_seen", d.get("first_run", date.today().isoformat())))
    ref   = max(date.today(), last)            # anti-retroceso de reloj
    days_left = max(0, TRIAL_DAYS - (ref - first).days)
    return {"days_left": days_left, "expired": days_left <= 0, "valid": days_left > 0}


def is_trial_valid() -> bool:
    """True si el software está activado O si la prueba sigue vigente."""
    return esta_activado() or trial_info()["valid"]
