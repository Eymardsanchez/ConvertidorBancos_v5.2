"""ConvertidorBancos 5.2 — interfaz HTML (pywebview / WebView2) + backend Python.

Ventana de escritorio normal, sin servidor ni puerto. El HTML (carpeta ui/) llama a
Python con `pywebview.api.<metodo>()`; Python empuja avances y resultados con
`evaluate_js`. Todo trabajo pesado corre en hilos: la ventana nunca se congela.

Motores (bancos/, sat_saldos/, persistencia, conciliacion, cfdi_*, etc.) copiados de
la 5.0 sin cambios; solo la interfaz es nueva. Cada módulo de la interfaz tiene su
API (`api_<modulo>.py`) y su script (`ui/mod_<modulo>.js`).

Uso:  python app52.py
      python app52.py --prueba-saldos <carpeta>   → prueba de punta a punta
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
sys.dont_write_bytecode = True

import webview  # noqa: E402

from activacion import init_trial, registrar_arranque  # noqa: E402
from api_auth import AuthApi  # noqa: E402
from api_base import ApiBase  # noqa: E402
from api_comun import ComunApi  # noqa: E402
from api_conciliacion import ConciliacionApi  # noqa: E402
from api_config import ConfigApi  # noqa: E402
from api_convertidor import ConvertidorApi  # noqa: E402
from api_obligaciones import ObligacionesApi  # noqa: E402
from api_saldos import SaldosApi  # noqa: E402

VERSION = "5.2"
UI = BASE / "ui" / "index.html"


class Api(ApiBase, AuthApi, ComunApi, ConvertidorApi, ConciliacionApi, ObligacionesApi, SaldosApi,
          ConfigApi):
    def __init__(self):
        ApiBase.__init__(self)
        self._conv_init()
        self._oblig_init()
        self._concil_init()
        self._saldos_init()

    def app_version(self) -> str:
        return VERSION


def _prueba_saldos(window, api: Api, carpeta: str):
    """E2E: entra al módulo Saldos (sin login; solo prueba), carga por la MISMA vía
    que el botón y lee el DOM."""
    time.sleep(1.5)
    window.evaluate_js("app.entrar('prueba'); app.ir('saldos')")
    api.saldos_fijar_rutas([carpeta])
    t0 = time.perf_counter()
    window.evaluate_js("saldos.pintarRutas(%s); document.getElementById('sBtnAnalizar').click()"
                       % json.dumps([carpeta]))
    while not window.evaluate_js("window.__listo === true"):
        time.sleep(0.2)
        if time.perf_counter() - t0 > 900:
            break
    seg = time.perf_counter() - t0
    info = window.evaluate_js(
        "({filas: document.querySelectorAll('#sTablaIva tbody tr').length,"
        " revisar: document.querySelectorAll('#sTablaIva tbody tr.revisar').length,"
        " maxGapMs: Math.round(window.__maxGap||0), resumen: document.getElementById('sResumen').innerText})")
    print(json.dumps({"segundos": round(seg, 1), **info}, ensure_ascii=False, indent=1))
    window.destroy()


def _prueba_modulo(window, api: Api, modulo: str, consulta: str):
    """Abre un módulo (sin login; solo prueba), espera a que monte y reporta el DOM
    pedido + errores JS. NO pulsa botones que guarden: solo lectura."""
    time.sleep(1.5)
    tam = os.environ.get("PRUEBA_TAM")                               # p. ej. "1024x680"
    if tam:
        window.resize(*(int(x) for x in tam.lower().split("x")))
        time.sleep(1)
    window.evaluate_js(f"app.entrar('prueba'); app.ir('{modulo}')")
    time.sleep(2.5)
    if len(sys.argv) > sys.argv.index("--prueba-modulo") + 3:      # paso previo opcional
        window.evaluate_js(sys.argv[sys.argv.index("--prueba-modulo") + 3])
        time.sleep(2.5)
    info = window.evaluate_js(f"({{datos: ({consulta}), errores: window.__errores}})")
    print(json.dumps(info, ensure_ascii=False, indent=1, default=str))
    window.destroy()


def _prueba_conv(window, api: Api, pdf: str, salida: str):
    """E2E del Convertidor SIN efectos en los datos del usuario: no escribe en la
    BD Firebird ni en la bitácora (se sustituyen), y el Excel va a `salida`."""
    import api_convertidor
    import persistencia

    class _SinBD:
        def __init__(self, *a, **k):
            raise RuntimeError("BD desactivada en prueba")
    persistencia.FirebirdPersistencia = _SinBD
    api_convertidor.bitacora_registrar = lambda **k: None
    api_convertidor.buscar_por_rfc = lambda rfc: f"EMPRESA PRUEBA {rfc}"   # sin alta real
    time.sleep(1.5)
    window.evaluate_js("window.__prueba = true; app.entrar('prueba'); app.ir('conv')")
    time.sleep(1)
    api._c_outdir = salida
    api.conv_agregar_rutas([pdf])
    time.sleep(3)                                   # deja terminar la auto-detección
    t0 = time.perf_counter()
    window.evaluate_js("document.getElementById('cBtnConv').click()")
    while not window.evaluate_js("window.__listo === true"):
        time.sleep(0.3)
        if time.perf_counter() - t0 > 600:
            break
    info = window.evaluate_js(
        "({fin: conv._fin, fila: document.querySelector('#cTabla tbody tr')?.innerText,"
        " log: document.getElementById('cLog').innerText.split('\\n').slice(-8),"
        " maxGapMs: Math.round(window.__maxGap||0), errores: window.__errores})")
    print(json.dumps({"segundos": round(time.perf_counter() - t0, 1), **info},
                     ensure_ascii=False, indent=1, default=str))
    window.destroy()


def _prueba_compl(window, api: Api, carpeta: str):
    """E2E de la carga de declaraciones de Obligaciones SIN efectos: no escribe en la
    BD (se sustituye) y se detiene ANTES de marcar/copiar (window.__prueba)."""
    import persistencia

    class _SinBD:
        def __init__(self, *a, **k):
            raise RuntimeError("BD desactivada en prueba")
    persistencia.FirebirdPersistencia = _SinBD
    time.sleep(1.5)
    window.evaluate_js("window.__prueba = true; app.entrar('prueba'); app.ir('compl')")
    time.sleep(2)
    window.evaluate_js("compl.iniciarCarga()")
    t0 = time.perf_counter()
    api.compl_cargar_rutas([carpeta])
    while not window.evaluate_js("window.__listo === true"):
        time.sleep(0.3)
        if time.perf_counter() - t0 > 900:
            break
    info = window.evaluate_js("({leido: compl._leido, maxGapMs: Math.round(window.__maxGap||0),"
                              " estado: document.getElementById('caEstado').innerText, errores: window.__errores})")
    print(json.dumps({"segundos": round(time.perf_counter() - t0, 1), **info},
                     ensure_ascii=False, indent=1, default=str))
    window.destroy()


def main():
    # Igual que la 5.0: arranca/valida la prueba y registra el arranque (anti-retroceso
    # de reloj). La pantalla de activación la decide el HTML con auth_estado().
    init_trial()
    registrar_arranque()
    api = Api()
    window = webview.create_window(
        f"ConvertidorBancos {VERSION}", str(UI), js_api=api,
        width=1360, height=860, min_size=(1024, 680))
    api._window = window
    if "--prueba-saldos" in sys.argv:
        carpeta = sys.argv[sys.argv.index("--prueba-saldos") + 1]
        webview.start(_prueba_saldos, (window, api, carpeta))
    elif "--prueba-conv" in sys.argv:
        i = sys.argv.index("--prueba-conv")
        webview.start(_prueba_conv, (window, api, sys.argv[i + 1], sys.argv[i + 2]))
    elif "--prueba-compl" in sys.argv:
        webview.start(_prueba_compl, (window, api, sys.argv[sys.argv.index("--prueba-compl") + 1]))
    elif "--prueba-modulo" in sys.argv:
        i = sys.argv.index("--prueba-modulo")
        webview.start(_prueba_modulo, (window, api, sys.argv[i + 1], sys.argv[i + 2]))
    else:
        webview.start()


if __name__ == "__main__":
    main()
