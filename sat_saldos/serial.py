"""(De)serialización JSON de los objetos parseados de una declaración.

Para la caché de declaraciones: guarda/reconstruye `DetalleIVA`, `Declaracion` y
`AcusePago` (con sus dataclasses anidados y `datetime`) sin perder información.

`a_json` produce ASCII puro (`ensure_ascii=True`) a propósito: el payload se
guarda en un BLOB de Firebird y el ASCII evita cualquier problema de charset de
la conexión. `de_json` es tolerante — si el payload es de una versión anterior
del modelo y ya no reconstruye, el llamador trata eso como fallo de caché
(re-lee el PDF), nunca como dato válido a medias.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime

from .models import (AcusePago, Concepto, ConceptoPago, Declaracion, DetalleIVA,
                     OrigenCompensacion)

_DT = "__dt__"   # marca de datetime en el JSON
# Versión del payload. Subirla invalida TODA la caché (se re-leen los PDF), p. ej.
# cuando cambia cómo se leen las cifras. v2 = lectura vía MD con perfiles por régimen.
_VERSION = 2
_V = "__v__"


def _enc(o):
    if isinstance(o, datetime):
        return {_DT: o.isoformat()}
    raise TypeError(f"no serializable: {type(o)!r}")


def a_json(tipo: str, obj) -> str:
    """Serializa un objeto parseado (detalle|acuse|pago) a JSON ASCII."""
    return json.dumps({**asdict(obj), _V: _VERSION}, default=_enc, ensure_ascii=True)


def _dt(v):
    return datetime.fromisoformat(v[_DT]) if isinstance(v, dict) and _DT in v else v


def _origen(d):
    return OrigenCompensacion(**d) if d else None


def _concepto(d):
    d = dict(d)
    d["origen"] = _origen(d.get("origen"))
    return Concepto(**d)


def _declaracion(d):
    d = dict(d)
    d["fecha_presentacion"] = _dt(d.get("fecha_presentacion"))
    d["conceptos"] = [_concepto(c) for c in (d.get("conceptos") or [])]
    return Declaracion(**d)


def _acuse(d):
    d = dict(d)
    d["fecha_presentacion"] = _dt(d.get("fecha_presentacion"))
    d["conceptos"] = [ConceptoPago(**c) for c in (d.get("conceptos") or [])]
    return AcusePago(**d)


def _detalle(d):
    d = dict(d)
    d["fecha_presentacion"] = _dt(d.get("fecha_presentacion"))
    return DetalleIVA(**d)


_DESER = {"detalle": _detalle, "acuse": _declaracion, "pago": _acuse}


def de_json(tipo: str, payload: str):
    """Reconstruye el objeto parseado desde su JSON. Lanza si el tipo/estructura
    no cuadra (el llamador lo toma como fallo de caché)."""
    d = json.loads(payload)
    if d.pop(_V, None) != _VERSION:
        raise ValueError("payload de otra versión de lectura")
    return _DESER[tipo](d)
