"use strict";
const $ = (selector, parent = document) => parent.querySelector(selector);
const devices = new Map();
const held = new Map();
let socket, retry = 1000, timer, active = false;
const layout = ["123A", "456B", "789C", "*0#D"];
const font = {
  " ":[0,0,0,0,0,0,0], "?": [14,17,1,2,4,0,4], "!": [4,4,4,4,4,0,4],
  A:[14,17,17,31,17,17,17], B:[30,17,17,30,17,17,30], C:[14,17,16,16,16,17,14],
  D:[30,17,17,17,17,17,30], E:[31,16,16,30,16,16,31], F:[31,16,16,30,16,16,16],
  G:[14,17,16,23,17,17,15], H:[17,17,17,31,17,17,17], I:[14,4,4,4,4,4,14],
  J:[7,2,2,2,18,18,12], K:[17,18,20,24,20,18,17], L:[16,16,16,16,16,16,31],
  M:[17,27,21,21,17,17,17], N:[17,25,21,19,17,17,17], O:[14,17,17,17,17,17,14],
  P:[30,17,17,30,16,16,16], Q:[14,17,17,17,21,18,13], R:[30,17,17,30,20,18,17],
  S:[15,16,16,14,1,1,30], T:[31,4,4,4,4,4,4], U:[17,17,17,17,17,17,14],
  V:[17,17,17,17,17,10,4], W:[17,17,17,21,21,21,10], X:[17,17,10,4,10,17,17],
  Y:[17,17,10,4,4,4,4], Z:[31,1,2,4,8,16,31],
  a:[0,0,14,1,15,17,15], b:[16,16,22,25,17,17,30], c:[0,0,14,16,16,17,14],
  d:[1,1,13,19,17,17,15], e:[0,0,14,17,31,16,14], f:[6,9,8,28,8,8,8],
  g:[0,15,17,17,15,1,14], h:[16,16,22,25,17,17,17], i:[4,0,12,4,4,4,14],
  j:[2,0,6,2,2,18,12], k:[16,16,18,20,24,20,18], l:[12,4,4,4,4,4,14],
  m:[0,0,26,21,21,17,17], n:[0,0,22,25,17,17,17], o:[0,0,14,17,17,17,14],
  p:[0,0,30,17,30,16,16], q:[0,0,15,17,15,1,1], r:[0,0,22,25,16,16,16],
  s:[0,0,15,16,14,1,30], t:[8,8,28,8,8,9,6], u:[0,0,17,17,17,19,13],
  v:[0,0,17,17,17,10,4], w:[0,0,17,17,21,21,10], x:[0,0,17,10,4,10,17],
  y:[0,0,17,17,15,1,14], z:[0,0,31,2,4,8,31],
  "0":[14,17,19,21,25,17,14], "1":[4,12,4,4,4,4,14], "2":[14,17,1,2,4,8,31],
  "3":[30,1,1,14,1,1,30], "4":[2,6,10,18,31,2,2], "5":[31,16,16,30,1,1,30],
  "6":[6,8,16,30,17,17,14], "7":[31,1,2,4,8,8,8], "8":[14,17,17,14,17,17,14],
  "9":[14,17,17,15,1,2,12], ":":[0,4,4,0,4,4,0], ".":[0,0,0,0,0,12,12],
  "-": [0,0,0,31,0,0,0], "_": [0,0,0,0,0,0,31], "/": [1,2,2,4,8,8,16],
  "*": [0,21,14,31,14,21,0], "#": [10,31,10,10,31,10,0], "+": [0,4,4,31,4,4,0],
  "=": [0,0,31,0,31,0,0], "%": [25,25,2,4,8,19,19], ",": [0,0,0,0,12,12,8],
};
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function sendKey(device, row, col, pressed) {
  if (active && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({cmd: "KEY_EVENT", device, row, col, pressed}));
}
function key(device, row, col, pressed, source) {
  const id = JSON.stringify([device, row, col]);
  const sources = held.get(id) || new Set();
  const before = sources.size > 0;
  if (pressed) sources.add(source); else sources.delete(source);
  if (sources.size) held.set(id, sources); else held.delete(id);
  if (before !== (sources.size > 0)) sendKey(device, row, col, sources.size > 0);
}
function releaseAll() {
  for (const id of held.keys()) sendKey(...JSON.parse(id), false);
  held.clear();
}
function setStatus(text, connected) {
  active = connected;
  $("#status").textContent = text;
  $("#status").dataset.state = connected ? "connected" : "waiting";
  for (const button of document.querySelectorAll(".keypad button")) button.disabled = !connected;
}
function card(device, index) {
  const node = el("article", "card");
  node.dataset.kind = device.type;
  const names = {keypad_4x4: ["ENTRADA / 01", "Teclado matricial", "4 × 4"], lcd_hd44780: ["SALIDA / 02", "Display LCD", "16 × 2"], pwm_rgb: ["SALIDA / 03", "LED RGB", "PWM"]};
  const [label, title, badge] = names[device.type];
  const heading = el("div", "card-heading"), titleBox = el("div");
  titleBox.append(el("p", "card-label", label), el("h2", "", title), el("span", "device-name", `${device.name} · MMIO +0x${device.offset.toString(16).padStart(2, "0")}`));
  heading.append(titleBox, el("span", "badge", badge)); node.append(heading);
  if (device.type === "keypad_4x4") {
    const grid = el("div", "keypad");
    layout.forEach((line, row) => [...line].forEach((char, col) => {
      const button = el("button", "", char);
      button.type = "button"; button.dataset.row = row; button.dataset.col = col;
      button.setAttribute("aria-pressed", "false");
      button.addEventListener("pointerdown", event => { if (event.button !== 0) return; event.preventDefault(); button.focus(); button.setPointerCapture(event.pointerId); key(device.name, row, col, true, `p${event.pointerId}`); });
      for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) button.addEventListener(type, event => key(device.name, row, col, false, `p${event.pointerId}`));
      button.addEventListener("keydown", event => { if ([" ", "Enter"].includes(event.key)) { event.preventDefault(); key(device.name, row, col, true, "button"); } });
      button.addEventListener("keyup", event => { if ([" ", "Enter"].includes(event.key)) { event.preventDefault(); key(device.name, row, col, false, "button"); } });
      button.addEventListener("blur", () => key(device.name, row, col, false, "button"));
      grid.append(button);
    }));
    node.append(grid, el("p", "small", "Mantené una tecla con el mouse o usá 0–9, A–D, * y #. Las filas se activan en alto."));
    const scan = el("div", "scan");
    for (const name of ["Filas", "Columnas"]) { const group = el("span", "", name), bits = el("span", `bits ${name.toLowerCase()}`); for (let i = 0; i < 4; i++) bits.append(el("span", "bit")); group.append(bits); scan.append(group); }
    node.append(scan);
  } else if (device.type === "lcd_hd44780") {
    const shell = el("div", "lcd-shell"), lcd = el("div", "lcd");
    lcd.setAttribute("aria-hidden", "true"); shell.append(lcd);
    const readable = el("span", "lcd-readable sr-only"); readable.setAttribute("role", "img"); readable.setAttribute("aria-label", "LCD apagado");
    node.append(shell, readable);
    const contrast = el("label", "contrast", "Contraste"), input = el("input"); input.type = "range"; input.min = "20"; input.max = "100"; input.value = "100";
    input.setAttribute("aria-label", `Contraste LCD ${index + 1}`); input.addEventListener("input", () => lcd.style.setProperty("--contrast", Number(input.value) / 100)); contrast.append(input); node.append(contrast, el("p", "lcd-status"));
    const details = el("details"); details.append(el("summary", "", "Inspeccionar DDRAM / CGRAM"), el("pre", "memory")); node.append(details);
  } else {
    const body = el("div", "rgb-body"), ledWrap = el("div", "led-wrap"), led = el("div", "led"); led.setAttribute("role", "img"); led.setAttribute("aria-label", "LED RGB apagado"); ledWrap.append(led);
    const channels = el("div", "channels");
    for (const name of ["Rojo", "Verde", "Azul"]) { const channel = el("div", "channel"), label = el("div", "channel-label"), track = el("div", "track"); label.append(el("span", "", name), el("span", "percent", "0 %")); track.append(el("div", "fill")); channel.append(label, track); channels.append(channel); }
    body.append(ledWrap, channels); node.append(body, el("div", "timing"));
  }
  $("#devices").append(node); devices.set(device.name, {device, node, signature: ""});
}
function hex(values) { return values.map(value => value.toString(16).padStart(2, "0")).join(" "); }
function renderLcd(node, state) {
  const lcd = $(".lcd", node); lcd.replaceChildren();
  state.cells.forEach((line, row) => line.forEach((code, col) => {
    const glyph = el("span", "glyph");
    const bitmap = code < 8 ? state.cgram.slice(code * 8, code * 8 + 8) : (font[String.fromCharCode(code)] || font["?"]);
    for (let y = 0; y < 8; y++) for (let x = 0; x < 5; x++) glyph.append(el("span", `dot${state.display && ((bitmap[y] || 0) & (1 << (4 - x))) ? " on" : ""}`));
    if (state.display && row === state.cursor_row && col === state.cursor_col) { glyph.classList.toggle("cursor", state.cursor); glyph.classList.toggle("blink", state.blink); }
    lcd.append(glyph);
  }));
  const text = state.display ? state.cells.map(line => line.map(code => code < 8 ? "◆" : String.fromCharCode(code)).join("")).join("\n") : "LCD apagado";
  $(".lcd-readable", node).textContent = text; $(".lcd-readable", node).setAttribute("aria-label", text);
  $(".lcd-status", node).textContent = `${state.display ? "Encendido" : "Apagado"} · Cursor ${state.cursor ? "sí" : "no"} · Dirección 0x${state.address.toString(16).padStart(2, "0")} · Desplazamiento ${state.shift}`;
  $(".memory", node).textContent = `DDRAM 00: ${hex(state.ddram[0])}\nDDRAM 40: ${hex(state.ddram[1])}\nCGRAM: ${hex(state.cgram)}`;
}
function render(message) {
  $("#cycle").textContent = `Ciclo ${message.cycle.toLocaleString("es-AR")}`;
  for (const [name, state] of Object.entries(message.devices)) {
    const entry = devices.get(name); if (!entry) continue;
    const signature = JSON.stringify([state, message.clock_hz]); if (entry.signature === signature) continue; entry.signature = signature;
    const {device, node} = entry;
    if (device.type === "keypad_4x4") {
      $(".filas", node).setAttribute("aria-label", `Filas ${state.rows}`); $(".columnas", node).setAttribute("aria-label", `Columnas ${state.columns}`);
      for (const [kind, value] of [["filas", state.rows], ["columnas", state.columns]]) [...$("." + kind, node).children].forEach((bit, i) => bit.classList.toggle("on", Boolean(value & (1 << i))));
      for (const button of node.querySelectorAll("button")) { const down = state.pressed.some(([row, col]) => row === Number(button.dataset.row) && col === Number(button.dataset.col)); button.classList.toggle("pressed", down); button.setAttribute("aria-pressed", String(down)); }
    } else if (device.type === "lcd_hd44780") renderLcd(node, state);
    else {
      const color = `rgb(${state.rgb.join(", ")})`, led = $(".led", node); led.style.backgroundColor = color; led.style.boxShadow = `0 0 30px ${color}`; led.setAttribute("aria-label", `LED RGB ${state.rgb.join(", ")}`);
      [...node.querySelectorAll(".channel")].forEach((channel, i) => { const percent = `${(state.duty[i] * 100).toFixed(1)} %`; $(".percent", channel).textContent = percent; $(".fill", channel).style.width = `${state.duty[i] * 100}%`; });
      $(".timing", node).textContent = message.clock_hz && state.period ? `${(message.clock_hz / state.period).toFixed(1)} Hz · ${(state.period * 1e6 / message.clock_hz).toFixed(1)} µs · ${state.period} ticks` : `${state.period} ticks · ${state.period ? "Sin reloj fijo" : "PWM detenido"}`;
    }
  }
}
function connect() {
  socket = new WebSocket(`ws://${location.host}/ws`);
  socket.addEventListener("message", event => {
    const message = JSON.parse(event.data);
    if (message.type === "HELLO") {
      held.clear(); devices.clear(); $("#devices").replaceChildren(); message.peripherals.forEach(card);
      $("#board").textContent = message.board; setStatus("Conectado", true); retry = 1000; $("#error").textContent = "";
    } else if (message.type === "STATE") render(message);
    else if (message.type === "ERROR") $("#error").textContent = message.message;
  });
  socket.addEventListener("close", () => { held.clear(); setStatus("Reconectando…", false); clearTimeout(timer); timer = setTimeout(connect, retry); retry = Math.min(retry * 2, 10000); });
  socket.addEventListener("error", () => socket.close());
}
for (const type of ["keydown", "keyup"]) document.addEventListener(type, event => {
  if (!active || (type === "keydown" && (event.repeat || event.ctrlKey || event.metaKey || event.altKey || event.target.matches("input, textarea, select")))) return;
  const char = event.key.toUpperCase(), row = layout.findIndex(line => line.includes(char));
  if (row < 0 || char.length !== 1) return;
  const keypad = [...devices.values()].find(entry => entry.device.type === "keypad_4x4"); if (!keypad) return;
  event.preventDefault(); key(keypad.device.name, row, layout[row].indexOf(char), type === "keydown", "keyboard");
});
window.addEventListener("blur", releaseAll);
document.addEventListener("visibilitychange", () => { if (document.hidden) releaseAll(); });
window.addEventListener("pagehide", releaseAll);
connect();
