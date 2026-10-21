// ConvertidorBancos 5.2 — núcleo de la interfaz: navegación, ventanas emergentes,
// licencia y usuarios. Cada módulo vive en su propio mod_<modulo>.js.
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const dinero = v => "$" + Number(v || 0).toLocaleString("es-MX", {maximumFractionDigits: 0});

window.__errores = [];
window.addEventListener("error", e => window.__errores.push(String(e.message)));
window.addEventListener("unhandledrejection", e => window.__errores.push(String(e.reason)));
// Mide si la ventana se congela mientras corre un proceso (verificación de la 5.2).
window.__maxGap = 0; window.__listo = false;
let __ult = performance.now(); window.__midiendo = false;
setInterval(() => { const t = performance.now();
  if (window.__midiendo) window.__maxGap = Math.max(window.__maxGap, t - __ult - 50); __ult = t; }, 50);

const modal = {
  abrir(html, ancho){ $("ventana").innerHTML = html; $("ventana").style.width = (ancho || 440) + "px"; $("velo").classList.remove("oculto");
    const f = $("ventana").querySelector("input"); if (f) f.focus(); },
  cerrar(){ $("velo").classList.add("oculto"); $("ventana").innerHTML = ""; },
};

const app = {
  modulos: {},                      // id → {montar()} (lo registra cada mod_*.js)
  entrar(usuario){
    ["pActivacion", "pLogin"].forEach(id => $(id).classList.add("oculto"));
    $("pApp").classList.remove("oculto");
    $("pillUser").textContent = `👤 ${usuario}  ·  Cambiar contraseña`;
    auth.refrescarPill();
    app.ir("saldos");
  },
  ir(id){
    document.querySelectorAll("nav.menu button").forEach(b => b.classList.toggle("activo", b.dataset.m === id));
    document.querySelectorAll(".modulo").forEach(s => s.classList.toggle("oculto", s.id !== "m-" + id));
    const m = app.modulos[id];
    if (m && !m.montado){ m.montar($("m-" + id)); m.montado = true; }
  },
};

// Formato del serial: XXXXXX-XXXXXX-XXXXXX-XXXXXX (igual que la 5.0).
function formatoSerial(inp, btn){
  const raw = inp.value.replace(/[-\s]/g, "").toUpperCase().slice(0, 24);
  const fmt = (raw.match(/.{1,6}/g) || []).join("-");
  if (inp.value !== fmt) inp.value = fmt;
  if (btn) btn.disabled = raw.length !== 24;
}

