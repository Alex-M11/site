// Робочий стіл у браузері для демо-режиму (коли немає Docker).
// Працює зі справжніми «Моїми файлами» студента через API порталу: усе створене зберігається
// і може бути здане викладачу. Справжня Ubuntu/Kali запускається, коли встановлено Docker.

const HDR = { "X-Requested-With": "cloud-desktop" };
const desktopEl = document.getElementById("desktop");
const taskbarEl = document.getElementById("taskbar");
const bus = new EventTarget();
let me = { username: "student" };

// ------------------------------------------------------------------ утиліти
function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k === "style") e.style.cssText = v;
    else if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2), v);
    else if (k === "value") e.value = v;
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    e.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return e;
}

async function api(path, { method = "GET", body, form } = {}) {
  const opts = { method, headers: { ...HDR }, credentials: "same-origin" };
  if (form) opts.body = form;
  else if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  const res = await fetch(path, opts);
  const data = (res.headers.get("content-type") || "").includes("json") ? await res.json() : await res.text();
  if (!res.ok) {
    let msg = (data && data.detail) || res.statusText;
    if (Array.isArray(msg)) msg = msg.map((d) => d.msg).join("; ");
    throw new Error(msg);
  }
  return data;
}

function toast(text, isError = false) {
  const t = el("div", { class: "toast" + (isError ? " err" : "") }, text);
  document.body.append(t);
  setTimeout(() => t.remove(), isError ? 5000 : 2500);
}

const q = encodeURIComponent;
const P = {
  join: (a, b) => [a, b].filter(Boolean).join("/"),
  parent: (p) => p.split("/").slice(0, -1).join("/"),
  base: (p) => p.split("/").pop(),
  // Шлях відносно «Моїх файлів»: "~" і "/" — корінь, підтримуються "." і "..".
  resolve(cwd, input) {
    if (!input || input === "~") return "";
    let parts = input.startsWith("/") || input.startsWith("~") ? [] : cwd.split("/").filter(Boolean);
    for (const seg of input.replace(/^~\/?/, "").split("/")) {
      if (!seg || seg === ".") continue;
      if (seg === "..") parts.pop(); else parts.push(seg);
    }
    return parts.join("/");
  },
};

const fs = {
  list: (path) => api(`/api/files?path=${q(path)}`),
  mkdir: (path, name) => api("/api/files/mkdir", { method: "POST", body: { path, name } }),
  read: (path) => api(`/api/files/content?path=${q(path)}`).then((r) => r.content),
  write: (path, content) => api("/api/files/content", { method: "PUT", body: { path, content } }),
  move: (path, to) => api("/api/files/move", { method: "POST", body: { path, to } }),
  remove: (path) => api(`/api/files?path=${q(path)}`, { method: "DELETE" }),
  upload(path, file) {
    const form = new FormData(); form.append("path", path); form.append("file", file);
    return api("/api/files/upload", { method: "POST", form });
  },
  download: (path) => window.open(`/api/files/download?path=${q(path)}`, "_blank"),
  changed: () => bus.dispatchEvent(new Event("fs")),
};

const TEXT_EXT = /\.(txt|md|py|c|cc|cpp|h|hpp|java|js|ts|html|htm|css|json|sql|sh|bash|csv|xml|ya?ml|ini|cfg|conf|log|go|rs|php|rb|kt|cs|pas|asm|r|tex)$/i;
const isText = (name) => TEXT_EXT.test(name) || !name.includes(".");
const fileIcon = (item) => item.is_dir ? "📁" : /\.(png|jpe?g|gif|svg|webp)$/i.test(item.name) ? "🖼️"
  : /\.(zip|tar|gz|7z|rar)$/i.test(item.name) ? "🗜️" : /\.(py|c|cpp|java|js|sql|sh|html|css)$/i.test(item.name) ? "📜" : "📄";
const fmtSize = (n) => n == null ? "" : n < 1024 ? `${n} Б` : n < 1048576 ? `${(n / 1024).toFixed(1)} КБ` : `${(n / 1048576).toFixed(1)} МБ`;

function uniqueName(existing, base, ext = "") {
  const names = new Set(existing.map((i) => i.name));
  if (!names.has(base + ext)) return base + ext;
  for (let i = 2; ; i++) if (!names.has(`${base} ${i}${ext}`)) return `${base} ${i}${ext}`;
}

// ------------------------------------------------------------------ контекстне меню
let openMenu = null;
function closeMenu() { if (openMenu) { openMenu.remove(); openMenu = null; } }
function showMenu(x, y, items) {
  closeMenu();
  const m = el("div", { class: "menu" }, items.filter(Boolean).map((it) => it === "-" ? el("hr")
    : el("div", { onclick: () => { closeMenu(); it.action(); } }, it.label)));
  document.body.append(m);
  m.style.left = Math.min(x, innerWidth - m.offsetWidth - 4) + "px";
  m.style.top = Math.min(y, innerHeight - m.offsetHeight - 4) + "px";
  openMenu = m;
}
document.addEventListener("pointerdown", (e) => {
  if (openMenu && !openMenu.contains(e.target)) closeMenu();
  if (launcher && !launcher.contains(e.target) && e.target.id !== "activities") closeLauncher();
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeMenu(); closeLauncher(); } });

