// Módulo Configuración (5.2). Backend: api_config.py
const config = {
  montar(el){
    el.innerHTML = `
    <section class="card" style="height:100%">
      <div class="tabs">
        <button class="tab activa" data-t="email" onclick="config.tab(this)">📧 Email multi-proveedor</button>
        <button class="tab" data-t="usr" onclick="config.tab(this)">👤 Usuarios</button>
        <button class="tab" data-t="db" onclick="config.tab(this)">🗄 Base de datos</button>
        <button class="tab" data-t="kw" onclick="config.tab(this)">🔑 Palabras clave</button>
      </div>
      <div style="overflow:auto;flex:1;min-height:0">
        <div id="cfg-email"></div>
        <div id="cfg-usr" class="oculto"></div>
        <div id="cfg-db" class="oculto"></div>
        <div id="cfg-kw" class="oculto"></div>
      </div>
    </section>`;
    config.email.montar(); config.usr.montar(); config.db.montar(); config.kw.montar();
  },
  tab(b){
    document.querySelectorAll("#m-config .tab").forEach(x => x.classList.toggle("activa", x === b));
    ["email", "usr", "db", "kw"].forEach(t => $("cfg-" + t).classList.toggle("oculto", b.dataset.t !== t));
  },

  // ── Correo ────────────────────────────────────────────────────────────────
  email: {
    PROV: {gmail: ["#EA4335", "Gmail"], outlook: ["#0078D4", "Outlook / Hotmail"],
           yahoo: ["#6001D2", "Yahoo Mail"], smtp: ["#374151", "SMTP Custom"]},
    async montar(){
      const r = await pywebview.api.cfg_email_cargar(), c = r.cfg;
      $("cfg-email").innerHTML = `
        <h3 style="margin:12px 0 6px">Configuración de correo saliente</h3>
        <div class="fila" id="eProv">${Object.entries(config.email.PROV).map(([k, [col, lb]]) =>
          `<button data-p="${k}" data-c="${col}" onclick="config.email.proveedor('${k}')" style="min-width:150px">${lb}</button>`).join("")}</div>
        <div id="eNota" class="estado" style="background:#EFF6FF;color:#1E40AF;padding:8px 12px;border-radius:8px;margin:10px 0"></div>
        <div style="display:grid;grid-template-columns:180px 1fr;gap:8px 12px;max-width:720px;align-items:center">
          <span>Correo remitente:</span><input id="eRem" value="${esc(c.remitente)}" oninput="config.email.detectar()">
          <span>Contraseña / App pwd:</span><div class="fila"><input id="ePwd" type="password" value="${esc(c.password)}" style="flex:1">
            <button class="fantasma" onclick="ePwd.type = ePwd.type === 'password' ? 'text' : 'password'">👁</button></div>
          <span>Host SMTP:</span><input id="eHost" value="${esc(c.host_smtp)}">
          <span>Puerto:</span><input id="ePuerto" value="${esc(c.puerto)}" style="width:100px">
          <span></span><label><input id="eSsl" type="checkbox" ${c.ssl ? "checked" : ""}> Usar SSL directo (puerto 465) en lugar de STARTTLS (587)</label>
        </div>
        <div class="fila" style="margin-top:12px"><button class="primario" onclick="config.email.guardar()">💾 Guardar</button>
          <button onclick="config.email.probar()">🧪 Probar conexión</button><span id="eMsg" class="estado"></span></div>`;
      config.email.marcar(c.proveedor || "gmail");
      config.email.nota(c.proveedor || "gmail");
    },
    marcar(p){
      config.email.actual = p;
      document.querySelectorAll("#eProv button").forEach(b => {
        const sel = b.dataset.p === p;
        b.style.background = sel ? b.dataset.c : ""; b.style.color = sel ? "#fff" : ""; b.style.borderColor = sel ? b.dataset.c : "";
      });
    },
    async nota(p){ const r = await pywebview.api.cfg_email_proveedor(p); $("eNota").textContent = r.nota || ""; return r; },
    async proveedor(p){
      config.email.marcar(p);
      const r = await config.email.nota(p);
      if (r.host_smtp){ $("eHost").value = r.host_smtp; $("ePuerto").value = r.puerto; $("eSsl").checked = !!r.ssl; }
    },
    async detectar(){
      const p = await pywebview.api.cfg_email_detectar($("eRem").value);
      if (p !== "smtp" && p !== config.email.actual) config.email.proveedor(p);
    },
    datos(){ return {proveedor: config.email.actual, remitente: $("eRem").value, password: $("ePwd").value,
                     host_smtp: $("eHost").value, puerto: $("ePuerto").value, ssl: $("eSsl").checked}; },
    async guardar(){ const r = await pywebview.api.cfg_email_guardar(config.email.datos());
      $("eMsg").className = "estado ok"; $("eMsg").textContent = r.msg; },
    async probar(){ $("eMsg").className = "estado"; $("eMsg").textContent = "⏳ Probando…";
      const r = await pywebview.api.cfg_email_probar(config.email.datos());
      $("eMsg").className = r.ok ? "estado ok" : "msg"; $("eMsg").textContent = (r.msg || "").split("\n")[0]; },
  },

  // ── Usuarios ──────────────────────────────────────────────────────────────
  usr: {
    async montar(){
      $("cfg-usr").innerHTML = `
        <h3 style="margin:12px 0 6px">Gestión de usuarios</h3>
        <div style="max-width:520px;display:flex;flex-direction:column;gap:8px">
          <span class="estado">Usuarios registrados:</span>
          <select id="uLista" size="6" style="font-family:Consolas,monospace"></select>
          <div class="fila"><button onclick="config.usr.eliminar()">🗑 Eliminar usuario</button>
            <button class="fantasma" onclick="config.usr.recargar()">🔄 Actualizar lista</button></div>
          <div id="uMsg" class="msg"></div>
          <h3 style="margin:8px 0 0">Crear nuevo usuario</h3>
          <label class="campo">Usuario <input id="uU"></label>
          <label class="campo">Contraseña <input id="uP" type="password"></label>
          <label class="campo">Confirmar <input id="uP2" type="password"></label>
          <div><button class="primario" onclick="config.usr.crear()">➕ Crear usuario</button></div>
        </div>`;
      config.usr.pintar(await pywebview.api.cfg_usuarios());
    },
    pintar(lista){ $("uLista").innerHTML = lista.map(u => `<option value="${esc(u)}">👤  ${esc(u)}</option>`).join(""); },
    async recargar(){ config.usr.pintar(await pywebview.api.cfg_usuarios()); },
    async eliminar(){
      const u = $("uLista").value; if (!u) return;
      const r = await pywebview.api.cfg_usuario_eliminar(u);
      $("uMsg").className = r.ok ? "msg ok" : "msg"; $("uMsg").textContent = r.ok ? `Usuario ${u} eliminado.` : r.msg;
      if (r.ok) config.usr.pintar(r.usuarios);
    },
    async crear(){
      const r = await pywebview.api.cfg_usuario_crear($("uU").value, $("uP").value, $("uP2").value);
      if (!r.ok){ $("uMsg").className = "msg"; $("uMsg").textContent = r.msg; return; }
      config.usr.pintar(r.usuarios); ["uU", "uP", "uP2"].forEach(i => $(i).value = ""); $("uMsg").textContent = "";
      modal.abrir(`<h3>Usuario creado</h3><div class="estado">Código de recuperación (solo se muestra una vez):</div>
        <div class="codigo">${esc(r.codigo)}</div>
        <div class="fila" style="justify-content:flex-end"><button class="primario" onclick="modal.cerrar()">Entendido, ya lo guardé</button></div>`);
    },
  },

  // ── Base de datos ─────────────────────────────────────────────────────────
  db: {
    CAMPOS: [["host", "Servidor (host):", "localhost si es local"], ["port", "Puerto:", "3050 (default de Firebird)"],
             ["database", "Ruta de la BD (.fdb):", ""], ["user", "Usuario:", "SYSDBA por defecto"],
             ["password", "Contraseña:", ""], ["charset", "Charset:", "UTF8"],
             ["fbclient", "fbclient.dll:", "vacío = autodetección (64-bit)"]],
    async montar(){
      const c = await pywebview.api.cfg_db_cargar();
      $("cfg-db").innerHTML = `
        <h3 style="margin:12px 0 2px">Conexión a la base de datos (Firebird)</h3>
        <div class="estado">La base guarda la conciliación y sus CFDI (para reimportar y generar pólizas).</div>
        <div style="display:grid;grid-template-columns:170px 1fr auto;gap:8px 12px;max-width:820px;align-items:center;margin-top:10px">
        ${config.db.CAMPOS.map(([k, lb, hint]) => `<span>${lb}</span>
          <input id="db_${k}" ${k === "password" ? 'type="password"' : ""} value="${esc(c[k] ?? "")}">
          <span class="estado">${k === "database" ? '<button class="fantasma" onclick="config.db.buscar(\'fdb\')">📂</button>'
            : k === "fbclient" ? '<button class="fantasma" onclick="config.db.buscar(\'dll\')">📂</button> ' + hint
            : k === "password" ? '<button class="fantasma" onclick="db_password.type = db_password.type === \'password\' ? \'text\' : \'password\'">👁</button>'
            : hint}</span>`).join("")}
        </div>
        <div class="fila" style="margin-top:12px"><button onclick="config.db.probar()">🔌 Probar conexión</button>
          <button class="primario" onclick="config.db.guardar()">💾 Guardar configuración</button><span id="dbMsg" class="estado"></span></div>
        <div class="estado" style="margin-top:8px">Nota: si Firebird no está instalado o el servicio no corre, la conciliación funciona igual pero SIN guardar en la BD (no habrá IDs ni reimportación).</div>`;
    },
    datos(){ const d = {}; config.db.CAMPOS.forEach(([k]) => d[k] = $("db_" + k).value); return d; },
    async buscar(t){
      const r = t === "fdb" ? await pywebview.api.cfg_db_buscar_fdb() : await pywebview.api.cfg_db_buscar_fbclient();
      if (r) $(t === "fdb" ? "db_database" : "db_fbclient").value = r;
    },
    async probar(){ $("dbMsg").className = "estado"; $("dbMsg").textContent = "Probando…";
      const r = await pywebview.api.cfg_db_probar(config.db.datos());
      $("dbMsg").className = r.ok ? "estado ok" : "msg"; $("dbMsg").textContent = (r.ok ? "✔ Conectado — " : "✕ ") + r.msg; },
    async guardar(){ const r = await pywebview.api.cfg_db_guardar(config.db.datos());
      $("dbMsg").className = r.ok ? "estado ok" : "msg"; $("dbMsg").textContent = (r.ok ? "✔ Guardado. " : "✕ ") + r.msg; },
  },

  // ── Palabras clave + emisores bancarios ───────────────────────────────────
  kw: {
    async montar(){
      const r = await pywebview.api.cfg_kw_cargar();
      config.kw.emisores = r.emisores.map(e => ({nombre: e.nombre || "", rfc: e.rfc || ""}));
      $("cfg-kw").innerHTML = `
        <h3 style="margin:12px 0 2px">Palabras clave del usuario</h3>
        <div class="estado">Agrega palabras clave (una por línea) que el conciliador no tiene en su código. Se aplican automáticamente.</div>
        ${r.categorias.map(c => `<div style="margin-top:10px;max-width:820px"><div style="font-weight:600;margin-bottom:4px">${esc(c.desc)}</div>
          <textarea data-cat="${esc(c.id)}" rows="5" style="width:100%;font:inherit;padding:8px;border:1px solid var(--border);border-radius:8px">${esc(c.kws.join("\n"))}</textarea></div>`).join("")}
        <div class="fila" style="margin-top:8px"><button class="primario" onclick="config.kw.guardar()">💾 Guardar todas las palabras clave</button><span id="kwMsg" class="estado"></span></div>
        <h3 style="margin:18px 0 2px">Emisores bancarios (instituciones financieras)</h3>
        <div class="estado">Instituciones cuyos CFDIs se cruzan con comisiones bancarias. Se aplican automáticamente.</div>
        <div class="tabla" style="max-width:820px;max-height:220px;border:1px solid var(--border);border-radius:8px;margin-top:6px">
          <table><thead><tr><th>Nombre de la institución</th><th>RFC</th><th></th></tr></thead><tbody id="emBody"></tbody></table></div>
        <div class="fila" style="margin-top:6px">Nombre: <input id="emN" style="width:300px"> RFC: <input id="emR" style="width:150px">
          <button onclick="config.kw.agregar()">➕ Agregar</button></div>
        <div class="fila" style="margin-top:6px"><button class="primario" onclick="config.kw.guardarEmisores()">💾 Guardar emisores</button><span id="emMsg" class="estado"></span></div>`;
      config.kw.pintarEmisores();
    },
    pintarEmisores(){
      $("emBody").innerHTML = config.kw.emisores.map((e, i) =>
        `<tr><td>${esc(e.nombre)}</td><td>${esc(e.rfc)}</td><td><button class="fantasma" onclick="config.kw.quitar(${i})">🗑</button></td></tr>`).join("");
    },
    agregar(){
      const n = $("emN").value.trim(), r = $("emR").value.trim().toUpperCase();
      if (!n && !r) return;
      config.kw.emisores.push({nombre: n, rfc: r}); $("emN").value = ""; $("emR").value = ""; config.kw.pintarEmisores();
    },
    quitar(i){ config.kw.emisores.splice(i, 1); config.kw.pintarEmisores(); },
    async guardar(){
      const d = {}; document.querySelectorAll("#cfg-kw textarea[data-cat]").forEach(t => d[t.dataset.cat] = t.value);
      const r = await pywebview.api.cfg_kw_guardar(d); $("kwMsg").className = "estado ok"; $("kwMsg").textContent = r.msg;
    },
    async guardarEmisores(){
      const r = await pywebview.api.cfg_emisores_guardar(config.kw.emisores);
      $("emMsg").className = "estado ok"; $("emMsg").textContent = r.msg;
    },
  },
};
app.modulos.config = config;
