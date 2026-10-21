"""Adaptador de caché de declaraciones (sat_saldos) sobre FirebirdPersistencia.

Implementa la interfaz que `sat_saldos.pipeline.cargar(cache=...)` espera:
    get(ruta, tamano, mtime) -> (tipo, objeto) | None
    put(ruta, tamano, mtime, tipo, objeto) -> None
más `listar(rfc)` / `borrar(ruta)` para el visor de declaraciones cargadas.

Mantiene `sat_saldos` desacoplado de Firebird: el core solo ve un objeto con
`get`/`put`; aquí se hace la (de)serialización (`sat_saldos.serial`) y el acceso a
la BD. Toda falla de caché se traga a propósito — la caché NUNCA debe tumbar ni
alterar el resultado de la carga; ante cualquier duda se re-lee el PDF.
"""
from __future__ import annotations

from typing import Optional

from sat_saldos import serial as _serial

# Tolerancia al comparar mtime (segundos): absorbe el ruido de redondeo del
# round-trip float→DOUBLE PRECISION→float sin dejar pasar un cambio real de archivo.
_TOL_MTIME = 1e-3


class CacheDeclaracionesFDB:
    """Caché de declaraciones parseadas respaldada por la BD Firebird del proyecto."""

    def __init__(self, persistencia):
        # `persistencia` es un FirebirdPersistencia YA inicializado (con _con abierto).
        self._p = persistencia

    # -- interfaz usada por pipeline.cargar ---------------------------------
    def get(self, ruta: str, tamano: int, mtime: float):
        """(tipo, objeto) si el PDF está cacheado y su identidad coincide; None si no."""
        try:
            row = self._p.obtener_cache_declaracion(ruta)
        except Exception:
            return None
        if not row:
            return None
        # Validación de identidad de archivo: tamaño exacto y mtime dentro de tolerancia.
        try:
            if float(row.get("tamano") or -1) != float(tamano):
                return None
            if abs(float(row.get("mtime") or -1.0) - float(mtime)) > _TOL_MTIME:
                return None
        except (TypeError, ValueError):
            return None
        tipo = row.get("tipo")
        payload = row.get("payload")
        if not tipo or payload is None:
            return None
        try:
            obj = _serial.de_json(tipo, payload)
        except Exception:
            # Payload de una versión anterior del modelo o corrupto → re-leer el PDF.
            return None
        return (tipo, obj)

    def put(self, ruta: str, tamano: int, mtime: float, tipo: str, obj) -> None:
        try:
            payload = _serial.a_json(tipo, obj)
            self._p.guardar_cache_declaracion(
                ruta, tamano, mtime,
                getattr(obj, "rfc", "") or "",
                getattr(obj, "ejercicio", None),
                getattr(obj, "periodo", None),
                getattr(obj, "operacion", None),
                getattr(obj, "subtipo", None),
                tipo, payload)
        except Exception:
            # Una falla al cachear nunca debe abortar ni alterar la carga.
            pass

    # -- usado por el visor --------------------------------------------------
    def listar(self, rfc: Optional[str] = None) -> list:
        try:
            return self._p.listar_cache_declaraciones(rfc)
        except Exception:
            return []

    def borrar(self, ruta: str) -> bool:
        try:
            return self._p.borrar_cache_declaracion(ruta)
        except Exception:
            return False
