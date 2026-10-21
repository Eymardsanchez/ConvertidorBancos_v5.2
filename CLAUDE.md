# ConvertidorBancos 5.2 — interfaz HTML (pywebview) + backend Python

Migración de la 5.0 (`D:\OneDrive\Claude\proyectos-code-backup\2026\versiones\codigo\v5.0-sin-descarga-sat`)
a interfaz HTML. **Solo cambia la interfaz**: los motores se copiaron de la 5.0 sin cambios.
Carpeta FUERA de OneDrive a propósito (OneDrive revierte ediciones).

## Correr
```
pip install pywebview==6.1          # requiere WebView2 (viene con Windows 11 / Edge)
python -B app52.py                   # o iniciar_52.bat
python -B app52.py --prueba-saldos <carpeta>   # prueba de punta a punta del módulo Saldos
python -B app52.py --prueba-modulo <id> "<expresión JS>"   # abre un módulo, devuelve la expresión + errores JS
```
`PRUEBA_TAM=1024x680` (variable de entorno) fija el tamaño de ventana en `--prueba-modulo`.
Columnas con scroll llevan `class="apilado"` (`.apilado>*{flex-shrink:0}`): sin eso, al achicar la
ventana los bloques se comprimen y se enciman (pasó en Conciliación: 190 px encimados a 1024×680).
Errores JS se acumulan en `window.__errores` (toda prueba debe terminar con `errores: []`).

## Arquitectura
- `app52.py`: arranque (init_trial/registrar_arranque como la 5.0) + `class Api(ApiBase, AuthApi, SaldosApi, …)`.
- `api_base.py`: puente. **Reglas:** métodos públicos = visibles desde JS (`pywebview.api.x()`,
  cada llamada en su propio hilo); **estado SIEMPRE con `_`** (pywebview recorre atributos públicos;
  `self.window` público causó recursión infinita y colgó la app); Python→HTML con `self._js("mod.fn", ...)`.
- `api_<modulo>.py`: una API por módulo, métodos con prefijo del módulo (`saldos_*`, `auth_*`, `lic_*`).
- `ui/index.html` (pantallas activación/login/app + menú), `ui/app.css` (mismos colores que `ui_theme.py`),
  `ui/app.js` (navegación, ventanas emergentes, licencia, usuarios), `ui/mod_<modulo>.js` (cada módulo se
  monta al entrar: `app.modulos.<id> = {montar(el)}`).
- Trabajo pesado SIEMPRE en hilo + `_js` para avance/resultado → la ventana nunca se congela.
  `window.__maxGap` mide congelamientos (verificación).
- Motores copiados de la 5.0 (sin tkinter): activacion, usuarios, empresas, bitacora, persistencia,
  saldos_cache, conciliacion, cfdi_parser, cfdi_validador, cif_parser, compliance_engine, email_sender,
  exportar_*, reimportar, repo_conciliaciones, reportes, polizas_coi, catalogo_*, grupos_conciliacion,
  evidencia_compartida, ocr_pdf, sat_descarga (SIN sat_descarga_portal), db_config, diagnostico_conciliacion,
  construir_plantilla, bancos/, sat_saldos/. Si se corrige un motor en la 5.0, copiarlo aquí.

