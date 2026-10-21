// Módulo Saldos a favor ISR/IVA (5.2). Backend: api_saldos.py
const saldos = {
  montar(el){
    el.innerHTML = `
    <div style="display:grid;grid-template-columns:330px 1fr;gap:12px;height:100%">
      <section class="card">
        <h2>Declaraciones</h2>
        <div class="fila">
          <button onclick="saldos.carpetas()">＋ Carpeta</button>
          <button onclick="saldos.archivos()">＋ PDF / ZIP</button>
          <button onclick="saldos.limpiar()">Limpiar</button>
        </div>
        <ul id="sRutas" class="lista" style="flex:1"><li class="vacio">Sin carpetas ni archivos.</li></ul>
        <button id="sBtnAnalizar" class="primario" onclick="saldos.analizar()">ANALIZAR</button>
        <div class="barra-prog"><div id="sBarra"></div></div>
        <div id="sEstado" class="estado"></div>
        <label class="campo">RFC <select id="sRfc" onchange="saldos.recalcular()" disabled></select></label>
        <label class="campo">Saldo a favor inicial IVA (opcional)
          <input id="sIni" inputmode="decimal" placeholder="0.00" onchange="saldos.recalcular()"></label>
        <button id="sBtnExcel" onclick="saldos.excel()" disabled>Generar Excel</button>
      </section>
      <section class="card">
        <div id="sResumen" style="white-space:pre-line">Agrega declaraciones y pulsa ANALIZAR.</div>
        <div class="tabs">
          <button class="tab activa" data-t="iva" onclick="saldos.tab(this)">IVA acumulado</button>
          <button class="tab" data-t="pag" onclick="saldos.tab(this)">Pagos</button>
          <button class="tab" data-t="isr" onclick="saldos.tab(this)">ISR acumulado</button>
        </div>
        <div class="tabla" id="sT-iva"><table id="sTablaIva"><thead><tr>
          <th>Periodo</th><th>No. operación</th><th>Fecha present.</th><th class="n">IVA a cargo</th>
          <th class="n">Saldo a favor gen.</th><th class="n">Acreditado (ant.)</th>
          <th class="n">Remanente acumulado</th><th>Lectura</th><th></th></tr></thead><tbody></tbody></table></div>
        <div class="tabla oculto" id="sT-pag"><table id="sTablaPag"><thead><tr>
          <th>Periodo</th><th>Tipo</th><th>No. operación</th><th>Vence</th><th class="n">Contribución</th>
          <th class="n">Actualiz.</th><th class="n">Recargos</th><th class="n">A pagar</th>
          <th class="n">Pagado</th><th>Fecha pago</th><th>Estatus</th></tr></thead><tbody></tbody></table></div>
        <div class="tabla oculto" id="sT-isr"><table id="sTablaIsr"><thead><tr>
          <th>Periodo</th><th>No. operación</th><th>Fecha present.</th><th class="n">Ingresos</th>
          <th class="n">Utilidad fiscal</th><th class="n">Pérdidas aplic.</th><th class="n">ISR causado</th>
          <th class="n">Pagos prov. ant.</th><th class="n">ISR retenido</th><th class="n">Compensaciones</th>
          <th class="n">ISR a cargo</th><th class="n">Saldo a favor</th><th>Régimen</th></tr></thead><tbody></tbody></table></div>
        <div id="sNota" class="msg"></div>
      </section>
    </div>`;
  },
  pintarRutas(r){
    $("sRutas").innerHTML = r.length ? r.map(x => `<li>${esc(x)}</li>`).join("")
                                     : '<li class="vacio">Sin carpetas ni archivos.</li>';
  },
  async carpetas(){ saldos.pintarRutas(await pywebview.api.saldos_carpetas()); },
  async archivos(){ saldos.pintarRutas(await pywebview.api.saldos_archivos()); },
  async limpiar(){
    saldos.pintarRutas(await pywebview.api.saldos_limpiar());
    $("sTablaIva").tBodies[0].innerHTML = ""; $("sTablaPag").tBodies[0].innerHTML = "";
    $("sTablaIsr").tBodies[0].innerHTML = "";
    $("sResumen").textContent = "Agrega declaraciones y pulsa ANALIZAR."; $("sNota").textContent = "";
    $("sRfc").innerHTML = ""; $("sRfc").disabled = true; $("sBtnExcel").disabled = true;
  },
  async analizar(){
    window.__listo = false; window.__maxGap = 0; window.__midiendo = true;
    $("sBarra").style.width = "0"; $("sEstado").textContent = "Leyendo PDFs…";
    const r = await pywebview.api.saldos_analizar();
    if (!r.ok){ $("sEstado").textContent = r.msg; window.__midiendo = false; return; }
    $("sBtnAnalizar").disabled = true;
  },
  progreso(i, n, nom){
    $("sBarra").style.width = (100 * i / Math.max(n, 1)) + "%";
    $("sEstado").textContent = `Leyendo ${nom} (${i}/${n})`;
  },
  cargado(c){
    $("sBtnAnalizar").disabled = false; window.__midiendo = false;
    $("sEstado").textContent = `${c.pdfs} PDF · ${c.acuses} acuses · ${c.detalles} detalles IVA · ` +
      `${c.pagos} pagos · ${c.rfcs.length} RFC · ${c.segundos} s` +
      (c.no_legibles.length ? ` · ${c.no_legibles.length} no legibles` : "");
    $("sRfc").innerHTML = c.rfcs.map(r => `<option>${esc(r)}</option>`).join("");
    $("sRfc").disabled = !c.rfcs.length;
    if (!c.rfcs.length){ saldos.error("No se leyó ningún acuse/declaración/pago legible (¿PDF escaneados sin texto?)."); }
  },
  async recalcular(){
    const r = await pywebview.api.saldos_calcular($("sRfc").value, $("sIni").value);
    if (r.ok) saldos.resultado(r); else $("sEstado").textContent = r.msg;
  },
  resultado(d){
    $("sRfc").value = d.rfc;
    const nrev = (d.filas || []).filter(f => f.revisar).length;

    const ivaResumen = [
      "IVA",
      `- Generado: ${dinero(d.iva.generado)}`,
      `- Acreditado: ${dinero(d.iva.acreditado)}`,
      `- Neto: ${dinero(d.iva.neto)}`,
      `- Remanente al cierre: ${dinero(d.iva.cierre)}`,
    ].join("\n");

    const isrResumen = [
      "ISR",
      `- Remanente total: ${dinero(d.remanente_isr)}`,
      `- Pagos provisionales acumulados: ${dinero(d.isr?.total_pagos_prov ?? 0)}`,
      `- Declaraciones ISR: ${(d.filas_isr || []).length}`,
    ].join("\n");

    let txt = [
      `${d.rfc} — ${d.razon}`,
      `${d.regimen}`,
      `Periodos vigentes: ${d.vigentes}`,
      "",
      ivaResumen,
      "",
      isrResumen,
    ].join("\n");

    if (nrev) txt += `\n\n⚠ ${nrev} declaración(es) por revisar: la identidad fiscal no cuadró al leerlas (renglón en rojo).`;
    $("sResumen").textContent = txt;

    const notas = [];
    if (d.iva && d.iva.nota) notas.push(`IVA: ${d.iva.nota}`);
    if (d.isr && d.isr.nota) notas.push(`ISR: ${d.isr.nota}`);
    $("sNota").textContent = notas.join("\n\n");

    saldos._md = (d.filas || []).map(f => f.md);
    $("sTablaIva").tBodies[0].innerHTML = (d.filas || []).map((f, i) => `
      <tr class="${f.revisar ? "revisar" : ""}"><td>${esc(f.periodo)}</td><td>${esc(f.operacion)}</td>
      <td>${esc(f.fecha)}</td><td class="n">${dinero(f.cargo)}</td><td class="n">${dinero(f.generado)}</td>
      <td class="n">${dinero(f.acreditado)}</td><td class="n">${dinero(f.remanente)}</td>
      <td>${f.revisar ? "⚠ revisar" : esc(f.regimen || "—")}</td>
      <td>${f.md ? `<button class="fantasma" title="Abrir el MD de esta declaración" onclick="pywebview.api.saldos_ver_md(saldos._md[${i}])">Ver MD</button>` : ""}</td></tr>`).join("");
    $("sTablaPag").tBodies[0].innerHTML = (d.pagos || []).map(p => `
      <tr><td>${esc(p.periodo)}</td><td>${esc(p.tipo)}</td><td>${esc(p.operacion)}</td><td>${esc(p.venc)}</td>
      <td class="n">${dinero(p.contrib)}</td><td class="n">${dinero(p.actualiz)}</td><td class="n">${dinero(p.recargos)}</td>
      <td class="n">${dinero(p.importe)}</td><td class="n">${dinero(p.pagado)}</td><td>${esc(p.fecha_pago)}</td>
      <td class="${p.ok ? "ok" : "no"}">${p.ok ? "✓ Pagado" : "⚠ Sin comprobante"}</td></tr>`).join("");
    document.querySelector('#m-saldos [data-t="pag"]').textContent =
      (d.pagos || []).length ? `Pagos (${(d.pagos || []).filter(p => p.ok).length}/${(d.pagos || []).length})` : "Pagos";
    $("sTablaIsr").tBodies[0].innerHTML = (d.filas_isr || []).map(f => `
      <tr class="${f.es_anual ? "anual" : ""}"><td>${esc(f.periodo)}</td><td>${esc(f.operacion)}</td>
      <td>${esc(f.fecha)}</td><td class="n">${dinero(f.ingresos)}</td><td class="n">${dinero(f.utilidad)}</td>
      <td class="n">${dinero(f.perdidas)}</td><td class="n">${dinero(f.causado)}</td>
      <td class="n">${dinero(f.pagos_prov)}</td><td class="n">${dinero(f.retenido)}</td>
      <td class="n">${dinero(f.compensado)}</td><td class="n">${dinero(f.cargo)}</td>
      <td class="n">${dinero(f.favor)}</td><td>${esc(f.regimen)}</td></tr>`).join("");
    const nIsr = (d.filas_isr || []).length;
    document.querySelector('#m-saldos [data-t="isr"]').textContent =
      nIsr ? `ISR acumulado (${nIsr})` : "ISR acumulado";
    $("sBtnExcel").disabled = false; window.__listo = true;
  },
  async excel(){
    const r = await pywebview.api.saldos_excel($("sIni").value);
    $("sEstado").textContent = r.ok ? `Excel guardado: ${r.ruta}` : r.msg;
  },
  error(msg){ $("sBtnAnalizar").disabled = false; window.__midiendo = false; window.__listo = true;
    $("sEstado").textContent = "Error"; $("sNota").textContent = msg; },
  tab(b){ document.querySelectorAll("#m-saldos .tab").forEach(x => x.classList.toggle("activa", x === b));
    $("sT-iva").classList.toggle("oculto", b.dataset.t !== "iva");
    $("sT-pag").classList.toggle("oculto", b.dataset.t !== "pag");
    $("sT-isr").classList.toggle("oculto", b.dataset.t !== "isr"); },
};
app.modulos.saldos = saldos;