// ------------------------------------------------------------------ вікна
let zTop = 100;
let cascade = 0;
class Win {
  constructor({ title, icon = "🗔", width = 720, height = 460 }) {
    this.icon = icon;
    this.titleEl = el("span", { class: "t" }, title);
    this.body = el("div", { class: "body" });
    const bar = el("div", { class: "bar" }, el("span", {}, icon), this.titleEl,
      el("button", { title: "Згорнути", onclick: () => this.minimize() }, "–"),
      el("button", { title: "На весь екран", onclick: () => this.toggleMax() }, "□"),
      el("button", { class: "close", title: "Закрити", onclick: () => this.close() }, "✕"));
    this.root = el("div", { class: "win" }, bar, this.body);
    const off = (cascade++ % 8) * 28;
    Object.assign(this.root.style, {
      width: Math.min(width, innerWidth - 40) + "px", height: Math.min(height, innerHeight - 110) + "px",
      left: 60 + off + "px", top: 50 + off + "px",
    });
    this.root.addEventListener("pointerdown", () => this.focus());
    bar.addEventListener("dblclick", (e) => { if (e.target.tagName !== "BUTTON") this.toggleMax(); });
    bar.addEventListener("pointerdown", (e) => this.drag(e));
    this.task = el("button", { onclick: () => (this.root.classList.contains("hidden") || !this.root.classList.contains("focused")) ? this.focus() : this.minimize() },
      `${icon} `, title);
    document.body.append(this.root);
    taskbarEl.append(this.task);
    this.focus();
  }
  setTitle(t) { this.titleEl.textContent = t; this.task.lastChild.textContent = t; }
  focus() {
    this.root.classList.remove("hidden");
    document.querySelectorAll(".win.focused").forEach((w) => w.classList.remove("focused"));
    taskbarEl.querySelectorAll("button").forEach((b) => b.classList.remove("active"));
    this.root.classList.add("focused"); this.task.classList.add("active");
    this.root.style.zIndex = ++zTop;
    this.onFocus?.();
  }
  minimize() { this.root.classList.add("hidden"); this.root.classList.remove("focused"); this.task.classList.remove("active"); }
  toggleMax() { this.root.classList.toggle("max"); }
  close() {
    if (this.beforeClose && !this.beforeClose()) return;
    this.root.remove(); this.task.remove(); this.onClose?.();
  }
  drag(e) {
    if (e.target.tagName === "BUTTON" || this.root.classList.contains("max")) return;
    const sx = e.clientX - this.root.offsetLeft, sy = e.clientY - this.root.offsetTop;
    const move = (ev) => {
      this.root.style.left = Math.max(-this.root.offsetWidth + 80, Math.min(innerWidth - 80, ev.clientX - sx)) + "px";
      this.root.style.top = Math.max(30, Math.min(innerHeight - 74, ev.clientY - sy)) + "px";
    };
    const up = () => { removeEventListener("pointermove", move); removeEventListener("pointerup", up); };
    addEventListener("pointermove", move); addEventListener("pointerup", up);
  }
}

// ------------------------------------------------------------------ дії з файлами (спільні для столу й «Файлів»)
async function openItem(path, item) {
  if (item.is_dir) return new FileManager(path);
  if (isText(item.name)) return new Editor(path);
  fs.download(path);
}

async function newFolder(dir, existing, after) {
  const name = uniqueName(existing, "Нова папка");
  try { await fs.mkdir(dir, name); fs.changed(); after?.(P.join(dir, name)); } catch (e) { toast(e.message, true); }
}

async function newTextFile(dir, existing, after) {
  const name = uniqueName(existing, "Новий документ", ".txt");
  try { await fs.write(P.join(dir, name), ""); fs.changed(); after?.(P.join(dir, name)); } catch (e) { toast(e.message, true); }
}

async function removeItem(path, item) {
  if (!confirm(`Видалити «${item.name}»${item.is_dir ? " разом з усім вмістом" : ""}?`)) return;
  try { await fs.remove(path); fs.changed(); } catch (e) { toast(e.message, true); }
}

function startRename(labelEl, path, onDone) {
  const old = P.base(path);
  const input = el("input", { value: old });
  labelEl.replaceChildren(input);
  input.focus();
  const dot = old.lastIndexOf(".");
  input.setSelectionRange(0, dot > 0 ? dot : old.length);
  let done = false;
  const finish = async (save) => {
    if (done) return; done = true;
    const name = input.value.trim();
    if (save && name && name !== old) {
      try { await fs.move(path, P.join(P.parent(path), name)); fs.changed(); return; } catch (e) { toast(e.message, true); }
    }
    labelEl.textContent = old; onDone?.();
  };
  input.addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Enter") finish(true); if (e.key === "Escape") finish(false); });
  input.addEventListener("blur", () => finish(true));
  input.addEventListener("pointerdown", (e) => e.stopPropagation());
}

