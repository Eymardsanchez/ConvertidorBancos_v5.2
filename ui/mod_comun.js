// Ventanas compartidas (5.2): Empresas / RFC, Bitácora, conflicto al reimportar.
// Backend: api_comun.py
const comun = {
  // ── Catálogo de Empresas / RFC (DialogEmpresas de la 5.0) ───────────────────
  async empresas(){
    modal.abrir(`<h3>Catálogo de Empresas <small class="estado">RFC · Nombre · Régimen fiscal (CSF)</small></h3>
      <div class="tabla" style="max-height:260px;border:1px solid var(--border);border-radius:8px">
        <table><thead><tr><th>RFC</th><th>Nombre de Empresa</th><th>Régimen(es) SAT</th></tr></thead>
        <tbody id="empBody"></tbody></table></div>
      <div style="display:grid;grid-template-columns:110px 1fr;gap:6px 10px;align-items:center">
        <span>RFC:</span><input id="empRfc" style="font:700 13px Consolas,monospace" oninput="comun.empRfc()">
        <span></span><div id="empRfcMsg" class="msg"></div>
        <span>Nombre:</span><input id="empNombre">
        <span>Régimen(es):</span><div id="empReg" class="estado"></div>
      </div>
      <div id="empMsg" class="msg"></div>
      <div class="fila"><button onclick="comun.empNuevo()">➕ Nuevo</button>
        <button class="primario" onclick="comun.empGuardar()">💾 Guardar</button>
        <button onclick="comun.empCsf()">📄 Subir CSF</button>
        <button onclick="comun.empEliminar()">🗑 Eliminar</button>
        <span class="espacio"></span><button onclick="modal.cerrar()">✖ Cerrar</button></div>`, 760);
    comun.empRefrescar();
  },
  async empRefrescar(sel){
    comun._emp = await pywebview.api.emp_listar();
    $("empBody").innerHTML = comun._emp.map((e, i) =>
      `<tr data-i="${i}" style="cursor:pointer;${e.csf ? "" : "color:#9E9E9E"}" onclick="comun.empSel(${i})">
        <td>${esc(e.rfc)}</td><td>${esc(e.nombre)}</td><td>${esc(e.regimen)}</td></tr>`).join("");
    if (sel){ const i = comun._emp.findIndex(e => e.rfc === sel); if (i >= 0) comun.empSel(i); }
  },
  empSel(i){
    const e = comun._emp[i]; comun._empSel = e.rfc;
    document.querySelectorAll("#empBody tr").forEach(tr => tr.style.background = tr.dataset.i == i ? "var(--accent-soft)" : "");
    $("empRfc").value = e.rfc; $("empNombre").value = e.nombre; $("empRfcMsg").textContent = "";
    $("empReg").style.color = e.csf ? "var(--success)" : "#E65100";
    $("empReg").innerHTML = e.csf ? e.detalle.map(d => "• " + esc(d)).join("<br>")
                                  : "Sin CSF registrada — sube la Constancia de Situación Fiscal";
  },
  async empRfc(){
    const v = $("empRfc").value.toUpperCase(); $("empRfc").value = v;
    const ok = await pywebview.api.emp_validar_rfc(v);
    $("empRfcMsg").textContent = (ok || !v) ? "" : "⚠ Formato: AAA000000AA0 (moral) o AAAA000000AA0 (física)";
  },
  empNuevo(){ comun._empSel = null; ["empRfc", "empNombre"].forEach(i => $(i).value = "");
    $("empRfcMsg").textContent = ""; $("empReg").textContent = ""; $("empMsg").textContent = "";
    document.querySelectorAll("#empBody tr").forEach(tr => tr.style.background = ""); },
  async empGuardar(){
    const rfc = $("empRfc").value.trim().toUpperCase(), nombre = $("empNombre").value.trim();
    const ya = rfc ? await pywebview.api.emp_existe(rfc) : null;
    if (ya && !confirm(`RFC ${rfc} ya existe (${ya}).\n¿Actualizar nombre?`)) return;
    const r = await pywebview.api.emp_guardar(rfc, nombre);
    $("empMsg").className = r.ok ? "msg ok" : "msg"; $("empMsg").textContent = r.msg;
    if (r.ok){ await comun.empRefrescar(); comun.empNuevo(); $("empMsg").className = "msg ok"; $("empMsg").textContent = r.msg; }
  },
  async empEliminar(){
    if (!comun._empSel){ $("empMsg").className = "msg"; $("empMsg").textContent = "Elige una empresa de la lista."; return; }
    const e = comun._emp.find(x => x.rfc === comun._empSel);
    if (!confirm(`¿Eliminar '${e.nombre}' (${e.rfc})?`)) return;
    await pywebview.api.emp_eliminar(e.rfc); await comun.empRefrescar(); comun.empNuevo();
  },
  async empCsf(){
    const r = await pywebview.api.emp_subir_csf();
    if (r.cancelado) return;
    $("empMsg").className = r.ok ? "msg ok" : "msg"; $("empMsg").textContent = r.msg;
    if (r.ok) comun.empRefrescar(r.rfc);
  },

  // ── Bitácora de conversiones (_DialogBitacora de la 5.0) ─────────────────────
  COLS_BIT: [["Fecha / Hora", "fecha_hora"], ["RFC", "rfc"], ["Empresa", "empresa"], ["Banco", "banco"],
             ["Periodo", "periodo"], ["Movimientos", "movimientos"], ["Usuario", "usuario"], ["Archivo PDF", "archivo_origen"]],
  bitacora(){
    modal.abrir(`<h3>Bitácora de Conversiones <small id="bitTotal" class="estado"></small></h3>
      <div class="fila">RFC: <input id="bitRfc" style="width:130px;font-family:Consolas,monospace">
        Banco: <select id="bitBanco">${["Todos","BBVA","Santander","Banorte","Banamex","Inbursa","Banbajío","Banregio","HSBC"].map(b => `<option>${b}</option>`).join("")}</select>
        Periodo (YYYY-MM): <input id="bitPer" style="width:90px;font-family:Consolas,monospace">
        <button class="primario" onclick="comun.bitCargar()">🔍 Filtrar</button>
        <button onclick="bitRfc.value='';bitBanco.value='Todos';bitPer.value='';comun.bitCargar()">Limpiar</button></div>
      <div class="tabla" style="max-height:420px;border:1px solid var(--border);border-radius:8px">
        <table><thead><tr>${comun.COLS_BIT.map(c => `<th>${c[0]}</th>`).join("")}</tr></thead><tbody id="bitBody"></tbody></table></div>
      <div class="fila" style="justify-content:flex-end"><button onclick="modal.cerrar()">Cerrar</button></div>`, 1100);
    comun.bitCargar();
  },
  async bitCargar(){
    const r = await pywebview.api.bit_listar($("bitRfc").value, $("bitBanco").value, $("bitPer").value);
    $("bitBody").innerHTML = r.filas.map(e => `<tr>${comun.COLS_BIT.map(c => `<td>${esc(e[c[1]] ?? "")}</td>`).join("")}</tr>`).join("");
    $("bitTotal").textContent = `${r.filas.length} mostrado(s)  |  ${r.total} en total`;
  },

  // ── Conflicto al reimportar (App._resolver_conflicto de la 5.0) ──────────────
  conflicto(cid, c){
    const caja = (t, x, col) => `<div style="flex:1;border:1px solid ${col};border-radius:8px;overflow:hidden">
      <div style="background:${col};color:#fff;font-weight:600;padding:4px 8px">${t}</div>
      <pre style="margin:0;padding:8px;font:12px Consolas,monospace;white-space:pre-wrap">Fecha: ${esc(x.fecha)}
Desc: ${esc(x.desc)}
Depósito: ${esc(x.deposito)}   Retiro: ${esc(x.retiro)}
UUID: ${esc(x.uuid)}</pre></div>`;
    modal.abrir(`<h3>⚠ Otro proceso ya modificó este registro</h3>
      <div class="estado">${esc(c.tabla)}  ID=${esc(c.id)}   (tu versión ${esc(c.v_local)} · guardada ${esc(c.v_guardada)})</div>
      <div class="fila" style="align-items:stretch">${caja("TU CAMBIO (Excel)", c.local, "#1565C0")}${caja("YA GUARDADO (otro)", c.guardado, "#C62828")}</div>
      <div class="fila"><button class="primario" style="background:var(--danger);border-color:var(--danger)" onclick="comun.responder(${cid},'sobrescribir')">Sobrescribir con lo mío</button>
        <button onclick="comun.responder(${cid},'descartar')">Descartar mi cambio</button></div>`, 720);
  },
  responder(cid, v){ modal.cerrar(); pywebview.api.comun_conflicto_responder(cid, v); },
};