const auth = {
  primer: false,
  async iniciar(){
    const e = await pywebview.api.auth_estado();
    auth.primer = e.primer_usuario;
    if (e.requiere_activacion){
      $("actTexto").textContent = `Tu periodo de prueba de ${e.trial_days} días terminó.\nActiva la licencia para seguir usando la aplicación.`;
      $("actSerial").oninput = () => formatoSerial($("actSerial"), $("actBtn"));
      $("pActivacion").classList.remove("oculto");
      return;
    }
    auth.mostrarLogin();
  },
  mostrarLogin(){
    $("pActivacion").classList.add("oculto");
    $("loginTitulo").textContent = auth.primer ? "Crear primer usuario" : "Iniciar sesión";
    $("loginBtn").textContent = auth.primer ? "Crear usuario" : "Entrar";
    $("loginPwd2Box").classList.toggle("oculto", !auth.primer);
    $("loginOlvido").classList.toggle("oculto", auth.primer);
    $("pLogin").classList.remove("oculto");
    $("loginUser").focus();
  },
  async entrar(ev){
    ev.preventDefault();
    const u = $("loginUser").value.trim(), p = $("loginPwd").value;
    if (auth.primer){
      const r = await pywebview.api.auth_crear(u, p, $("loginPwd2").value);
      if (!r.ok){ $("loginMsg").textContent = r.msg; return; }
      modal.abrir(`<h3>Guarda este código de recuperación</h3>
        <div class="estado">Usuario: ${esc(r.usuario)}</div><div class="codigo">${esc(r.codigo)}</div>
        <div class="estado">Úsalo en Login → "¿Olvidaste tu contraseña?". Este código solo se muestra UNA vez.</div>
        <div class="fila" style="justify-content:flex-end"><button class="primario" onclick="modal.cerrar(); app.entrar('${esc(r.usuario)}')">Entendido, ya lo guardé</button></div>`);
      return;
    }
    const r = await pywebview.api.auth_login(u, p);
    if (r.ok) app.entrar(r.usuario); else $("loginMsg").textContent = r.msg;
  },
  abrirRecuperar(){
    modal.abrir(`<h3>Recuperar contraseña</h3>
      <label class="campo">Usuario <input id="rU"></label>
      <label class="campo">Código de recuperación (XXXX-XXXX-XXXX) <input id="rC"></label>
      <label class="campo">Nueva contraseña <input id="rP" type="password"></label>
      <div id="rM" class="msg"></div>
      <div class="fila" style="justify-content:flex-end"><button onclick="modal.cerrar()">Cancelar</button>
      <button class="primario" onclick="auth.recuperar()">Restablecer</button></div>`);
  },
  async recuperar(){
    const r = await pywebview.api.auth_recuperar($("rU").value, $("rC").value, $("rP").value);
    if (!r.ok){ $("rM").textContent = r.msg; return; }
    modal.abrir(`<h3>Contraseña restablecida</h3><div class="estado">${esc(r.msg)}</div>
      ${r.nuevo_codigo ? `<div class="estado">Tu NUEVO código de recuperación (guárdalo):</div><div class="codigo">${esc(r.nuevo_codigo)}</div>` : ""}
      <div class="fila" style="justify-content:flex-end"><button class="primario" onclick="modal.cerrar()">Entendido</button></div>`);
  },
  abrirCambiarPwd(){
    modal.abrir(`<h3>Cambiar contraseña</h3>
      <label class="campo">Contraseña actual <input id="cA" type="password"></label>
      <label class="campo">Nueva contraseña <input id="cN" type="password"></label>
      <label class="campo">Confirmar nueva <input id="cC" type="password"></label>
      <div id="cM" class="msg"></div>
      <div class="fila" style="justify-content:flex-end"><button onclick="modal.cerrar()">Cancelar</button>
      <button class="primario" onclick="auth.cambiarPwd()">Cambiar</button></div>`);
  },
  async cambiarPwd(){
    const r = await pywebview.api.auth_cambiar($("cA").value, $("cN").value, $("cC").value);
    if (r.ok){ modal.cerrar(); } else $("cM").textContent = r.msg;
  },
  async refrescarPill(){ $("pillLic").textContent = await pywebview.api.lic_texto(); },
  async abrirLicencia(){
    const e = await pywebview.api.lic_estado_detalle();
    modal.abrir(`<h3>Activar licencia</h3>
      <div class="estado" style="color:${e.activado ? "var(--success)" : "var(--muted)"};font-weight:600">${esc(e.texto)}</div>
      <label class="campo">Ingresa tu serial de activación:
        <input id="lSerial" class="serial" placeholder="XXXXXX-XXXXXX-XXXXXX-XXXXXX" oninput="formatoSerial(this, $('lBtn'))"></label>
      <div id="lMsg" class="msg"></div>
      <div class="fila"><span class="estado" style="flex:1">¿No tienes serial? Copia tu código de equipo y envíalo a soporte.</span>
        <button onclick="auth.copiarCodigo('lMsg')">Copiar código de equipo</button></div>
      <div class="fila" style="justify-content:flex-end"><button onclick="modal.cerrar()">Cerrar</button>
      <button id="lBtn" class="primario" disabled onclick="auth.activar('lSerial','lMsg', false)">Activar</button></div>`);
  },
  async activar(idInput, idMsg, alArrancar){
    const ok = await pywebview.api.lic_activar($(idInput).value);
    const m = $(idMsg);
    if (!ok){ m.className = "msg"; m.textContent = "Serial inválido para este equipo. Verifica e intenta de nuevo.";
      $(idInput).value = ""; return; }
    m.className = "msg ok"; m.textContent = "Activación exitosa. ¡Gracias!";
    setTimeout(() => { if (alArrancar) auth.mostrarLogin(); else { modal.cerrar(); auth.refrescarPill(); } }, 1000);
  },
  async copiarCodigo(idMsg){
    const c = await pywebview.api.lic_codigo_equipo();
    try { await navigator.clipboard.writeText(c); } catch (_) {}
    const m = $(idMsg); m.className = "msg ok"; m.textContent = "Código de equipo copiado al portapapeles.";
  },
  cerrar(){ window.close(); },
};

window.addEventListener("pywebviewready", auth.iniciar);