function itemMenu(e, path, item, labelEl, refresh) {
  e.preventDefault(); e.stopPropagation();
  showMenu(e.clientX, e.clientY, [
    { label: item.is_dir ? "📂 Відкрити" : "📝 Відкрити", action: () => openItem(path, item) },
    !item.is_dir && { label: "⬇ Завантажити на комп'ютер", action: () => fs.download(path) },
    item.is_dir && { label: "🖥 Відкрити в терміналі", action: () => new Terminal(path) },
    "-",
    { label: "✏ Перейменувати", action: () => startRename(labelEl, path, refresh) },
    { label: "🗑 Видалити", action: () => removeItem(path, item) },
  ]);
}

// ------------------------------------------------------------------ робочий стіл
const APPS = [
  { name: "Мої_файли", icon: "🏠", open: () => new FileManager("") },
  { name: "Термінал", icon: "🖥️", open: () => new Terminal("") },
  { name: "Текстовий редактор", icon: "📝", open: () => new Editor(null) },
  { name: "Браузер", icon: "🌐", open: () => new Browser() },
  { name: "Калькулятор", icon: "🧮", open: () => new Calculator() },
  { name: "Справжня Ubuntu?", icon: "🐧", open: () => new About() },
];

let desktopItems = [];
async function renderDesktop(renamePath) {
  let items = [];
  try { items = (await fs.list("")).items; } catch (e) { toast(e.message, true); }
  desktopItems = items;
  const icons = [];
  for (const app of APPS) {
    const d = el("div", { class: "dicon", title: app.name }, el("span", { class: "ico" }, app.icon), el("span", {}, app.name));
    d.addEventListener("dblclick", app.open);
    d.addEventListener("click", (e) => select(d, e));
    d.addEventListener("keydown", (e) => { if (e.key === "Enter") app.open(); });
    d.tabIndex = 0;
    icons.push(d);
  }
  for (const item of items) {
    const label = el("span", {}, item.name);
    const d = el("div", { class: "dicon", title: item.name + (item.is_dir ? "" : ` (${fmtSize(item.size)})`), tabindex: 0 },
      el("span", { class: "ico" }, fileIcon(item)), label);
    d.addEventListener("dblclick", () => openItem(item.path, item));
    d.addEventListener("click", (e) => select(d, e));
    d.addEventListener("contextmenu", (e) => { select(d, e); itemMenu(e, item.path, item, label, renderDesktop); });
    d.addEventListener("keydown", (e) => {
      if (e.key === "Enter") openItem(item.path, item);
      if (e.key === "Delete") removeItem(item.path, item);
      if (e.key === "F2") startRename(label, item.path, renderDesktop);
    });
    icons.push(d);
    if (renamePath === item.path) setTimeout(() => { select(d); startRename(label, item.path, renderDesktop); });
  }
  desktopEl.replaceChildren(...icons);
}
function select(d) {
  desktopEl.querySelectorAll(".selected").forEach((x) => x.classList.remove("selected"));
  d.classList.add("selected"); d.focus();
}
desktopEl.addEventListener("click", (e) => { if (e.target === desktopEl) desktopEl.querySelectorAll(".selected").forEach((x) => x.classList.remove("selected")); });
desktopEl.addEventListener("contextmenu", (e) => {
  if (e.target !== desktopEl) return;
  e.preventDefault();
  showMenu(e.clientX, e.clientY, [
    { label: "📁 Нова папка", action: () => newFolder("", desktopItems, (p) => renderDesktop(p)) },
    { label: "📄 Новий текстовий файл", action: () => newTextFile("", desktopItems, (p) => renderDesktop(p)) },
    "-",
    { label: "🖥 Відкрити термінал", action: () => new Terminal("") },
    { label: "🏠 Відкрити «Мої_файли»", action: () => new FileManager("") },
    { label: "⟳ Оновити", action: () => renderDesktop() },
  ]);
});
// перетягнути файли з комп'ютера прямо на стіл
desktopEl.addEventListener("dragover", (e) => e.preventDefault());
desktopEl.addEventListener("drop", async (e) => {
  e.preventDefault();
  for (const f of e.dataTransfer.files) { try { await fs.upload("", f); } catch (err) { toast(err.message, true); } }
  fs.changed();
});
bus.addEventListener("fs", () => renderDesktop());

// меню «Програми»
let launcher = null;
function closeLauncher() { if (launcher) { launcher.remove(); launcher = null; } }
document.getElementById("activities").addEventListener("click", () => {
  if (launcher) return closeLauncher();
  launcher = el("div", { class: "launcher" }, APPS.map((a) => el("div", { class: "dicon", onclick: () => { closeLauncher(); a.open(); } },
    el("span", { class: "ico" }, a.icon), el("span", {}, a.name))));
  document.body.append(launcher);
});

