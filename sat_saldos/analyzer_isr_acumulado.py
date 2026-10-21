"""Análisis acumulado de ISR: 3 controles sobre las declaraciones detalladas.

Control 1 — Pérdidas fiscales: seguimiento por año de origen, aplicación en
            cada mensual/anual, remanente.
Control 2 — Saldo a favor ISR: origen de la anual, compensaciones en mensuales,
            remanente. Regla: saldo a favor SOLO nace en la anual.
Control 3 — Pagos provisionales: impuesto a cargo por mensual, acumulado,
            validación contra lo reportado en la anual.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .config import MES_ABR
from .models import DetalleISR


@dataclass
class RenglonISR:
    ejercicio: int
    periodo: int
    es_anual: bool
    ingresos: float
    utilidad_fiscal: float
    perdidas_aplicadas: float
    impuesto_causado: float
    pagos_prov_anteriores: float
    isr_retenido: float
    compensaciones: float
    impuesto_a_cargo: float
    saldo_a_favor: float
    operacion: Optional[str]
    subtipo: str
    regimen: str
    fecha_presentacion: Optional[datetime] = None


@dataclass
class ControlPerdida:
    anio_origen: int
    monto_original: float
    aplicaciones: list = field(default_factory=list)  # [(periodo_str, monto)]
    remanente: float = 0.0


@dataclass
class ControlSaldoFavor:
    ejercicio_origen: int
    monto_original: float
    operacion_origen: Optional[str] = None
    aplicaciones: list = field(default_factory=list)  # [(periodo_str, monto)]
    remanente: float = 0.0


@dataclass
class AnalisisISRAcumulado:
    renglones: list[RenglonISR] = field(default_factory=list)
    perdidas: list[ControlPerdida] = field(default_factory=list)
    saldos_favor: list[ControlSaldoFavor] = field(default_factory=list)
    total_pagos_provisionales: float = 0.0
    pagos_prov_reportados_anual: Optional[float] = None
    ejercicio: Optional[int] = None
    cobertura: list[int] = field(default_factory=list)
    nota: str = ""


def _dt(d: DetalleISR) -> datetime:
    return d.fecha_presentacion or datetime(1900, 1, 1)


def _etq(ej: int, per: int) -> str:
    if per == 0:
        return f"Anual-{ej}"
    return f"{MES_ABR[per]}-{ej}" if 1 <= per <= 12 else f"{per}-{ej}"


def vigentes_detalle_isr(detalles: list[DetalleISR]) -> dict[tuple[int, int], DetalleISR]:
    byop: dict[str, DetalleISR] = {}
    for d in detalles:
        clave = d.operacion or d.archivo
        byop.setdefault(clave, d)
    grupos: dict[tuple[int, int], list[DetalleISR]] = {}
    for d in byop.values():
        if d.ejercicio is None:
            continue
        per = d.periodo if d.periodo is not None else (0 if d.es_anual else -1)
        if per < 0:
            continue
        grupos.setdefault((d.ejercicio, per), []).append(d)
    return {k: max(g, key=_dt) for k, g in grupos.items()}


def analizar_isr_acumulado(detalles: list[DetalleISR]) -> AnalisisISRAcumulado:
    an = AnalisisISRAcumulado()
    vig = vigentes_detalle_isr(detalles)
    if not vig:
        an.nota = "Sin declaraciones detalladas de ISR legibles."
        return an

    an.ejercicio = max(ej for (ej, _) in vig)
    orden = sorted(vig.items(), key=lambda kv: (kv[0][0], 99 if kv[0][1] == 0 else kv[0][1]))

    acum_pagos = 0.0
    for (ej, per), d in orden:
        etq = _etq(ej, per)
        r = RenglonISR(
            ejercicio=ej, periodo=per, es_anual=d.es_anual,
            ingresos=d.ingresos_acumulables or 0.0,
            utilidad_fiscal=d.utilidad_fiscal or 0.0,
            perdidas_aplicadas=d.perdidas_fiscales_aplicadas or 0.0,
            impuesto_causado=d.impuesto_causado or 0.0,
            pagos_prov_anteriores=d.pagos_provisionales_anteriores or 0.0,
            isr_retenido=d.isr_retenido or 0.0,
            compensaciones=d.compensaciones or 0.0,
            impuesto_a_cargo=(d.impuesto_a_cargo or d.isr_a_cargo_ejercicio or 0.0),
            saldo_a_favor=d.saldo_a_favor or 0.0,
            operacion=d.operacion, subtipo=d.subtipo,
            regimen=d.regimen, fecha_presentacion=d.fecha_presentacion,
        )
        an.renglones.append(r)

        # Control 1: pérdidas aplicadas en este periodo
        if d.perdidas_detalle:
            for pd in d.perdidas_detalle:
                ctrl = next((c for c in an.perdidas if c.anio_origen == pd.anio_origen), None)
                if ctrl is None:
                    ctrl = ControlPerdida(
                        anio_origen=pd.anio_origen,
                        monto_original=pd.pendientes_de_aplicar or pd.perdida_actualizada or 0.0,
                    )
                    an.perdidas.append(ctrl)
                if pd.aplicada_en_ejercicio and pd.aplicada_en_ejercicio > 0:
                    ctrl.aplicaciones.append((etq, pd.aplicada_en_ejercicio))
                ctrl.remanente = pd.remanente or 0.0

        # Control 2: saldo a favor (solo nace en anual)
        if d.es_anual and (d.saldo_a_favor or 0) > 0:
            an.saldos_favor.append(ControlSaldoFavor(
                ejercicio_origen=ej,
                monto_original=d.saldo_a_favor,
                operacion_origen=d.operacion,
                remanente=d.saldo_a_favor,
            ))

        # Compensaciones mensuales consumen el saldo más antiguo (PEPS)
        if not d.es_anual and (d.compensaciones or 0) > 0:
            pend = d.compensaciones
            for sf in an.saldos_favor:
                if pend <= 0:
                    break
                if sf.remanente <= 0:
                    continue
                toma = min(sf.remanente, pend)
                sf.aplicaciones.append((etq, toma))
                sf.remanente = round(sf.remanente - toma, 2)
                pend = round(pend - toma, 2)

        # Control 3: pagos provisionales acumulados
        if not d.es_anual:
            cargo = d.impuesto_a_cargo or d.cantidad_a_cargo or d.cantidad_a_pagar or 0.0
            acum_pagos += cargo
        else:
            an.pagos_prov_reportados_anual = d.pagos_provisionales_anteriores

    an.total_pagos_provisionales = round(acum_pagos, 2)
    an.cobertura = sorted({per for (_, per) in vig if per > 0})

    # Nota de validación cruzada
    if an.pagos_prov_reportados_anual is not None:
        diff = abs(an.total_pagos_provisionales - an.pagos_prov_reportados_anual)
        if diff > 1.0:
            an.nota = (
                f"Pagos provisionales acumulados (${an.total_pagos_provisionales:,.2f}) "
                f"difieren de lo reportado en la anual "
                f"(${an.pagos_prov_reportados_anual:,.2f}). Diferencia: ${diff:,.2f}."
            )
        else:
            an.nota = "Pagos provisionales cuadran con la anual."
    else:
        an.nota = "Sin declaración anual para validación cruzada de pagos provisionales."

    return an