## Fases (cada una verificada contra la 5.0 con datos reales)
| Fase | Contenido | Estado |
|---|---|---|
| 1 | Base: motores, ventana+menú, activación, login/recuperar/cambiar contraseña, Saldos a favor, Configuración (correo, usuarios, BD, palabras clave, emisores) | ✅ 20-oct-2026 (`api_auth`, `api_saldos`, `api_config` + `config_email.py` con el mismo `email_cfg.bin` de la 5.0) |
| 2 | Convertidor PDF→Excel (+ bancos aprendidos, reimportar Excel, Empresas/RFC, Bitácora) | ✅ 20-oct-2026 (`api_convertidor`, `api_comun`, `convertidor_util`; conflicto de reimportación: el hilo del motor espera la respuesta de la pantalla con `threading.Event`). Santander 8.AGOSTO: 467 movs = motor 5.0 |
| 3 | Obligaciones Fiscales (Panel, Obligaciones, Contribuciones/Saldos, Archivos, Config Empresa, reportes, envío de correo, años de trabajo) | ✅ 20-oct-2026 (`api_obligaciones`). Carga de declaraciones EN HILO + caché Firebird (en la 5.0 congelaba la ventana y no usaba caché). Jordan 82 PDF: ventana responde (peor tirón <1 s). La pestaña Contribuciones/Saldos remite al módulo Saldos (los PDF cargados se le agregan solos) + reporte de BD |
| 4 | Conciliación CFDI (descarga SAT WS, fases, Administrador de Conciliaciones, reimprimir/subir Excel) | pendiente |
| 5 | Pólizas COI + Grupos RFC | pendiente |
| 6 | Empaquetado PyInstaller + Inno (incluir ui/ y WebView2) — compilar SOLO con OK del usuario | pendiente |

## Diferencias deliberadas vs 5.0
- `convertidor_util.año_mes_fallback`: alternativa AGREGADA para "DEL 01-AGO-2026 AL 31-AGO-2026"
  (Santander, con guiones). En la 5.0 cae a la fecha de HOY → Excel en carpeta del mes equivocado
  (bug de la 5.0, pendiente de corregir allá con OK del usuario).
- Saldos: guardado en BD en hilo aparte (la 5.0 lo hacía en el hilo de la ventana).

## Verificado (20-oct-2026)
- Saldos (Jordan, 82 PDF sin caché): 77 periodos, 1 revisar, remanente $15,024 = 5.0; 115 s; ventana
  sin congelarse (máx 15 ms). BUCJ con caché: 0.5 s.
- Medición 5.0: la lentitud percibida es **Obligaciones Fiscales** (`_cargar_y_procesar`, lee los PDF en el
  hilo principal → "No responde"); Saldos a favor 5.0 ya leía en hilo (29.7 s ≈ motor).


---

## Sincronía de motores entre 5.0 / 5.1 / 5.2 / sat-saldos-favor (20 oct 2026)

**Regla:** `sat_saldos/`, `bancos/` y `exportar_excel.py` son MOTORES COMPARTIDOS —
todo fix se aplica en TODAS las copias el mismo día. Verificar con:

```bash
python D:\OneDrive\Claude\proyectos-code-backup\2026\verificar_sync.py
```

Debe decir "Todo sincronizado." (ignora CRLF/LF). Diferencias intencionales:
`bancos/detector.py` y `bancos/generador.py` del 5.1 (no tiene
`carpeta_bancos_custom`; su cargador dinámico solo lee `bancos/`).

**Sync aplicado hoy** (respaldo previo en `D:\respaldo_sync_20261020\`):
- Fix BBVA de la otra sesión (`bancos/base.py`, `bancos/bbva.py`,
  `exportar_excel.py`: clasificación por columna, FECHA LIQ, SALDO LIQUIDACIÓN,
  pie pegado a descripciones) → copiado 5.0 → 5.2.
- **Detector por RAZÓN SOCIAL** (`bancos/detector.py`) → 5.2 → 5.0 y 5.1.
  Estrategia 1: denominación legal + "S.A." / "Sociedad Nacional de Crédito"
  (`_RAZONES_SOCIALES`, ~70 instituciones; sin parser → genérico), primeras 4
  + últimas 2 páginas, variante de texto pegado (`SAINSTITU`). Estrategia 2: ancla
  IBM. Estrategia 3: `detectar()` por keywords. **Ya NO se detecta por nombre
  comercial** (causaba Banorte→BBVA por SPEIs a BBVA).
- `sat_saldos/` ya estaba idéntico en las 4 copias (incluye el fix de PF
  actividad empresarial pre-2023, 20-oct 11:36–11:53).

**Verificado:** 80 PDF reales → mismas detecciones en 5.0, 5.1 y 5.2
(Banorte 18 · Santander 47 · genérico 15); los 3 importan `bancos`, `bbva`,
`exportar_excel` sin error.