// ------------------------------------------------------------------ «Файли»
class FileManager extends Win {
  constructor(path) {
    super({ title: "Мої_файли", icon: "📁", width: 760, height: 480 });
    this.path = path; this.history = []; this.items = [];
    this.crumbs = el("div", { class: "crumbs" });
    this.list = el("div", { class: "fm", tabindex: 0 });
    this.status = el("div", { class: "status" });
    const upload = el("input", { type: "file", multiple: true, style: "display:none", onchange: async () => {
      for (const f of upload.files) { try { await fs.upload(this.path, f); } catch (e) { toast(e.message, true); } }
      upload.value = ""; fs.changed();
    } });
    this.body.append(el("div", { class: "tool" },
      el("button", { title: "Назад", onclick: () => this.history.length && this.go(this.history.pop(), false) }, "←"),
      el("button", { title: "Вгору", onclick: () => this.path && this.go(P.parent(this.path)) }, "↑"),
      this.crumbs,
      el("button", { onclick: () => newFolder(this.path, this.items, (p) => this.load(p)) }, "📁 Нова папка"),
      el("button", { onclick: () => newTextFile(this.path, this.items, (p) => this.load(p)) }, "📄 Новий файл"),
      el("button", { onclick: () => upload.click() }, "⬆ Завантажити"), upload,
      el("button", { title: "Оновити", onclick: () => this.load() }, "⟳")), this.list, this.status);
    this.list.addEventListener("contextmenu", (e) => {
      if (e.target !== this.list) return;
      e.preventDefault();
      showMenu(e.clientX, e.clientY, [
        { label: "📁 Нова папка", action: () => newFolder(this.path, this.items, (p) => this.load(p)) },
        { label: "📄 Новий текстовий файл", action: () => newTextFile(this.path, this.items, (p) => this.load(p)) },
        { label: "⬆ Завантажити файли", action: () => upload.click() },
        { label: "🖥 Відкрити термінал тут", action: () => new Terminal(this.path) },
      ]);
    });
    this.list.addEventListener("dragover", (e) => { e.preventDefault(); this.list.classList.add("drop"); });
    this.list.addEventListener("dragleave", () => this.list.classList.remove("drop"));
    this.list.addEventListener("drop", async (e) => {
      e.preventDefault(); this.list.classList.remove("drop");
      for (const f of e.dataTransfer.files) { try { await fs.upload(this.path, f); } catch (err) { toast(err.message, true); } }
      fs.changed();
    });
    this.listener = () => this.load();
    bus.addEventListener("fs", this.listener);
    this.onClose = () => bus.removeEventListener("fs", this.listener);
    this.load();
  }
  go(path, remember = true) { if (remember) this.history.push(this.path); this.path = path; this.load(); }
  async load(renamePath) {
    let data;
    try { data = await fs.list(this.path); } catch (e) { toast(e.message, true); if (this.path) return this.go(P.parent(this.path), false); return; }
    this.items = data.items;
    const parts = this.path ? this.path.split("/") : [];
    this.crumbs.replaceChildren(el("a", { onclick: () => this.go("") }, "🏠 Мої_файли"),
      parts.map((p, i) => [" / ", el("a", { onclick: () => this.go(parts.slice(0, i + 1).join("/")) }, p)]));
    this.setTitle(this.path ? P.base(this.path) : "Мої_файли");
    this.list.replaceChildren(...(data.items.length ? data.items.map((item) => {
      const label = el("span", {}, item.name);
      const d = el("div", { class: "fitem", title: item.name }, el("span", { class: "ico" }, fileIcon(item)), label,
        item.is_dir ? null : el("div", { class: "sz" }, fmtSize(item.size)));
      d.addEventListener("click", () => { this.list.querySelectorAll(".selected").forEach((x) => x.classList.remove("selected")); d.classList.add("selected"); });
      d.addEventListener("dblclick", () => item.is_dir ? this.go(item.path) : openItem(item.path, item));
      d.addEventListener("contextmenu", (e) => itemMenu(e, item.path, item, label, () => this.load()));
      if (renamePath === item.path) setTimeout(() => startRename(label, item.path, () => this.load()));
      return d;
    }) : [el("div", { class: "empty" }, "Папка порожня. Клацніть правою кнопкою, щоб створити папку чи файл, або перетягніть сюди файли з комп'ютера.")]));
    const used = data.quota ? ` · зайнято ${fmtSize(data.used)} з ${fmtSize(data.quota)}` : "";
    this.status.textContent = `${data.items.length} об'єктів${used}`;
  }
}

// ------------------------------------------------------------------ текстовий редактор
class Editor extends Win {
  constructor(path) {
    super({ title: path ? P.base(path) : "Без назви", icon: "📝", width: 760, height: 520 });
    this.path = path; this.saved = "";
    this.area = el("textarea", { class: "editor", spellcheck: "false" });
    this.status = el("div", { class: "status" });
    this.body.append(el("div", { class: "tool" },
      el("button", { onclick: () => this.save() }, "💾 Зберегти"),
      el("button", { onclick: () => this.save(true) }, "Зберегти як…"),
      el("span", { style: "color:#666;font-size:12px" }, "Ctrl+S — зберегти")), this.area, this.status);
    this.area.addEventListener("input", () => this.updateStatus());
    this.area.addEventListener("keyup", () => this.updateStatus());
    this.area.addEventListener("click", () => this.updateStatus());
    this.area.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); this.save(); }
      if (e.key === "Tab") { e.preventDefault(); document.execCommand("insertText", false, "    "); }
    });
    this.beforeClose = () => this.area.value === this.saved || confirm("Зміни не збережено. Закрити без збереження?");
    this.onFocus = () => setTimeout(() => this.area.focus());
    if (path) this.load(); else this.updateStatus();
  }
  async load() {
    try { this.saved = this.area.value = await fs.read(this.path); }
    catch (e) {
      toast(e.message, true);
      if (/не текстовий|завеликий/.test(e.message)) { fs.download(this.path); this.beforeClose = null; this.close(); return; }
    }
    this.updateStatus(); this.area.focus();
  }
  async save(asNew = false) {
    let path = this.path;
    if (!path || asNew) {
      const name = prompt("Назва файлу (у «Моїх_файлах», можна з папкою: lab1/main.py):", path || "документ.txt");
      if (!name) return;
      path = P.resolve("", name.trim());
    }
    try {
      await fs.write(path, this.area.value);
      this.path = path; this.saved = this.area.value;
      this.setTitle(P.base(path)); this.updateStatus(); fs.changed(); toast("Збережено");
    } catch (e) { toast(e.message, true); }
  }
  updateStatus() {
    const before = this.area.value.slice(0, this.area.selectionStart).split("\n");
    this.status.textContent = `${this.path ? "~/Мої_файли/" + this.path : "новий файл"} · рядок ${before.length}, стовпець ${before.at(-1).length + 1} · ` +
      (this.area.value === this.saved ? "збережено" : "● не збережено");
  }
}

