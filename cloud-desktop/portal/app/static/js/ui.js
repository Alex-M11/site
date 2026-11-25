// Невеликі утиліти інтерфейсу: побудова DOM без innerHTML (захист від XSS), API, модальні вікна.

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") el.className = value;
    else if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2), value);
    else if (key === "value") el.value = value;
    else if (key === "checked" || key === "selected" || key === "disabled") el[key] = Boolean(value);
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

export async function api(path, { method = "GET", body, form } = {}) {
  const opts = { method, headers: { "X-Requested-With": "cloud-desktop" }, credentials: "same-origin" };
  if (form) opts.body = form;
  else if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  const res = await fetch(path, opts);
  const isJson = (res.headers.get("content-type") || "").includes("application/json");
  const data = isJson ? await res.json() : await res.text();
  if (!res.ok) {
    let message = (data && data.detail) || res.statusText;
    if (Array.isArray(message)) message = message.map((d) => `${(d.loc || []).slice(-1)[0]}: ${d.msg}`).join("; ");
    throw new ApiError(res.status, message);
  }
  return data;
}

export function toast(message, isError = false) {
  let box = document.querySelector(".toasts");
  if (!box) { box = h("div", { class: "toasts" }); document.body.append(box); }
  const el = h("div", { class: "toast" + (isError ? " error" : "") }, message);
  box.append(el);
  setTimeout(() => el.remove(), isError ? 6000 : 3500);
}

export function handleError(err) {
  console.error(err);
  toast(err.message || "Сталася помилка", true);
}

// Модальне вікно з формою. build(body) наповнює вміст і повертає функцію, що збирає дані.
export function modal(title, build, { submitText = "Зберегти", onSubmit, wide = false } = {}) {
  return new Promise((resolve) => {
    const body = h("div");
    const error = h("div", { class: "error-box hidden" });
    const collect = build(body);
    const close = (value) => { back.remove(); resolve(value); };
    const submitBtn = h("button", { class: "primary", type: "submit" }, submitText);
    const form = h("form", { class: "modal", style: wide ? "width:min(900px,100%)" : null },
      h("h3", {}, title), error, body,
      h("div", { class: "foot" },
        h("button", { type: "button", onclick: () => close(null) }, "Скасувати"),
        onSubmit ? submitBtn : null));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!onSubmit) return;
      submitBtn.disabled = true;
      try {
        const result = await onSubmit(collect ? collect() : undefined);
        close(result === undefined ? true : result);
      } catch (err) {
        error.textContent = err.message;
        error.classList.remove("hidden");
      } finally { submitBtn.disabled = false; }
    });
    const back = h("div", { class: "modal-back", onclick: (e) => { if (e.target === back) close(null); } }, form);
    document.body.append(back);
    const first = form.querySelector("input, select, textarea");
    if (first) first.focus();
  });
}

export async function confirmDialog(title, text, okText = "Так") {
  return modal(title, (body) => { body.append(h("p", {}, text)); }, { submitText: okText, onSubmit: async () => true });
}

export function field(labelText, input, hint) {
  return h("div", { class: "field" }, h("label", {}, labelText), input, hint ? h("div", { class: "muted small" }, hint) : null);
}

export function fmtBytes(bytes) {
  if (bytes === null || bytes === undefined) return "";
  const units = ["Б", "КБ", "МБ", "ГБ", "ТБ"];
  let i = 0; let n = bytes;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(n < 10 && i ? 1 : 0)} ${units[i]}`;
}

export function fmtDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("uk-UA", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function ago(iso) {
  if (!iso) return "—";
  const min = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (min < 1) return "щойно";
  if (min < 60) return `${min} хв тому`;
  if (min < 1440) return `${Math.floor(min / 60)} год тому`;
  return fmtDate(iso);
}

export const STATUS = {
  creating: "Запускається", running: "Працює", paused: "Пауза", stopped: "Зупинено", error: "Помилка",
};
export const ROLE = { student: "Студент", teacher: "Викладач", admin: "Адміністратор" };
export const OS_ICON = { ubuntu: "🐧", kali: "🐉", vscode: "💻", mysql: "🗄️", windows: "🪟", other: "🖥️" };

export function badge(status) {
  return h("span", { class: `badge ${status}` }, STATUS[status] || status);
}

export function table(headers, rows, emptyText = "Нічого немає") {
  if (!rows.length) return h("div", { class: "panel empty" }, emptyText);
  return h("div", { class: "panel table-wrap", style: "padding:0" },
    h("table", {}, h("thead", {}, h("tr", {}, headers.map((t) => h("th", {}, t)))),
      h("tbody", {}, rows.map((r) => h("tr", {}, r.map((c) => h("td", {}, c)))))));
}
