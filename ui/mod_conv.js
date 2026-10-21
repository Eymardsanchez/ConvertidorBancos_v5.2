// Módulo Convertidor PDF → Excel (5.2). Backend: api_convertidor.py
const conv = {
  montar(el){
    el.innerHTML = `
    <div style="display:grid;grid-template-columns:1fr 230px;grid-template-rows:auto 1fr auto auto;gap:10px;height:100%">
      <div class="fila" style="grid-column:1/3">
        <h2 style="margin:0 12px 0 0;font-size:15px">🏦 Convertidor de Estados de Cuenta</h2>
        <span class="estado">Convierte los PDF del banco a Excel con saldos y clasificación de movimientos</span>
        <span class="espacio"></span>
        <button class="primario" onclick="conv.agregar()">📂 Agregar PDFs</button>
        <button onclick="conv.limpiar()">Limpiar lista</button>
        <button onclick="conv.eliminar()">Quitar seleccionados</button>
        <button id="cBtnConv" class="primario" style="background:var(--success);border-color:var(--success)" onclick="conv.convertir(false)">▶ CONVERTIR A EXCEL</button>
      </div>
      <section class="card" style="padding:0;overflow:hidden">
        <div class="tabla"><table id="cTabla"><thead><tr><th style="width:28px"></th><th>Archivo</th><th>Banco</th><th>Estado</th><th class="n">Movs</th></tr></thead>
          <tbody></tbody></table></div>
      </section>
      <section class="card">
        <button onclick="comun.empresas()">🏢 Empresas / RFC</button>
        <button onclick="comun.bitacora()">📋 Bitácora</button>
        <button onclick="conv.reimportar()">📥 Reimportar Excel (actualizar)</button>
        <hr style="border:0;border-top:1px solid var(--border);width:100%">
        <span class="estado">Carpeta de salida:</span>
        <div id="cOut" class="estado" style="word-break:break-all;background:var(--bg);padding:6px;border-radius:6px">(misma carpeta del PDF)</div>
        <button onclick="conv.salida()">📂 Elegir carpeta salida</button>
        <button onclick="conv.resetSalida()">↺ Restablecer carpeta</button>
        <hr style="border:0;border-top:1px solid var(--border);width:100%">
        <label><input id="cAbrir" type="checkbox" checked> Abrir Excel al terminar</label>
      </section>
      <div style="grid-column:1/3" class="fila"><div class="barra-prog" style="flex:1"><div id="cBarra"></div></div>
        <span id="cEstado" class="estado">Listo</span></div>
      <div style="grid-column:1/3">
        <div class="estado">Registro de conversión:</div>
        <pre id="cLog" style="margin:3px 0 0;height:120px;overflow:auto;background:#1A1A19;color:#C3C2B7;border-radius:8px;padding:8px;font:12px Consolas,monospace"></pre>
      </div>
    </div>`;
    pywebview.api.conv_lista().then(r => { conv.lista(r.archivos); conv.pintarOut(r.outdir); });
  },
  COLOR: {ok: ["var(--success-bg)", "var(--success)"], error: ["var(--danger-bg)", "var(--danger)"],
          procesando: ["var(--warn-bg)", "var(--warn)"]},
  lista(archivos){
    $("cTabla").tBodies[0].innerHTML = archivos.map((a, i) => {
      const [bg, fg] = conv.COLOR[a.estado] || ["", ""];
      return `<tr style="background:${bg};color:${fg}" title="${esc(a.mensaje)}"><td><input type="checkbox" data-i="${i}"></td>
        <td>${esc(a.nombre)}</td><td>${esc(a.banco)}</td><td>${esc(a.estado_txt)}</td><td class="n">${a.movs}</td></tr>`;
    }).join("") || '<tr><td colspan="5" class="vacio">Agrega estados de cuenta en PDF.</td></tr>';
  },
  pintarOut(d){ $("cOut").textContent = d || "(misma carpeta del PDF)"; },
  async agregar(){ conv.lista(await pywebview.api.conv_agregar()); },
  async limpiar(){ conv.lista(await pywebview.api.conv_limpiar()); },
  async eliminar(){
    const idx = [...document.querySelectorAll("#cTabla input[data-i]:checked")].map(c => +c.dataset.i);
    if (idx.length) conv.lista(await pywebview.api.conv_eliminar(idx));
  },
  async salida(){ conv.pintarOut(await pywebview.api.conv_elegir_salida()); },
  async resetSalida(){ conv.pintarOut(await pywebview.api.conv_reset_salida()); },
  async convertir(reconvertir){
    const r = await pywebview.api.conv_convertir(reconvertir);
    if (r.confirmar){ if (confirm(r.msg)) conv.convertir(true); return; }
    if (!r.ok){ alert(r.msg); return; }
    window.__listo = false; window.__maxGap = 0; window.__midiendo = true;
    $("cBtnConv").disabled = true; $("cBtnConv").textContent = "⏳ Procesando…";
    $("cBarra").style.width = "0"; $("cEstado").textContent = "Procesando…";
  },
  log(msg, tag){
    const col = {ok: "#4ADE80", err: "#F87171", info: "#60A5FA", bank: "#FACC15", warn: "#FB923C"}[tag] || "";
    const t = new Date().toLocaleTimeString("es-MX", {hour12: false});
    $("cLog").insertAdjacentHTML("beforeend", `<span style="color:${col}">[${t}] ${esc(msg)}</span>\n`);
    $("cLog").scrollTop = $("cLog").scrollHeight;
  },
  progreso(pct, txt){ $("cBarra").style.width = pct + "%"; $("cEstado").textContent = txt; },
  fin(r){
    window.__midiendo = false; window.__listo = true; conv._fin = r;
    $("cBtnConv").disabled = false; $("cBtnConv").textContent = "▶ CONVERTIR A EXCEL";
    $("cBarra").style.width = "100%"; $("cEstado").textContent = "Completado";
    if (window.__prueba) return;          // prueba automática: sin ventanas ni abrir Excel
    let msg = `Conversión finalizada.\n${r.ok} archivo(s) generados.`;
    if (r.err) msg += `\n${r.err} con error (ver registro).`;
    alert(msg);
    if (r.outputs.length && $("cAbrir").checked) pywebview.api.conv_abrir(r.outputs[r.outputs.length - 1]);
    if (r.nuevos.length && confirm(`Se convirtieron ${r.nuevos.length} estado(s) de cuenta con el extractor GENÉRICO (best-effort).\n\n¿Quieres GENERAR el parser específico para ese banco (para mejorar la extracción)?`))
      conv.parserSiguiente(r.nuevos.slice());
  },
  async parserSiguiente(cola){
    const pdf = cola.shift(); if (!pdf) return;
    const r = await pywebview.api.conv_parser_analizar(pdf);
    if (!r.ok){ alert(r.msg); return conv.parserSiguiente(cola); }
    modal.abrir(`<h3>Confirma los datos del banco nuevo</h3><div class="estado">PDF: ${esc(r.pdf)}</div>
      <label class="campo">Nombre del banco: <input id="pbN" value="${esc(r.info.nombre)}"></label>
      <label class="campo">Palabra clave (detectar) — aparece en el encabezado <input id="pbK" value="${esc(r.info.keyword)}"></label>
      <label class="campo">Formato de fecha (regex) — auto-detectado <input id="pbD" value="${esc(r.info.date_src)}" style="font-family:Consolas,monospace"></label>
      <div id="pbM" class="msg"></div>
      <div class="fila"><button class="primario" id="pbOk">✔ Generar parser</button><button id="pbNo">Cancelar</button></div>`);
    $("pbNo").onclick = () => { modal.cerrar(); conv.parserSiguiente(cola); };
    $("pbOk").onclick = async () => {
      const c = await pywebview.api.conv_parser_crear(pdf, {nombre: $("pbN").value.trim(), keyword: $("pbK").value.trim(), date_src: $("pbD").value.trim()});
      if (!c.ok){ $("pbM").textContent = c.msg; return; }
      modal.cerrar();
      alert(`Se creó:\n${c.ruta}\n\nEl banco '${c.nombre}' quedará reconocido al reiniciar la app. Puedes afinar el archivo si algún movimiento no sale bien (ver bancos/banbajio.py como ejemplo).`);
      conv.parserSiguiente(cola);
    };
  },
  async reimportar(){
    const r = await pywebview.api.conv_reimportar();
    if (r.cancelado) return;
    if (!r.ok){ alert("Error al reimportar:\n" + r.msg); return; }
    const st = r.st;
    let extra = "";
    if (st.conflictos) extra = `\nConflictos detectados: ${st.conflictos}  (descartados: ${st.descartados || 0})\nCada conflicto quedó en la bitácora de auditoría.`;
    alert(`Filas leídas: ${st.leidos || 0}\nActualizadas (cambiaron): ${st.actualizados || 0}\nNuevas (insertadas): ${st.nuevos || 0}\nSin cambios: ${st.sin_cambio || 0}${extra}\n\nSolo se actualizó en la base lo que modificaste.`);
  },
};
app.modulos.conv = conv;
