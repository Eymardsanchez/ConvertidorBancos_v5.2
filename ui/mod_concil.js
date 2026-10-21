// Módulo Conciliación CFDI (5.2). Backend: api_conciliacion.py
const concil = {
  formas: new Set(), mesesIva: new Set(),
  async montar(el){
    concil.meta = await pywebview.api.concil_meta();
    const m = concil.meta;
    el.innerHTML = `
    <div class="apilado" style="display:flex;flex-direction:column;gap:10px;height:100%;overflow:auto">
      <div class="fila"><div class="chip">⇄</div><div><h2 style="margin:0;font-size:15px">Conciliación Bancaria ↔ CFDI</h2>
        <span class="estado">Cruza movimientos bancarios con los CFDI del SAT y exporta el papel de trabajo</span></div></div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:10px">
        <section class="card"><h2>1 · Carpetas con XML (CFDI)</h2>
          <div class="fila"><button class="primario" onclick="concil.addCarpeta()">＋ Agregar carpeta</button>
            <button onclick="concil.abrirSat()" ${m.sat_ok ? "" : "disabled title='Falta el paquete satcfdi'"}>📥 Descargar del SAT</button>
            <button onclick="concil.addXml()">📄 Agregar XML (sin carpeta)</button>
            <button class="fantasma" onclick="concil.clearXml()">✕ Limpiar</button></div>
          <ul id="kXml" class="lista" style="height:110px"></ul><div id="kXmlCuenta" class="estado" style="text-align:right">0 carpetas  |  0 XMLs cargados</div>
        </section>
        <section class="card"><h2>2 · Estados de cuenta (PDF)</h2>
          <div class="fila"><button class="primario" onclick="concil.addPdf()">＋ Agregar PDFs</button>
            <button class="fantasma" onclick="concil.clearPdf()">✕ Limpiar</button></div>
          <ul id="kPdf" class="lista" style="height:110px"></ul><div id="kPdfCuenta" class="estado" style="text-align:right">0 PDFs</div>
        </section>
      </div>
      <section class="card"><h2>3 · Configuración y periodo</h2>
        <div class="fila" style="align-items:flex-end">
          <label class="campo">Empresa <select id="kEmp" style="min-width:340px">${m.empresas.map(e => `<option value="${esc(e.rfc)}">${esc(e.rfc)}  —  ${esc(e.nombre)}</option>`).join("")}</select></label>
          <label class="campo">Año a conciliar <select id="kAnio">${m.anios.map(a => `<option ${a === m.anio_default ? "selected" : ""}>${a}</option>`).join("")}</select></label>
          <label class="campo" style="flex:1">Guardar en <div class="fila"><input id="kDestino" style="flex:1" value=""><button onclick="concil.destino()">…</button></div></label>
        </div>
        <div id="kReg" class="estado"></div>
        <div class="fila"><button onclick="concil.abrirFormas()">💳 Forma de pago…</button><b id="kFormasTxt" style="color:var(--accent-ink)">Todas (01–99)</b>
          <span style="margin-left:16px" class="estado">Meses IVA:</span><b id="kMesesTxt" style="color:var(--accent-ink)">Todos</b><button class="fantasma" onclick="concil.abrirMeses()">▼</button>
          <span class="estado" style="color:var(--accent)">Solo del año elegido.</span></div>
      </section>
      <div class="fila"><button onclick="concil.abrirFases()">⚙ Fases de conciliación…</button><span id="kFasesTxt" class="estado"></span></div>
      <fieldset style="border:1px solid var(--border);border-radius:10px;padding:6px 10px"><legend class="estado"> Administrador de Conciliaciones </legend>
        <div class="fila"><button onclick="concil.reimprimir()">📊 Reimprimir → Excel</button>
          <button onclick="concil.admin()">🔎 Detalle de Conciliación</button></div></fieldset>
      <div class="fila"><button style="flex:1" onclick="concil.subirXml()">🔄 Actualizar XML</button>
        <button style="flex:1" onclick="concil.reconciliar()">🔗 Reconciliar (sin CFDI)</button></div>
      <div class="fila"><button id="kBtn" class="primario" style="flex:1;padding:12px;font-size:14px;background:var(--success);border-color:var(--success)" onclick="concil.ejecutar()">⚡ LEER PDFs → CONCILIAR → EXPORTAR EXCEL</button>
        <button id="kBtnPol" disabled onclick="concil.polizas()" style="padding:12px">Pólizas COI (tras conciliar)</button></div>
      <div class="barra-prog"><div id="kBarra"></div></div>
      <pre id="kLog" style="margin:0;min-height:140px;flex:1;overflow:auto;background:#1A1A19;color:#C3C2B7;border-radius:8px;padding:8px;font:12px Consolas,monospace"></pre>
    </div>`;
    $("kEmp").onchange = concil.empresa; concil.empresa();
    $("kDestino").value = m.destino;
    concil.fasesTxt();
  },
  async empresa(){ const r = await pywebview.api.concil_empresa($("kEmp").value);
    $("kReg").textContent = r.txt; $("kReg").style.color = r.ok === null ? "" : (r.ok ? "var(--success)" : "#E65100"); },
  rfc(){ return $("kEmp").value; },
  pintarXml(l){ $("kXml").innerHTML = l.map(x => `<li>${esc(x)}</li>`).join("") || '<li class="vacio">Sin carpetas ni XML.</li>';
    $("kXmlCuenta").textContent = l.length ? `${l.length} elemento(s)  |  XMLs pendientes de escanear` : "0 carpetas  |  0 XMLs cargados"; },
  xmlCuenta(t){ $("kXmlCuenta").textContent = t; },
  async addCarpeta(){ concil.pintarXml(await pywebview.api.concil_add_carpeta()); },
  async addXml(){ concil.pintarXml(await pywebview.api.concil_add_xml()); },
  async clearXml(){ concil.pintarXml(await pywebview.api.concil_clear_carpetas()); },
  pdfs(l){
    $("kPdf").innerHTML = l.map(d => `<li class="fila"><span class="pill" style="${d.estado === "error" ? "background:var(--danger-bg);color:var(--danger)" : ""}">${esc(d.banco)}</span>
      <span style="flex:1">${esc(d.nombre)}</span><b class="estado">${d.movs || "—"}</b>${d.estado === "omitido" ? '<span class="estado">omitido</span>' : ""}</li>`).join("") || '<li class="vacio">Sin PDFs.</li>';
    $("kPdfCuenta").textContent = `${l.length} PDF(s)`;
  },
  async addPdf(){ concil.pdfs(await pywebview.api.concil_add_pdf()); },
  async clearPdf(){ concil.pdfs(await pywebview.api.concil_clear_pdfs()); },
  async destino(){ const d = await pywebview.api.concil_elegir_destino(); if (d) $("kDestino").value = d; },
  log(msg, tag){
    const col = {ok: "#4ADE80", err: "#F87171", info: "#60A5FA", warn: "#FACC15"}[tag] || "";
    const t = new Date().toLocaleTimeString("es-MX", {hour12: false});
    $("kLog").insertAdjacentHTML("beforeend", `<span style="color:${col}">[${t}] ${esc(msg)}</span>\n`);
    $("kLog").scrollTop = $("kLog").scrollHeight;
  },
  ocupado(v){ $("kBarra").style.width = v ? "100%" : "0"; $("kBarra").style.opacity = v ? ".4" : "1"; },
  aviso(titulo, msg){ concil.ocupado(false); if (!window.__prueba) alert(`${titulo}\n\n${msg}`); },

  // ── Forma de pago / meses IVA / fases ─────────────────────────────────────
  abrirFormas(){
    modal.abrir(`<h3>Selecciona una o varias formas de pago</h3><div class="estado">Catálogo c_FormaPago del SAT (01 – 99) · marca las que quieras conciliar</div>
      <div class="fila"><button class="fantasma" onclick="document.querySelectorAll('.kfp').forEach(c=>c.checked=true)">Todos</button>
        <button class="fantasma" onclick="document.querySelectorAll('.kfp').forEach(c=>c.checked=false)">Ninguno</button></div>
      <div class="lista" style="max-height:360px">${concil.meta.formas_pago.map(([c, d]) =>
        `<li><label style="display:flex;gap:8px"><input type="checkbox" class="kfp" value="${c}" ${concil.formas.has(c) ? "checked" : ""}>
         <b class="pill">${c}</b> ${esc(d)}</label></li>`).join("")}</div>
      <div class="fila"><button class="primario" onclick="concil.aceptarFormas()">✔ Aceptar selección</button><button onclick="modal.cerrar()">Cancelar</button></div>`, 520);
  },
  aceptarFormas(){
    concil.formas = new Set([...document.querySelectorAll(".kfp:checked")].map(c => c.value));
    $("kFormasTxt").textContent = concil.formas.size ? [...concil.formas].sort().join(", ") : "Todas (01–99)";
    modal.cerrar();
  },
  MES: ["", "Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"],
  abrirMeses(){
    modal.abrir(`<h3>Meses para cálculo de IVA</h3><div class="estado">Ninguno o los 12 = Todos.</div>
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px">${concil.MES.slice(1).map((n, i) =>
        `<label><input type="checkbox" class="kmi" value="${i + 1}" ${concil.mesesIva.has(i + 1) ? "checked" : ""}> ${String(i + 1).padStart(2, "0")} - ${n}</label>`).join("")}</div>
      <div class="fila"><button class="primario" onclick="concil.aceptarMeses()">✔ Aceptar</button><button onclick="modal.cerrar()">Cancelar</button></div>`, 460);
  },
  aceptarMeses(){
    concil.mesesIva = new Set([...document.querySelectorAll(".kmi:checked")].map(c => +c.value));
    const s = [...concil.mesesIva].sort((a, b) => a - b);
    $("kMesesTxt").textContent = (!s.length || s.length === 12) ? "Todos" : s.map(x => concil.MES[x]).join(", ");
    modal.cerrar();
  },
  fasesTxt(){ $("kFasesTxt").textContent = `${concil.meta.fases_activas.length} fase(s) activas`; },
  abrirFases(){
    const act = new Set(concil.meta.fases_activas);
    modal.abrir(`<h3>Fases de conciliación</h3><div class="estado">Marca las fases que quieras aplicar. Se ejecutan en orden: cada fase solo ve lo que la anterior dejó sin conciliar.</div>
      ${concil.meta.niveles.map(n => `<div style="border-left:4px solid ${n.color};padding-left:10px">
        <div><b style="color:${n.color}">${esc(n.nombre)}</b> <span class="estado">${esc(n.desc)}</span></div>
        ${n.fases.map(f => `<label style="display:block"><input type="checkbox" class="kfase" value="${f.id}" ${act.has(f.id) ? "checked" : ""}> ${esc(f.etq)}</label>`).join("")}</div>`).join("")}
      <div class="estado">La Fase 9 cruza solo por importe: úsala como último recurso.</div>
      <div class="fila"><button class="primario" onclick="concil.aceptarFases()">Cerrar</button></div>`, 620);
  },
  async aceptarFases(){
    concil.meta.fases_activas = await pywebview.api.concil_fases([...document.querySelectorAll(".kfase:checked")].map(c => c.value));
    concil.fasesTxt(); modal.cerrar();
  },

  // ── Conciliar ─────────────────────────────────────────────────────────────
  async ejecutar(){
    const r = await pywebview.api.concil_ejecutar({rfc: concil.rfc(), anio: $("kAnio").value, destino: $("kDestino").value,
      formas: [...concil.formas], meses_iva: [...concil.mesesIva]});
    if (!r.ok){ alert(r.msg); return; }
    window.__listo = false; window.__maxGap = 0; window.__midiendo = true;
    $("kLog").textContent = ""; concil.ocupado(true);
    const b = $("kBtn"); b.textContent = "■ DETENER PROCESO"; b.style.background = b.style.borderColor = "var(--danger)";
    b.onclick = concil.detener;
  },
  async detener(){ await pywebview.api.concil_detener(); $("kBtn").disabled = true; $("kBtn").textContent = "■ Deteniendo…"; },
  fin(r){
    window.__midiendo = false; window.__listo = true; concil._fin = r; concil.ocupado(false);
    const b = $("kBtn"); b.disabled = false; b.textContent = "⚡ LEER PDFs → CONCILIAR → EXPORTAR EXCEL";
    b.style.background = b.style.borderColor = "var(--success)"; b.onclick = concil.ejecutar;
    if (!r.ok){ if (r.msg && !window.__prueba) alert("Error en conciliación\n\n" + r.msg); return; }
    $("kBtnPol").disabled = false; $("kBtnPol").textContent = `Pólizas COI → ${r.conc} movimientos listos`;
    if (window.__prueba) return;
    alert(`Proceso terminado exitosamente.\n\nBancos procesados   : ${r.bancos}\nMovimientos totales : ${r.movs}\nConciliados         : ${r.conc} (${r.pct}%)\nSin CFDI            : ${r.pend}\n` +
          (r.rev ? `Requieren revision  : ${r.rev}\n` : "") + `\n${r.destino}`);
    pywebview.api.concil_abrir(r.destino);
  },
  polizas(){ alert("Pólizas COI: se migra en la fase 5 de la 5.2."); },

  // ── Actualizar XML / Reconciliar ──────────────────────────────────────────
  async subirXml(){ const r = await pywebview.api.concil_subir_xml(concil.rfc()); if (!r.ok){ alert(r.msg); return; } $("kLog").textContent = ""; concil.ocupado(true); },
  async reconciliar(){ const r = await pywebview.api.concil_reconciliar_prep(concil.rfc()); if (!r.ok){ alert(r.msg); return; } $("kLog").textContent = ""; concil.ocupado(true); },
  reconciliarElegir(banco, xml){
    modal.abrir(`<h3>Reconciliar filas 'sin CFDI'</h3><div class="estado">Elige qué meses de estados de cuenta re-conciliar y qué meses de XML usar. Solo se tocan las filas 'sin CFDI'.</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
        <fieldset><legend>Meses de estados de cuenta</legend>${banco.map(b => `<label style="display:block"><input type="checkbox" class="kbm" value="${b.mes}" ${b.sin ? "checked" : ""}> ${b.nombre} (${b.sin} sin CFDI)</label>`).join("")}</fieldset>
        <fieldset><legend>Meses de XML a conciliar</legend>${xml.map(x => `<label style="display:block"><input type="checkbox" class="kxm" value="${x.mes}" checked> ${x.nombre} (${x.n} CFDI)</label>`).join("")}</fieldset>
      </div><div id="kRm" class="msg"></div>
      <div class="fila"><button class="primario" onclick="concil.reconciliarGo()">🔗 Reconciliar</button><button onclick="modal.cerrar()">Cancelar</button></div>`, 620);
  },
  async reconciliarGo(){
    const b = [...document.querySelectorAll(".kbm:checked")].map(c => +c.value), x = [...document.querySelectorAll(".kxm:checked")].map(c => +c.value);
    if (!b.length){ $("kRm").textContent = "Marca al menos un mes de estado de cuenta."; return; }
    if (!x.length){ $("kRm").textContent = "Marca al menos un mes de XML."; return; }
    modal.cerrar(); concil.ocupado(true); await pywebview.api.concil_reconciliar_run(b, x);
  },

  // ── Administrador de Conciliaciones ───────────────────────────────────────
  async admin(){
    const r = await pywebview.api.concil_lista_bd(concil.rfc());
    if (!r.ok){ alert("Error de base de datos\n\n" + r.msg); return; }
    concil._adm = r;
    modal.abrir(`<h3>Administrador de Conciliaciones — ${esc(r.empresa)}</h3>
      <div class="estado">RFC: ${esc(concil.rfc())}   ·   ${r.lista.length} conciliacion(es) en la base${r.lista.length ? "" : "   ·   (aun no hay conciliaciones guardadas)"}</div>
      <div class="tabla" style="max-height:340px;border:1px solid var(--border);border-radius:8px"><table><thead><tr><th>ID</th><th>Año</th><th>Mes(es)</th><th>Guardada</th><th class="n">Filas</th><th class="n">Conciliadas</th></tr></thead>
      <tbody>${r.lista.map(c => `<tr style="cursor:pointer" data-id="${c.id}" onclick="concil.admSel(this)" ondblclick="concil.detalle(${c.id})"><td>${c.id}</td><td>${esc(c.periodo)}</td><td>${esc(c.meses)}</td><td>${esc(c.creado)}</td><td class="n">${c.filas}</td><td class="n">${c.conc}</td></tr>`).join("")}</tbody></table></div>
      <div class="fila"><button class="primario" onclick="concil.detalle(concil._admId)">📄 Ver detalle</button>
        <button onclick="concil.subirExcel()">📤 Subir Excel revisado</button><button onclick="concil.admin()">🔄 Actualizar</button>
        <button onclick="concil.eliminarBd()" style="color:var(--danger)">🗑 Eliminar</button><button onclick="modal.cerrar()">Cerrar</button></div>`, 820);
  },
  admSel(tr){ document.querySelectorAll("#ventana tr[data-id]").forEach(x => x.style.background = ""); tr.style.background = "var(--accent-soft)"; concil._admId = +tr.dataset.id; },
  async detalle(cid){
    if (!cid){ alert("Elige una conciliacion de la lista."); return; }
    const r = await pywebview.api.concil_detalle(cid);
    if (!r.ok){ alert(r.msg); return; }
    const conc = r.filas.filter(f => (f.uuid || "").trim()).length;
    const volver = concil._adm ? '<button onclick="concil.admin()">← Volver a la lista</button>' : "";
    modal.abrir(`<h3>Detalle de la conciliacion #${cid}</h3><div class="estado">${esc(concil._adm?.empresa || "")}   ·   ${r.filas.length} filas   ·   ${conc} con CFDI</div>
      <div class="tabla" style="max-height:60vh;border:1px solid var(--border);border-radius:8px"><table><thead><tr><th>ID</th><th>Banco</th><th>Fecha</th><th>Concepto</th><th class="n">Retiro</th><th class="n">Depósito</th><th>UUID CFDI</th><th>Tipo</th><th>Tipo match</th></tr></thead>
      <tbody>${r.filas.map(f => `<tr style="background:${(f.uuid || "").trim() ? "#E8F5E9" : "#FDECEA"}"><td>${f.id}</td><td>${esc(f.banco)}</td><td>${esc(f.fecha)}</td><td style="white-space:normal;min-width:260px">${esc(f.concepto)}</td>
        <td class="n">${f.retiro ? f.retiro.toLocaleString("es-MX", {minimumFractionDigits: 2}) : ""}</td><td class="n">${f.deposito ? f.deposito.toLocaleString("es-MX", {minimumFractionDigits: 2}) : ""}</td>
        <td style="font-family:Consolas,monospace;font-size:11px">${esc(f.uuid)}</td><td>${esc(f.tipo)}</td><td>${esc(f.match)}</td></tr>`).join("")}</tbody></table></div>
      <div class="fila">${volver}<button onclick="modal.cerrar()">Cerrar</button></div>`, 1200);
  },
  async subirExcel(){ const r = await pywebview.api.concil_subir_excel(concil.rfc()); if (r.cancelado) return;
    alert((r.ok ? "Excel subido\n\n" : "Error al subir el Excel\n\n") + r.msg); if (r.ok) concil.admin(); },
  async eliminarBd(){
    const id = concil._admId; if (!id){ alert("Elige una conciliacion de la lista."); return; }
    const c = concil._adm.lista.find(x => x.id === id);
    if (!confirm(`¿Eliminar la conciliación #${id} (${c.periodo} · ${c.meses})?\n\nSe borrarán sus filas guardadas y su historial. Esta acción NO se puede deshacer.`)) return;
    const r = await pywebview.api.concil_eliminar_bd(id); alert(r.msg); concil._admId = null; concil.admin();
  },

  // ── Reimprimir → Excel (integrar conciliaciones) ───────────────────────────
  async reimprimir(){
    const r = await pywebview.api.concil_lista_bd(concil.rfc());
    if (!r.ok){ alert("Error de base de datos\n\n" + r.msg); return; }
    if (!r.lista.length){ alert("No hay conciliaciones guardadas en la BD para esta empresa.\n\nConcilia y guarda primero, o sube el Excel revisado."); return; }
    concil._adm = null;
    const anios = [...new Set(r.lista.map(c => String(c.periodo)).filter(a => a && a !== "—"))].sort().reverse();
    modal.abrir(`<h3>Integrar conciliaciones — ${esc(r.empresa)}</h3><div class="estado">Marca una o varias conciliaciones para combinarlas en un solo Excel (mes, varios meses o todo el año).</div>
      <div class="fila"><button class="fantasma" onclick="document.querySelectorAll('.krc').forEach(c=>c.checked=true)">Todas</button>
        <button class="fantasma" onclick="document.querySelectorAll('.krc').forEach(c=>c.checked=false)">Ninguna</button>
        ${anios.length ? `Año: <select id="kRcY">${anios.map(a => `<option>${a}</option>`).join("")}</select><button class="fantasma" onclick="document.querySelectorAll('.krc').forEach(c=>c.checked=c.dataset.y===kRcY.value)">Marcar año</button>` : ""}</div>
      <div class="lista" style="max-height:300px;font-family:Consolas,monospace">${r.lista.map(c => `<li><label><input type="checkbox" class="krc" value="${c.id}" data-y="${esc(c.periodo)}" checked>
        ${esc(c.periodo)}  ${esc(c.meses)}  ·  ${esc(c.creado)}  ·  ${c.filas}/${c.conc}</label></li>`).join("")}</div>
      <div class="fila"><button class="primario" onclick="concil.reimprimirGo()">📊 Generar Excel</button><button onclick="modal.cerrar()">Cancelar</button></div>`, 640);
  },
  async reimprimirGo(){
    const ids = [...document.querySelectorAll(".krc:checked")].map(c => +c.value);
    const r = await pywebview.api.concil_reimprimir_generar(concil.rfc(), ids);
    if (r.cancelado) return;
    if (!r.ok){ alert(r.msg); return; }
    modal.cerrar();
    if (confirm(`✅ ${r.n} conciliacion(es) integradas en:\n${r.destino}\n\n¿Abrirlo ahora?`)) pywebview.api.concil_abrir(r.destino);
  },

  // ── Descarga Masiva SAT (solo Web Service) ─────────────────────────────────
  async abrirSat(){
    const s = await pywebview.api.sat_meta();
    modal.abrir(`<h3>📥 Descarga Masiva SAT <small class="estado">Usa tu e.firma (FIEL) — la contraseña no se guarda en disco</small></h3>
      <div style="display:grid;grid-template-columns:330px 1fr;gap:14px">
        <div style="display:flex;flex-direction:column;gap:6px;max-height:68vh;overflow:auto">
          <label class="campo">RFC <input id="satRfcD" list="satRfcs" value="${esc(concil.rfc())}"><datalist id="satRfcs">${s.rfcs.map(r => `<option>${esc(r)}</option>`).join("")}</datalist></label>
          <label class="campo">Carpeta destino <div class="fila"><input id="satCarp" readonly value="${esc(s.carpeta)}" style="flex:1"><button onclick="concil.satCarpeta()">📂</button></div></label>
          <span class="estado">Cada descarga crea {carpeta}/{RFC}/{fecha}/emitidos y /recibidos.</span>
          <b>e.firma (FIEL)</b>
          <div class="fila">.cer: <input id="satCer" readonly style="flex:1"><button onclick="concil.satArchivo('satCer','.cer')">…</button></div>
          <div class="fila">.key: <input id="satKey" readonly style="flex:1"><button onclick="concil.satArchivo('satKey','.key')">…</button></div>
          <label class="campo">Contraseña (.key): <input id="satPwd" type="password" autocomplete="off"></label>
          <b>Modo de búsqueda</b>
          <label><input type="radio" name="sModo" value="fecha" checked onchange="concil.satModo()"> Por rango de fechas</label>
          <label><input type="radio" name="sModo" value="uuid" onchange="concil.satModo()"> Por UUID específico</label>
          <div id="satPanFecha" style="display:flex;flex-direction:column;gap:6px">
            <label class="campo">Fecha inicial (AAAA-MM-DD): <input id="satIni" value="${s.f_ini}"></label>
            <label class="campo">Fecha final (AAAA-MM-DD): <input id="satFin" value="${s.f_fin}"></label>
            <div class="fila">Tipo: <label><input id="satEmi" type="checkbox" checked> Emitidos</label><label><input id="satRec" type="checkbox" checked> Recibidos</label></div>
            <span class="estado">Cada tipo marcado es una solicitud SAT independiente — desmarca el que no necesites para ahorrar cuota diaria.</span>
            <label class="campo">Filtrar por UUID(s) tras descargar (opcional, uno por línea): <textarea id="satFiltro" rows="3" style="font:12px Consolas,monospace"></textarea></label>
          </div>
          <div id="satPanUuid" class="oculto" style="display:flex;flex-direction:column;gap:6px">
            <label class="campo">UUID(s) — uno por línea: <textarea id="satUuids" rows="4" style="font:12px Consolas,monospace"></textarea></label>
            <span class="estado" style="color:var(--warn)">⚠ Cada UUID consume 1 de las ${s.max} solicitudes/día del RFC ante el SAT.</span>
          </div>
          <button id="satBtn" class="primario" style="background:var(--success);border-color:var(--success)" onclick="concil.satDescargar()">📥 Descargar</button>
          <button onclick="concil.satCerrar()">Cerrar</button>
        </div>
        <div style="display:flex;flex-direction:column;gap:6px"><b>Progreso</b><div class="barra-prog"><div id="satBarra"></div></div>
          <pre id="satLog" style="margin:0;flex:1;min-height:380px;overflow:auto;background:#1A1A19;color:#C3C2B7;border-radius:8px;padding:8px;font:12px Consolas,monospace;white-space:pre-wrap"></pre></div>
      </div>`, 1040);
  },
  satModo(){ const f = document.querySelector('input[name="sModo"]:checked').value === "fecha";
    $("satPanFecha").classList.toggle("oculto", !f); $("satPanUuid").classList.toggle("oculto", f); },
  async satArchivo(id, ext){ const r = await pywebview.api.sat_elegir_archivo(ext); if (r) $(id).value = r; },
  async satCarpeta(){ const r = await pywebview.api.sat_elegir_carpeta(); if (r) $("satCarp").value = r; },
  async satDescargar(){
    const p = {rfc: $("satRfcD").value, carpeta: $("satCarp").value, cer: $("satCer").value, key: $("satKey").value, pwd: $("satPwd").value,
      modo: document.querySelector('input[name="sModo"]:checked').value, f_ini: $("satIni").value, f_fin: $("satFin").value,
      emitidos: $("satEmi").checked, recibidos: $("satRec").checked, filtro: $("satFiltro").value, uuids: $("satUuids").value};
    const r = await pywebview.api.sat_descargar(p);
    if (!r.ok){ alert(r.msg); return; }
    $("satBtn").disabled = true; $("satBtn").textContent = "Descargando…"; $("satLog").textContent = ""; $("satBarra").style.width = "100%"; $("satBarra").style.opacity = ".4";
  },
  satCerrar(){ const p = $("satPwd"); if (p) p.value = ""; modal.cerrar(); },
  satLog(m){ const el = document.getElementById("satLog"); if (!el) return; el.textContent += m + "\n"; el.scrollTop = el.scrollHeight; },
};
// Python → pantalla (descarga SAT)
const sat = {
  log(m){ concil.satLog(m); },
  fin(r){
    const b = document.getElementById("satBtn"); if (b){ b.disabled = false; b.textContent = "📥 Descargar"; }
    const br = document.getElementById("satBarra"); if (br){ br.style.width = "0"; br.style.opacity = "1"; }
    const pwd = document.getElementById("satPwd"); if (pwd) pwd.value = "";          // no conservar la contraseña
    if (!r.ok){ concil.satLog("❌ " + r.msg); alert("Error de descarga SAT\n\n" + r.msg); return; }
    concil.pintarXml(r.xml); alert("Descarga completa\n\n" + r.msg);
  },
};
app.modulos.concil = concil;