// ------------------------------------------------------------------ термінал
const NO_LINUX = "у демо-режимі справжні програми Linux недоступні. Встановіть Docker Desktop — і в столі буде справжня Ubuntu з терміналом, Python, gcc тощо.";
class Terminal extends Win {
  constructor(cwd = "") {
    super({ title: "Термінал", icon: "🖥️", width: 720, height: 420 });
    this.cwd = cwd; this.prev = ""; this.hist = []; this.hpos = 0;
    this.out = el("div", { class: "term" });
    this.input = el("input", { autocomplete: "off", spellcheck: "false" });
    this.promptEl = el("span", { class: "ps" });
    this.inLine = el("div", { class: "in" }, this.promptEl, this.input);
    this.out.append(this.inLine);
    this.body.append(this.out);
    this.out.addEventListener("click", () => { if (!getSelection().toString()) this.input.focus(); });
    this.input.addEventListener("keydown", (e) => this.key(e));
    this.onFocus = () => setTimeout(() => this.input.focus());
    this.print(`Ласкаво просимо до демо-терміналу. Команди працюють з вашими «Моїми_файлами». Наберіть help.`);
    this.renderPrompt();
  }
  prompt() {
    return [el("span", {}, `${me.username}@desktop`), ":", el("span", { class: "p" }, "~" + (this.cwd ? "/" + this.cwd : "")), "$ "];
  }
  renderPrompt() { this.promptEl.replaceChildren(...this.prompt()); this.input.focus(); }
  print(text, cls) { this.inLine.before(el("div", { class: "line" + (cls ? " " + cls : "") }, text)); this.out.scrollTop = this.out.scrollHeight; }
  printNodes(nodes) { this.inLine.before(el("div", { class: "line" }, nodes)); }
  async key(e) {
    if (e.key === "Enter") {
      const cmd = this.input.value;
      this.printNodes([...this.prompt(), cmd]);
      this.input.value = "";
      if (cmd.trim()) { this.hist.push(cmd); this.hpos = this.hist.length; }
      this.input.disabled = true;
      try { await this.run(cmd.trim()); } catch (err) { this.print(err.message, "err"); }
      this.input.disabled = false; this.renderPrompt(); this.out.scrollTop = this.out.scrollHeight;
    } else if (e.key === "ArrowUp") {
      e.preventDefault(); if (this.hpos > 0) this.input.value = this.hist[--this.hpos];
    } else if (e.key === "ArrowDown") {
      e.preventDefault(); this.hpos = Math.min(this.hist.length, this.hpos + 1); this.input.value = this.hist[this.hpos] || "";
    } else if (e.key === "Tab") {
      e.preventDefault(); await this.complete();
    } else if (e.key === "l" && e.ctrlKey) {
      e.preventDefault(); this.clear();
    }
  }
  clear() { this.out.replaceChildren(this.inLine); }
  async complete() {
    const v = this.input.value; const m = v.match(/(\S*)$/); const word = m[1];
    const dirPart = word.includes("/") ? word.slice(0, word.lastIndexOf("/") + 1) : "";
    const prefix = word.slice(dirPart.length);
    try {
      const items = (await fs.list(P.resolve(this.cwd, dirPart || "."))).items.filter((i) => i.name.startsWith(prefix));
      if (items.length === 1) this.input.value = v.slice(0, v.length - word.length) + dirPart + items[0].name + (items[0].is_dir ? "/" : " ");
      else if (items.length > 1) this.print(items.map((i) => i.name + (i.is_dir ? "/" : "")).join("  "));
    } catch { /* немає такої папки */ }
  }
  tokens(line) {
    const out = []; let cur = ""; let quote = null; let has = false;
    for (const ch of line) {
      if (quote) { if (ch === quote) quote = null; else cur += ch; continue; }
      if (ch === '"' || ch === "'") { quote = ch; has = true; continue; }
      if (/\s/.test(ch)) { if (cur || has) { out.push(cur); cur = ""; has = false; } continue; }
      cur += ch;
    }
    if (cur || has) out.push(cur);
    return out;
  }
  async stat(path) {
    if (!path) return { is_dir: true, name: "~", path: "" };
    const items = (await fs.list(P.parent(path))).items;
    return items.find((i) => i.name === P.base(path)) || null;
  }
  async run(line) {
    if (!line) return;
    // перенаправлення: echo текст > файл / >> файл
    const redir = line.match(/^(.*?)\s*(>>?)\s*(\S+)\s*$/);
    if (redir && /^echo\b/.test(redir[1])) {
      const text = this.tokens(redir[1]).slice(1).join(" ") + "\n";
      const path = P.resolve(this.cwd, redir[3]);
      let content = text;
      if (redir[2] === ">>") { try { content = (await fs.read(path)) + text; } catch { /* новий файл */ } }
      await fs.write(path, content); fs.changed(); return;
    }
    const [cmd, ...args] = this.tokens(line);
    const flags = new Set(args.filter((a) => /^-\w+$/.test(a)).flatMap((a) => [...a.slice(1)]));
    const pos = args.filter((a) => !/^-\w+$/.test(a));
    const R = (p) => P.resolve(this.cwd, p);
    switch (cmd) {
      case "help":
        this.print([
          "Команди демо-терміналу (працюють з «Моїми_файлами»):",
          "  ls [-l] [папка]      вміст папки            cd папка | .. | ~ | -   перейти",
          "  pwd                  поточна папка          tree                    дерево папок",
          "  mkdir [-p] назва     створити папку         touch файл              створити порожній файл",
          "  cat файл             показати вміст         echo текст > файл       записати (>> — дописати)",
          "  cp файл куди         копіювати файл         mv що куди              перемістити / перейменувати",
          "  rm [-r] що           видалити               nano файл               відкрити в редакторі",
          "  open що              відкрити у вікні       clear, history, whoami, date, uname, exit",
        ].join("\n")); break;
      case "pwd": this.print("/home/" + me.username + "/Мої_файли" + (this.cwd ? "/" + this.cwd : "")); break;
      case "whoami": this.print(me.username); break;
      case "hostname": this.print("desktop"); break;
      case "date": this.print(new Date().toLocaleString("uk-UA", { dateStyle: "full", timeStyle: "medium" })); break;
      case "uname": this.print(flags.has("a") ? "Linux desktop 6.8.0-demo #1 SMP x86_64 GNU/Linux (демо)" : "Linux"); break;
      case "clear": this.clear(); break;
      case "history": this.print(this.hist.map((h, i) => `${String(i + 1).padStart(4)}  ${h}`).join("\n")); break;
      case "exit": this.close(); break;
      case "cd": {
        const target = pos[0] === "-" ? this.prev : R(pos[0] || "~");
        const st = await this.stat(target);
        if (!st) throw new Error(`cd: ${pos[0]}: Немає такого файлу або каталогу`);
        if (!st.is_dir) throw new Error(`cd: ${pos[0]}: Це не каталог`);
        this.prev = this.cwd; this.cwd = target; break;
      }
      case "ls": case "ll": case "dir": {
        const target = R(pos[0] || ".");
        const st = await this.stat(target);
        if (!st) throw new Error(`ls: неможливо отримати доступ до '${pos[0]}': Немає такого файлу або каталогу`);
        const items = st.is_dir ? (await fs.list(target)).items : [st];
        const long = flags.has("l") || cmd === "ll";
        if (!items.length) break;
        if (long) {
          this.print(`усього ${items.length}`);
          for (const i of items) {
            const d = new Date(i.modified * 1000).toLocaleString("uk-UA", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
            this.printNodes([`${i.is_dir ? "drwxr-xr-x" : "-rw-r--r--"} ${me.username} ${String(i.size ?? 4096).padStart(8)} ${d} `,
              el("span", { class: i.is_dir ? "dir" : "" }, i.name)]);
          }
        } else {
          this.printNodes(items.flatMap((i) => [el("span", { class: i.is_dir ? "dir" : "" }, i.name), "  "]));
        }
        break;
      }
      case "tree": {
        const lines = [pos[0] || "."];
        const walk = async (dir, prefix, depth) => {
          const items = (await fs.list(dir)).items;
          for (const [n, i] of items.entries()) {
            const last = n === items.length - 1;
            lines.push(prefix + (last ? "└── " : "├── ") + i.name + (i.is_dir ? "/" : ""));
            if (i.is_dir && depth < 4) await walk(i.path, prefix + (last ? "    " : "│   "), depth + 1);
          }
        };
        await walk(R(pos[0] || "."), "", 0);
        this.print(lines.join("\n")); break;
      }
      case "mkdir": {
        if (!pos.length) throw new Error("mkdir: пропущено операнд");
        for (const p of pos) {
          const full = R(p);
          if (flags.has("p")) {
            let cur = "";
            for (const seg of full.split("/")) {
              const next = P.join(cur, seg);
              if (!(await this.stat(next))) await fs.mkdir(cur, seg);
              cur = next;
            }
          } else {
            if (await this.stat(full)) throw new Error(`mkdir: неможливо створити каталог '${p}': Файл існує`);
            await fs.mkdir(P.parent(full), P.base(full));
          }
        }
        fs.changed(); break;
      }
      case "touch": {
        for (const p of pos) if (!(await this.stat(R(p)))) await fs.write(R(p), "");
        fs.changed(); break;
      }
      case "cat": {
        if (!pos.length) throw new Error("cat: вкажіть файл");
        for (const p of pos) {
          const st = await this.stat(R(p));
          if (!st) throw new Error(`cat: ${p}: Немає такого файлу або каталогу`);
          if (st.is_dir) throw new Error(`cat: ${p}: Це каталог`);
          const text = await fs.read(R(p));
          this.print(text.endsWith("\n") ? text.slice(0, -1) : text);
        }
        break;
      }
      case "echo": this.print(pos.join(" ")); break;
      case "rm": {
        if (!pos.length) throw new Error("rm: пропущено операнд");
        for (const p of pos) {
          const st = await this.stat(R(p));
          if (!st) { if (!flags.has("f")) throw new Error(`rm: неможливо видалити '${p}': Немає такого файлу або каталогу`); continue; }
          if (st.is_dir && !flags.has("r")) throw new Error(`rm: неможливо видалити '${p}': Це каталог (використайте rm -r)`);
          await fs.remove(R(p));
        }
        fs.changed(); break;
      }
      case "rmdir": {
        for (const p of pos) {
          if ((await fs.list(R(p))).items.length) throw new Error(`rmdir: не вдалося видалити '${p}': Каталог не порожній`);
          await fs.remove(R(p));
        }
        fs.changed(); break;
      }
      case "mv": case "cp": {
        if (pos.length !== 2) throw new Error(`${cmd}: потрібно два аргументи: що і куди`);
        const src = R(pos[0]); let dst = R(pos[1]);
        const st = await this.stat(src);
        if (!st) throw new Error(`${cmd}: не вдалося отримати '${pos[0]}': Немає такого файлу або каталогу`);
        const dstSt = await this.stat(dst);
        if (dstSt && dstSt.is_dir) dst = P.join(dst, P.base(src));
        if (cmd === "mv") await fs.move(src, dst);
        else {
          if (st.is_dir) throw new Error("cp: копіювання папок у демо-терміналі не підтримується");
          await fs.write(dst, await fs.read(src));
        }
        fs.changed(); break;
      }
      case "nano": case "vim": case "vi": case "gedit": case "edit": case "code":
        if (pos[0]) new Editor(R(pos[0])); else new Editor(null);
        break;
      case "open": case "xdg-open": {
        const target = R(pos[0] || ".");
        const st = await this.stat(target);
        if (!st) throw new Error(`open: ${pos[0]}: не знайдено`);
        openItem(target, st); break;
      }
      case "python": case "python3": case "gcc": case "g++": case "node": case "java": case "javac": case "make":
      case "apt": case "apt-get": case "pip": case "pip3": case "git": case "mysql": case "nmap": case "ping": case "curl": case "wget":
        throw new Error(`${cmd}: ${NO_LINUX}`);
      case "sudo": throw new Error(`sudo: ${me.username} не має прав адміністратора на цьому столі. І це добре 🙂`);
      default: throw new Error(`${cmd}: команду не знайдено. Наберіть help, щоб побачити список.`);
    }
  }
}

// ------------------------------------------------------------------ браузер
class Browser extends Win {
  constructor(url = "") {
    super({ title: "Браузер", icon: "🌐", width: 900, height: 600 });
    this.addr = el("input", { type: "text", value: url, placeholder: "Адреса сайту, напр. uk.wikipedia.org" });
    this.frame = el("iframe", { class: "browser", referrerpolicy: "no-referrer",
      sandbox: "allow-scripts allow-forms allow-popups allow-same-origin allow-downloads" });
    this.status = el("div", { class: "status" }, "Деякі сайти забороняють показ у вбудованому вікні — тоді натисніть «↗ У новій вкладці».");
    const go = () => this.go(this.addr.value);
    this.addr.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
    this.body.append(el("div", { class: "tool" },
      el("button", { title: "Домашня сторінка", onclick: () => this.home() }, "🏠"), this.addr,
      el("button", { onclick: go }, "Перейти"),
      el("button", { onclick: () => this.addr.value && window.open(this.normalize(this.addr.value), "_blank", "noopener") }, "↗ У новій вкладці")),
    this.frame, this.status);
    if (url) this.go(url); else this.home();
  }
  normalize(u) { u = u.trim(); return /^https?:\/\//.test(u) ? u : "https://" + u; }
  go(u) { if (!u.trim()) return; const url = this.normalize(u); this.addr.value = url; this.frame.removeAttribute("srcdoc"); this.frame.src = url; this.setTitle(url.replace(/^https?:\/\//, "")); }
  home() {
    this.addr.value = ""; this.setTitle("Браузер");
    const links = [["Вікіпедія", "https://uk.m.wikipedia.org"], ["Документація Python", "https://docs.python.org/uk/3/"],
      ["MDN (HTML, CSS, JS)", "https://developer.mozilla.org/uk/"], ["Пошук DuckDuckGo", "https://html.duckduckgo.com/html/"]];
    this.frame.srcdoc = `<!doctype html><meta charset="utf-8"><body style="font-family:sans-serif;padding:30px;color:#333">
      <h2>Браузер демо-столу</h2><p>Введіть адресу вгорі або відкрийте:</p><ul>${
      links.map(([t, u]) => `<li><a href="${u}">${t}</a></li>`).join("")}</ul>
      <p style="color:#888;font-size:13px">Багато сайтів (Google, YouTube) не дозволяють показувати себе у вбудованому вікні —
      для них є кнопка «↗ У новій вкладці». У справжньому столі (з Docker) працює повноцінний Firefox.</p></body>`;
  }
}

// ------------------------------------------------------------------ калькулятор
class Calculator extends Win {
  constructor() {
    super({ title: "Калькулятор", icon: "🧮", width: 300, height: 400 });
    this.cur = "0"; this.acc = null; this.op = null; this.fresh = false;
    this.disp = el("div", { class: "disp" }, "0");
    const keys = ["C", "±", "%", "÷", "7", "8", "9", "×", "4", "5", "6", "−", "1", "2", "3", "+", "0", ".", "⌫", "="];
    this.body.append(el("div", { class: "calc" }, this.disp,
      keys.map((k) => el("button", { class: /[÷×−+=]/.test(k) ? "op" : "", onclick: () => this.press(k) }, k))));
    this.root.addEventListener("keydown", (e) => {
      const map = { "/": "÷", "*": "×", "-": "−", Enter: "=", Backspace: "⌫", Escape: "C" };
      const k = map[e.key] || e.key;
      if ("0123456789.+÷×−=⌫C%".includes(k)) { e.preventDefault(); this.press(k); }
    });
    this.root.tabIndex = 0; this.onFocus = () => this.root.focus();
  }
  calc(a, b, op) { return op === "+" ? a + b : op === "−" ? a - b : op === "×" ? a * b : op === "÷" ? (b === 0 ? NaN : a / b) : b; }
  press(k) {
    if (/\d/.test(k)) { this.cur = this.fresh || this.cur === "0" ? k : this.cur + k; this.fresh = false; }
    else if (k === ".") { if (this.fresh) { this.cur = "0"; this.fresh = false; } if (!this.cur.includes(".")) this.cur += "."; }
    else if (k === "C") { this.cur = "0"; this.acc = null; this.op = null; }
    else if (k === "⌫") { this.cur = this.cur.length > 1 ? this.cur.slice(0, -1) : "0"; }
    else if (k === "±") { this.cur = String(-parseFloat(this.cur)); }
    else if (k === "%") { this.cur = String(parseFloat(this.cur) / 100); }
    else {
      const v = parseFloat(this.cur);
      if (this.op && !this.fresh) this.acc = this.calc(this.acc, v, this.op); else if (this.acc === null || !this.op) this.acc = v;
      this.op = k === "=" ? null : k;
      this.cur = String(+this.acc.toPrecision(12));
      if (k === "=") this.acc = null;
      this.fresh = true;
    }
    this.disp.textContent = this.cur === "NaN" ? "Помилка" : this.cur;
  }
}

// ------------------------------------------------------------------ про справжню Ubuntu
class About extends Win {
  constructor() {
    super({ title: "Як отримати справжню Ubuntu", icon: "🐧", width: 560, height: 360 });
    this.body.append(el("div", { style: "padding:18px 22px;line-height:1.55;overflow:auto;user-select:text" },
      el("h3", { style: "margin-top:0" }, "Це демо-стіл"),
      el("p", {}, "Портал працює без Docker, тому робочий стіл тут — веб-імітація: файли, папки, термінал з базовими командами, редактор і браузер. " +
        "Усе, що ви створюєте, справді зберігається в «Моїх_файлах» і його можна здати викладачу."),
      el("h3", {}, "Справжня Ubuntu, Kali Linux і VS Code"),
      el("ol", {},
        el("li", {}, "Встановіть Docker Desktop (з WSL 2) і запустіть його."),
        el("li", {}, "Перезапустіть портал (CloudDesktop.exe: значок ☁ → «Зупинити й вийти», потім запустити знову)."),
        el("li", {}, "Запустіть середовище ще раз — відкриється справжній Linux з усіма програмами.")),
      el("p", { style: "color:#666" }, "На сервері коледжу (серверна версія порталу) справжні столи доступні одразу.")));
  }
}

// ------------------------------------------------------------------ старт
function tick() {
  document.getElementById("clock").textContent = new Date().toLocaleString("uk-UA", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

(async () => {
  tick(); setInterval(tick, 15000);
  const sid = (location.pathname.match(/\/desktop\/(\d+)/) || [])[1];
  try {
    me = await api("/api/auth/me");
    const sess = sid ? await api(`/api/sessions/${sid}`) : { is_owner: true };
    if (!sess.is_owner) {
      // Викладач дивиться демо-стіл студента: у демо-режимі показуємо лише пояснення (файли — студентські).
      desktopEl.replaceChildren(el("div", { class: "notice" },
        el("h3", { style: "margin-top:0" }, `Демо-стіл: ${sess.user.full_name || sess.user.username}`),
        el("p", {}, "У демо-режимі (без Docker) підключення до столу студента недоступне. " +
          "Роботу студента можна переглянути в розділі «Завдання й роботи», а повноцінне підключення працює зі справжніми столами (Docker).")));
      return;
    }
  } catch (e) {
    desktopEl.replaceChildren(el("div", { class: "notice" }, "Не вдалося завантажити стіл: ", e.message));
    return;
  }
  await renderDesktop();
  desktopEl.focus();
})();
