"""Base del puente HTML ↔ Python (pywebview).

Reglas del puente:
- Todo método PÚBLICO de la API queda visible para el HTML como
  `pywebview.api.<metodo>()`; pywebview corre cada llamada en su propio hilo.
- Todo atributo de estado va con `_` al inicio: pywebview recorre los atributos
  públicos para exponerlos, y la ventana nativa (`_window`) provoca recursión
  infinita si queda pública.
- Python → HTML: `self._js("modulo.funcion", args...)`, seguro desde cualquier hilo.
"""
from __future__ import annotations

import json

import webview


class ApiBase:
    def __init__(self):
        self._window = None

    def _js(self, fn: str, *args):
        if self._window is not None:
            self._window.evaluate_js(f"{fn}(...{json.dumps(args, default=str)})")

    # -- diálogos nativos del sistema ------------------------------------------
    def _elegir_carpetas(self) -> list[str]:
        return list(self._window.create_file_dialog(webview.FileDialog.FOLDER,
                                                    allow_multiple=True) or [])

    def _elegir_archivos(self, tipos: tuple[str, ...]) -> list[str]:
        return list(self._window.create_file_dialog(webview.FileDialog.OPEN,
                                                    allow_multiple=True, file_types=tipos) or [])

    def _guardar_como(self, nombre: str, tipos: tuple[str, ...]):
        r = self._window.create_file_dialog(webview.FileDialog.SAVE,
                                            save_filename=nombre, file_types=tipos)
        if not r:
            return None
        return r if isinstance(r, str) else r[0]
