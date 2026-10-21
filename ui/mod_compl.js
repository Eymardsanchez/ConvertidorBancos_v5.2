// Módulo Obligaciones Fiscales (5.2). Backend: api_obligaciones.py
const compl = {
  async montar(el){
    compl.meta = await pywebview.api.compl_meta();
    const selPeriodo = (p) => `Mes: <select id="${p}Mes">${compl.meta.meses.slice(1).map((m, i) =>
        `<option value="${i + 1}" ${i + 1 === compl.meta.mes_actual ? "selected" : ""}>${m}</option>`).join("")}</select>
      Año: <select id="${p}Anio" class="anios"></select>`;
    const selRfc = (id) => `<select id="${id}" class="rfcs" style="min-width:170px"></select>`;
    el.innerHTML = `
    <section class="card" style="height:100%">
      <div class="fila"><h2 style="margin:0 12px 0 0;font-size:15px">⚖ Obligaciones Fiscales</h2>
        <span class="estado">Panel de cumplimiento, obligaciones por empresa, archivos y configuración</span></div>
      <div class="tabs">
        <button class="tab activa" data-t="panel" onclick="compl.tab(this)">📊 Panel General</button>
        <button class="tab" data-t="obl" onclick="compl.tab(this)">📋 Obligaciones</button>
        <button class="tab" data-t="sal" onclick="compl.tab(this)">💰 Contribuciones, Pagos y Saldos a Favor</button>
        <button class="tab" data-t="arch" onclick="compl.tab(this)">📁 Archivos</button>
        <button class="tab" data-t="cc" onclick="compl.tab(this)">⚙ Config Empresa</button>
      </div>
      <div style="flex:1;min-height:0;display:flex;flex-direction:column">
        <div id="co-panel" style="display:flex;flex-direction:column;gap:8px;flex:1;min-height:0">
          <div class="fila">${selPeriodo("cp")}
            <button class="primario" onclick="compl.panel()">🔄 Actualizar</button>
            <button onclick="compl.envioMasivo()">✉✉ Envío masivo</button>
            <button onclick="compl.reporte('panel')">📊 Generar reporte</button>
            <span class="estado">Doble clic en una empresa → preparar envío</span></div>
          <div class="tabla"><table><thead><tr><th>Empresa</th><th>RFC</th><th>Destinatario</th><th>Oblig./mes</th>
            <th>Carpeta</th><th>Archivos</th><th>Estado</th></tr></thead><tbody id="cpBody"></tbody></table></div>
        </div>
        <div id="co-obl" class="oculto" style="display:flex;flex-direction:column;gap:8px;flex:1;min-height:0">
          <div class="fila">RFC Empresa: ${selRfc("coRfc")} ${selPeriodo("co")}<span id="coNombre" class="estado"></span></div>
          <div class="fila"><span class="estado">Para CARGAR declaraciones usa la pestaña «Archivos». Clic en una fila = activar/desactivar.</span>
            <button onclick="compl.todas(true)">✓ Todas</button><button onclick="compl.todas(false)">✗ Ninguna</button>
            <button class="primario" onclick="compl.guardarObligs()">💾 Guardar selección</button>
            <button onclick="compl.reporte('obligaciones')">📊 Generar reporte</button></div>
          <div class="tabla"><table><thead><tr><th>✔</th><th>Obligación</th><th>Periodicidad</th><th>Meses en que aplica</th>
            <th>Presentada (periodo)</th></tr></thead><tbody id="coBody"></tbody></table></div>
        </div>
        <div id="co-sal" class="oculto" style="display:flex;flex-direction:column;gap:10px;padding-top:10px">
          <div class="estado">Los PDF cargados en «Archivos» se agregan solos al módulo <b>Saldos a favor ISR/IVA</b>; ahí se analizan (ANALIZAR) y se genera el Excel.</div>
          <div><button class="primario" onclick="app.ir('saldos')">💰 Ir a Saldos a favor ISR/IVA</button></div>
          <div class="fila">Reporte de lo guardado en la BD — RFC: ${selRfc("saRfc")} ${selPeriodo("sa")}
            <button onclick="compl.reporte('saldos')">📊 Generar reporte</button></div>
        </div>
        <div id="co-arch" class="oculto" style="display:flex;flex-direction:column;gap:8px;flex:1;min-height:0">
          <div class="fila"><button class="primario" onclick="compl.cargar('archivos')">📤 Cargar declaración(es)</button>
            <button onclick="compl.cargar('carpeta')">📁 Cargar carpeta</button>
            <span class="estado">Lee los PDF, marca Obligaciones y alimenta Saldos a favor automáticamente.</span></div>
          <div class="fila"><div class="barra-prog" style="flex:1"><div id="caBarra"></div></div><span id="caEstado" class="estado"></span></div>
          <div class="fila">RFC: ${selRfc("caRfc")} ${selPeriodo("ca")}
            <button class="primario" onclick="compl.archivos()">🔍 Ver</button>
            <button onclick="compl.abrirCarpeta()">📂 Abrir carpeta</button>
            <button onclick="compl.reporte('archivos')">📊 Generar reporte</button>
            <span id="caRuta" class="estado"></span></div>
          <div class="tabla"><table><thead><tr><th>Archivo</th><th>Tamaño</th><th>Fecha modificación</th></tr></thead>
            <tbody id="caBody"></tbody></table></div>
        </div>
        <div id="co-cc" class="oculto" style="overflow:auto;padding-top:8px">
          <div class="fila">RFC: ${selRfc("ccRfc")}
            <button onclick="compl.ccSubirCsf()">📄 Subir CSF / CIF</button><span id="ccNombre" class="estado"></span></div>
          <div id="ccReg" class="estado" style="margin:6px 0"></div>
          <div style="display:grid;grid-template-columns:200px 1fr;gap:8px 12px;max-width:860px;align-items:center">
            <span>Correo destinatario (para:)</span><input id="cc_destinatario">
            <span>CC (separados por coma):</span><input id="cc_cc">
            <span>Plantilla asunto:</span><input id="cc_asunto_template">
            <span>Carpeta raíz de archivos:</span><div class="fila"><input id="cc_carpeta_raiz" style="flex:1"><button onclick="compl.ccCarpeta()">📂 Buscar…</button></div>
            <span>Notas adicionales:</span><textarea id="cc_notas_adicionales" rows="2" style="font:inherit;padding:6px;border:1px solid var(--border);border-radius:8px"></textarea>
            <span></span><span class="estado">Variables asunto: {empresa}  {mes}  {anio}  {dia}</span>
          </div>
          <div class="fila" style="margin-top:10px"><button onclick="compl.anios()">📅 Años de trabajo</button>
            <button class="primario" onclick="compl.ccGuardar()">💾 Guardar configuración</button>
            <button onclick="compl.envio($('ccRfc').value, $('cpMes').value, $('cpAnio').value)">📨 Preparar envío</button>
            <span id="ccMsg" class="estado"></span></div>
          <div class="estado" style="margin-top:12px">Historial de envíos:</div>
          <pre id="ccLog" style="margin:3px 0 0;height:90px;overflow:auto;background:#1A1A19;color:#C3C2B7;border-radius:8px;padding:8px;font:12px Consolas,monospace"></pre>
        </div>
      </div>
    </section>`;
    compl.pintarCombos();
    ["coRfc", "coMes", "coAnio"].forEach(i => $(i).onchange = compl.obligs);
    $("ccRfc").onchange = compl.ccCargar;
    compl.panel(); compl.obligs(); compl.archivos(); compl.ccCargar();
  },
  pintarCombos(){
    document.querySelectorAll("#m-compl select.anios").forEach(s => { const v = s.value;
      s.innerHTML = compl.meta.anios.map(a => `<option>${a}</option>`).join("");
      s.value = compl.meta.anios.includes(+v) ? v : compl.meta.anio_default; });
    document.querySelectorAll("#m-compl select.rfcs").forEach(s => { const v = s.value;
      s.innerHTML = compl.meta.empresas.map(e => `<option value="${esc(e.rfc)}">${esc(e.rfc)}</option>`).join("");
      if (v && compl.meta.empresas.some(e => e.rfc === v)) s.value = v; });
  },
  async refrescarMeta(){ compl.meta = await pywebview.api.compl_meta(); compl.pintarCombos(); },
  tab(b){
    document.querySelectorAll("#m-compl .tab").forEach(x => x.classList.toggle("activa", x === b));
    ["panel", "obl", "sal", "arch", "cc"].forEach(t => $("co-" + t).classList.toggle("oculto", b.dataset.t !== t));
    compl.refrescarMeta();          // como la 5.0: al cambiar de pestaña se refrescan los RFC
  },

  // ── Panel General ─────────────────────────────────────────────────────────
  async panel(){
    const filas = await pywebview.api.compl_panel($("cpMes").value, $("cpAnio").value);
    const col = {ok: "var(--success)", warn: "var(--warn)", err: "var(--danger)"};
    $("cpBody").innerHTML = filas.map(f => `<tr style="color:${col[f.tag]};cursor:pointer" ondblclick="compl.envio('${esc(f.rfc)}', $('cpMes').value, $('cpAnio').value)">
      <td>${esc(f.nombre)}</td><td>${esc(f.rfc)}</td><td>${esc(f.dest)}</td><td>${f.obs}</td><td>${f.carpeta}</td><td>${f.archivos}</td><td>${esc(f.estado)}</td></tr>`).join("");
  },
  async envioMasivo(){
    const lista = await pywebview.api.compl_envio_masivo_lista();
    if (!lista.length){ alert("Ninguna empresa tiene destinatario configurado en Compliance."); return; }
    const mes = $("cpMes").value, anio = $("cpAnio").value;
    if (!confirm(`¿Abrir ventana de envío para ${lista.length} empresa(s) de ${compl.meta.meses[mes]} ${anio}?`)) return;
    compl._cola = lista.map(e => e.rfc);
    compl._colaPeriodo = [mes, anio];
    compl.envioSiguiente();
  },
  envioSiguiente(){
    const rfc = (compl._cola || []).shift();
    if (rfc) compl.envio(rfc, ...compl._colaPeriodo);
  },

  // ── Obligaciones ──────────────────────────────────────────────────────────
  async obligs(){
    const r = await pywebview.api.compl_obligs($("coRfc").value, $("coMes").value, $("coAnio").value);
    compl._obl = r.filas;
    $("coNombre").textContent = r.nombre ? "  " + r.nombre : ($("coRfc").value ? "  RFC no registrado" : "  (selecciona empresa)");
    $("coNombre").style.color = r.nombre ? "" : "var(--danger)";
    compl.pintarObligs();
  },
  pintarObligs(){
    $("coBody").innerHTML = compl._obl.map((o, i) => `<tr style="cursor:pointer;${o.presentada ? "background:#E8F5E9" : ""}" onclick="compl.toggle(${i})">
      <td style="text-align:center">${o.activa ? "✔" : ""}</td><td>${esc(o.nombre)}</td><td>${esc(o.periodicidad)}</td>
      <td>${esc(o.meses)}</td><td>${esc(o.presentada)}</td></tr>`).join("");
  },
  toggle(i){ compl._obl[i].activa = !compl._obl[i].activa; compl.pintarObligs(); },
  todas(v){ compl._obl.forEach(o => o.activa = v); compl.pintarObligs(); },
  async guardarObligs(){
    const r = await pywebview.api.compl_obligs_guardar($("coRfc").value, compl._obl.filter(o => o.activa).map(o => o.id));
    alert(r.msg); if (r.ok) compl.panel();
  },

  // ── Archivos + carga de declaraciones (en segundo plano) ────────────────────
  async archivos(){
    const r = await pywebview.api.compl_archivos($("caRfc").value, $("caMes").value, $("caAnio").value);
    $("caRuta").style.color = r.ruta ? "" : "var(--danger)";
    $("caRuta").textContent = r.ruta || `⚠ No existe: ${r.esperada}`;
    const ico = {".pdf": "📄", ".xml": "📋", ".xlsx": "📊", ".xls": "📊", ".zip": "🗜", ".rar": "🗜", ".sua": "💾", ".txt": "📝"};
    $("caBody").innerHTML = r.archivos.map(a => `<tr><td>${ico[a.ext] || "📎"}  ${esc(a.nombre)}</td><td>${esc(a.tam)}</td><td>${esc(a.mtime)}</td></tr>`).join("");
  },
  async abrirCarpeta(){ const r = await pywebview.api.compl_abrir_carpeta($("caRfc").value, $("caMes").value, $("caAnio").value); if (!r.ok) alert(r.msg); },
  async cargar(tipo){
    const r = tipo === "carpeta" ? await pywebview.api.compl_cargar_carpeta() : await pywebview.api.compl_cargar_archivos();
    if (r.cancelado) return;
    if (!r.ok){ alert(r.msg); return; }
    compl.iniciarCarga();
  },
  iniciarCarga(){
    window.__listo = false; window.__maxGap = 0; window.__midiendo = true;
    $("caBarra").style.width = "0"; $("caEstado").textContent = "Leyendo PDFs…";
  },
  progreso(i, n, nom){ $("caBarra").style.width = (100 * i / Math.max(n, 1)) + "%"; $("caEstado").textContent = `Leyendo ${nom} (${i}/${n})`; },
  leido(r){
    window.__midiendo = false;
    $("caEstado").textContent = `${r.pdfs} PDF leídos en ${r.segundos} s`;
    compl._leido = r;
    if (!r.rfcs.length){ window.__listo = true;
      alert("No se pudo identificar el RFC en los archivos seleccionados (¿PDF escaneados sin texto o no son acuses/declaraciones del SAT?)."); return; }
    if (window.__prueba){ window.__listo = true; return; }
    modal.abrir(`<h3>Verifica a qué empresa pertenecen los archivos</h3><div class="estado">Solo se cargarán los RFC que dejes marcados.</div>
      ${r.rfcs.map(x => `<label style="display:flex;gap:8px;align-items:center"><input type="checkbox" class="selRfc" value="${esc(x.rfc)}" ${x.nombre ? "checked" : ""}>
        <span style="font-family:Consolas,monospace">${esc(x.rfc)}   ·   ${x.docs} doc(s)</span>
        ${x.nombre ? `<span style="color:var(--accent)">${esc(x.nombre)}</span>` : `<span style="color:var(--warn)">⚠ RFC no registrado (regístralo en Config Empresa)</span>`}</label>`).join("")}
      ${r.rfcs.length > 1 ? '<div class="estado" style="color:var(--warn)">⚠ Hay archivos de varias empresas. Cárgalas por separado si vas a analizar saldos, para no mezclar.</div>' : ""}
      <div class="fila"><button class="primario" onclick="compl.procesar()">✔ Cargar seleccionados</button><button onclick="modal.cerrar()">Cancelar</button></div>`, 620);
  },
  async procesar(){
    const sel = [...document.querySelectorAll(".selRfc:checked")].map(c => c.value);
    modal.cerrar();
    if (!sel.length) return;
    $("caEstado").textContent = "Marcando obligaciones y copiando archivos…";
    const r = await pywebview.api.compl_procesar(sel);
    window.__listo = true;
    $("caEstado").textContent = "Carga terminada.";
    alert(r.msg);
    compl.obligs(); compl.panel(); compl.archivos();
  },
  error(msg){ window.__midiendo = false; window.__listo = true; $("caEstado").textContent = "Error"; alert(msg); },

  // ── Config Empresa ────────────────────────────────────────────────────────
  CAMPOS: ["destinatario", "cc", "asunto_template", "carpeta_raiz", "notas_adicionales"],
  async ccCargar(){
    const r = await pywebview.api.compl_cc_cargar($("ccRfc").value);
    $("ccNombre").textContent = r.nombre || "RFC no registrado";
    $("ccReg").textContent = r.regimen || "";
    $("ccReg").style.color = r.regimen_ok === null ? "" : (r.regimen_ok ? "var(--success)" : "#E65100");
    compl.CAMPOS.forEach(k => $("cc_" + k).value = r.cfg[k] || "");
  },
  async ccGuardar(){
    const d = {}; compl.CAMPOS.forEach(k => d[k] = $("cc_" + k).value);
    const r = await pywebview.api.compl_cc_guardar($("ccRfc").value, d);
    $("ccMsg").textContent = r.msg; if (r.ok) compl.panel();
  },
  async ccCarpeta(){ const d = await pywebview.api.compl_cc_buscar_carpeta(); if (d) $("cc_carpeta_raiz").value = d; },
  async ccSubirCsf(){
    const r = await pywebview.api.compl_cc_subir_csf(); if (r.cancelado) return;
    alert(r.msg);
    if (r.ok){ await compl.refrescarMeta(); $("ccRfc").value = r.rfc; compl.ccCargar(); }
  },
  async anios(){
    const a = await pywebview.api.compl_anios();
    modal.abrir(`<h3>Años de trabajo</h3>
      <div class="estado">Captura los años que necesites (permitido ${a.min}–${a.max}). Ejemplos: 2015, 2018, 2024-2026</div>
      <input id="anTxt" value="${esc(a.texto)}" oninput="compl.aniosPrev()"><div id="anPrev" class="estado"></div>
      <div class="fila"><button class="fantasma" onclick="anTxt.value='${a.min}-${a.max}';compl.aniosPrev()">Todo ${a.min}–${a.max}</button>
        <button class="fantasma" onclick="anTxt.value='${a.hoy - 4}-${a.hoy}';compl.aniosPrev()">Últimos 5 (${a.hoy - 4}-${a.hoy})</button></div>
      <div class="fila"><button class="primario" onclick="compl.aniosGuardar()">💾 Guardar</button><button onclick="modal.cerrar()">Cancelar</button></div>`, 520);
    compl.aniosPrev();
  },
  async aniosPrev(){
    const a = await pywebview.api.compl_anios($("anTxt").value);
    $("anPrev").style.color = a.validos.length ? "var(--accent)" : "var(--warn)";
    $("anPrev").textContent = a.validos.length ? `✔ ${a.validos.length} año(s): ${a.fmt}` : "⚠ Sin años válidos (se usará 2015–2040 completo).";
  },
  async aniosGuardar(){
    const r = await pywebview.api.compl_anios_guardar($("anTxt").value);
    modal.cerrar(); compl.meta.anios = r.anios; compl.pintarCombos(); alert(r.msg);
  },

  // ── Reportes ──────────────────────────────────────────────────────────────
  async reporte(tipo){
    const pref = {panel: "cp", obligaciones: "co", saldos: "sa", archivos: "ca"}[tipo];
    const p = {mes: $(pref + "Mes").value, anio: $(pref + "Anio").value,
               rfc: tipo === "obligaciones" ? $("coRfc").value : tipo === "saldos" ? $("saRfc").value : tipo === "archivos" ? $("caRfc").value : ""};
    const r = await pywebview.api.compl_reporte(tipo, p);
    if (!r.ok){ alert(r.msg); return; }
    if (!r.n && !confirm("No hay datos para el periodo seleccionado.\n\n¿Generar de todos modos (solo encabezados)?")) return;
    modal.abrir(`<h3>${esc(r.titulo)}</h3><div class="estado">${esc(r.meta)}</div>
      <div class="estado" style="color:var(--accent)">${r.n} renglón(es)</div>
      <div class="fila">Formato: ${r.formatos.map((f, i) => `<label><input type="radio" name="rpFmt" value="${f.id}" ${i ? "" : "checked"}> ${esc(f.nombre)}</label>`).join(" ")}</div>
      <div class="fila"><button class="primario" onclick="compl.reporteExportar()">📊 Generar</button><button onclick="modal.cerrar()">Cancelar</button></div>`, 520);
  },
  async reporteExportar(){
    const fmt = document.querySelector('input[name="rpFmt"]:checked').value;
    modal.cerrar();
    const r = await pywebview.api.compl_reporte_exportar(fmt);
    if (r.cancelado) return;
    if (!r.ok){ alert("Error al generar el reporte:\n" + r.msg); return; }
    if (confirm(`✅ Se generó:\n${r.ruta}\n\n¿Abrirlo ahora?`)) pywebview.api.compl_abrir(r.ruta);
  },

  // ── Preparar envío de correo (_DialogEnvioCompliance) ──────────────────────
  async envio(rfc, mes, anio){
    const d = await pywebview.api.compl_envio_abrir(rfc, mes, anio);
    if (!d.ok){ alert(d.msg); return; }
    compl._env = d; compl._envSel = new Set(d.archivos.map(a => a.ruta));
    modal.abrir(`<h3>📤 ${esc(d.empresa)} — ${esc(d.mes_txt)} ${d.anio}</h3>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
        <div style="display:flex;flex-direction:column;gap:6px">
          <div class="estado">📁 Carpeta del mes: <span style="color:${d.carpeta ? "" : "var(--danger)"}">${esc(d.carpeta || "⚠ Carpeta no encontrada")}</span></div>
          <div class="fila">Selecciona archivos a adjuntar: <button class="fantasma" onclick="compl.envTodos(true)">✓ Todos</button><button class="fantasma" onclick="compl.envTodos(false)">✗ Ninguno</button></div>
          <div id="envLista" class="lista" style="height:300px"></div>
          <button onclick="compl.envAgregar()">➕ Agregar archivos adicionales…</button>
        </div>
        <div style="display:flex;flex-direction:column;gap:6px"><span class="estado">Vista previa del correo:</span>
          <pre id="envPrev" style="margin:0;height:340px;overflow:auto;background:#F8FAFF;border:1px solid var(--border);border-radius:8px;padding:8px;font:11px Consolas,monospace;white-space:pre-wrap"></pre></div>
      </div>
      <div class="fila"><span id="envCuenta" class="estado"></span><span class="espacio"></span>
        <button id="envBtn" class="primario" style="background:var(--success);border-color:var(--success)" onclick="compl.envEnviar()">📨 Enviar Correo</button>
        <button onclick="modal.cerrar(); compl.envioSiguiente()">✖ Cancelar</button></div>`, 980);
    compl.envPintar();
  },
  envPintar(){
    const ico = n => ({pdf: "📄", xml: "📋", xlsx: "📊", xls: "📊", zip: "🗜", rar: "🗜", sua: "💾", txt: "📝"}[n.split(".").pop().toLowerCase()] || "📎");
    $("envLista").innerHTML = compl._env.archivos.map((a, i) => `<li style="background:${a.extra ? "#FFF7ED" : "#F0FDF4"}">
      <label style="display:flex;gap:8px"><input type="checkbox" ${compl._envSel.has(a.ruta) ? "checked" : ""} onchange="compl.envMarca(${i}, this.checked)">
      <span>${ico(a.nombre)}  ${esc(a.nombre)}<br><span class="estado">${esc(a.tam)}</span></span></label></li>`).join("")
      || '<li class="vacio">Sin archivos en la carpeta del mes. Usa "➕ Agregar" para añadir manualmente.</li>';
    compl.envPreview();
  },
  envMarca(i, v){ const r = compl._env.archivos[i].ruta; v ? compl._envSel.add(r) : compl._envSel.delete(r); compl.envPreview(); },
  envTodos(v){ compl._envSel = new Set(v ? compl._env.archivos.map(a => a.ruta) : []); compl.envPintar(); },
  async envAgregar(){
    const extra = await pywebview.api.compl_envio_agregar();
    extra.forEach(a => { if (!compl._env.archivos.some(x => x.ruta === a.ruta)){ a.extra = true; compl._env.archivos.push(a); compl._envSel.add(a.ruta); } });
    compl.envPintar();
  },
  async envPreview(){
    const e = compl._env, r = await pywebview.api.compl_envio_preview(e.rfc, e.mes, e.anio, [...compl._envSel]);
    $("envPrev").textContent = r.cuerpo; $("envCuenta").textContent = r.cuenta;
  },
  async envEnviar(){
    const e = compl._env, sel = [...compl._envSel];
    const c = await pywebview.api.compl_envio_confirmacion(e.rfc, e.mes, e.anio, sel);
    if (!c.ok){ alert(c.msg); return; }
    if (!confirm(c.texto)) return;
    $("envBtn").disabled = true; $("envBtn").textContent = "Enviando…";
    const r = await pywebview.api.compl_envio_enviar(e.rfc, e.mes, e.anio, sel);
    compl.log(r.log);
    if (!r.ok){ $("envBtn").disabled = false; $("envBtn").textContent = "📨 Enviar Correo";
      alert(`No se pudo enviar:\n\n${r.msg}\n\nVerifica la configuración de email.`); return; }
    alert(r.msg); modal.cerrar(); compl.envioSiguiente();
  },
  log(msg){
    const t = new Date().toLocaleTimeString("es-MX", {hour12: false});
    const el = $("ccLog"); if (!el) return;
    el.textContent += `[${t}] ${msg}\n`; el.scrollTop = el.scrollHeight;
  },
};
app.modulos.compl = compl;
