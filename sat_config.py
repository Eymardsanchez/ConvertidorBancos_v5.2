"""Carpeta base de descargas SAT — mismo archivo que la 5.0
(`%APPDATA%\\ConvertidorBancos\\sat_config.json`) y el mismo filtro local por UUID
(`_filtrar_por_uuid_local`), extraídos tal cual de ConvertidorSantander.py 5.0."""
from __future__ import annotations

import json
import os
from pathlib import Path

SAT_CARPETA_DEFAULT = "C:/ConciliaRFC/SAT"


def _app_dir() -> Path:
    p = Path(os.environ.get("APPDATA", Path.home())) / "ConvertidorBancos"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _sat_config_path() -> Path:
    return _app_dir() / "sat_config.json"


def sat_carpeta_base() -> Path:
    try:
        cfg = json.loads(_sat_config_path().read_text(encoding="utf-8"))
        ruta = cfg.get("carpeta_base", "").strip()
        if ruta:
            return Path(ruta)
    except Exception:
        pass
    return Path(SAT_CARPETA_DEFAULT)


def guardar_sat_carpeta_base(ruta: str) -> None:
    _sat_config_path().write_text(json.dumps({"carpeta_base": ruta}, ensure_ascii=False, indent=2),
                                  encoding="utf-8")


def filtrar_por_uuid_local(carpeta: Path, uuids_extra: list, log) -> Path:
    """Mueve a `carpeta/filtrado/` solo los XML cuyo UUID esté en `uuids_extra` (no
    borra nada del lote). Gratis: no consume cuota del SAT."""
    from cfdi_parser import parsear_cfdi
    wanted = {u.strip().upper() for u in uuids_extra if u.strip()}
    destino = carpeta / "filtrado"
    destino.mkdir(parents=True, exist_ok=True)
    encontrados = set()
    for xml_path in carpeta.rglob("*.xml"):
        if destino in xml_path.parents:
            continue
        try:
            cfdi = parsear_cfdi(xml_path)
        except Exception:
            continue
        if cfdi and cfdi.uuid.upper() in wanted:
            xml_path.rename(destino / xml_path.name)
            encontrados.add(cfdi.uuid.upper())
    faltantes = wanted - encontrados
    if faltantes:
        log(f"⚠ {len(faltantes)} UUID(s) no encontrados en el lote descargado: "
            + ", ".join(sorted(faltantes)))
    log(f"Filtro UUID: {len(encontrados)}/{len(wanted)} encontrados -> {destino}")
    return destino
