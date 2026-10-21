"""Configuración de correo saliente — MISMO archivo y cifrado que la 5.0
(`%APPDATA%\\ConvertidorBancos\\email_cfg.bin`, XOR con SHA-256 del MAC), así la 5.0 y
la 5.2 comparten la configuración. Extraído tal cual de ConvertidorSantander.py 5.0."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path


def _app_dir() -> Path:
    p = Path(os.environ.get("APPDATA", Path.home())) / "ConvertidorBancos"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _xor(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def _key() -> bytes:
    return hashlib.sha256(str(uuid.getnode()).encode()).digest()


def cargar_email_cfg() -> dict:
    p = _app_dir() / "email_cfg.bin"
    try:
        if p.exists():
            return json.loads(_xor(p.read_bytes(), _key()).decode("utf-8"))
    except Exception:
        pass
    return {"proveedor": "gmail", "remitente": "", "password": "",
            "host_smtp": "smtp.gmail.com", "puerto": 587, "ssl": False}


def guardar_email_cfg(cfg: dict) -> None:
    p = _app_dir() / "email_cfg.bin"
    p.write_bytes(_xor(json.dumps(cfg).encode("utf-8"), _key()))
