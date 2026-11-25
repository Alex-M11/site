// Сторінка робочого столу: чекає на запуск контейнера, показує KasmVNC в iframe, надсилає heartbeat.
import { api, badge, confirmDialog, h, handleError, toast } from "./ui.js";
import { submitDialog } from "./submit.js";

const sessionId = Number(location.pathname.split("/").filter(Boolean).pop());
const $ = (id) => document.getElementById(id);
const frame = $("frame");
const wait = $("wait");
const waitText = $("wait-text");
let session = null;
let me = null;
let pollTimer = null;
let lastInteraction = Date.now();

const HEARTBEAT_MS = 60_000;
const INTERACTION_WINDOW_MS = 5 * 60_000; // без дій 5 хв — heartbeat не надсилаємо, спрацює автовимкнення

function showWait(text, actions = []) {
  frame.classList.add("hidden");
  frame.removeAttribute("src");
  wait.classList.remove("hidden");
  const spinner = actions.length ? null : h("div", { class: "spinner" });
  wait.replaceChildren(h("div", {}, spinner, h("div", { style: "margin-bottom:1rem" }, text), h("div", { class: "row", style: "justify-content:center" }, actions)));
}

function showDesktop() {
  if (!frame.classList.contains("hidden")) return;
  wait.classList.add("hidden");
  frame.classList.remove("hidden");
  frame.src = session.viewer_url;
  frame.addEventListener("load", hookFrameActivity, { once: true });
}

function hookFrameActivity() {
  // iframe того ж походження (через Nginx), тому можна слухати дії користувача всередині столу.
  try {
    const doc = frame.contentWindow.document;
    for (const ev of ["mousemove", "mousedown", "keydown", "touchstart", "wheel"]) {
      doc.addEventListener(ev, () => { lastInteraction = Date.now(); }, { capture: true, passive: true });
    }
  } catch { /* інше походження — орієнтуємося лише на видимість вкладки */ }
}

for (const ev of ["mousemove", "mousedown", "keydown", "touchstart"]) {
  window.addEventListener(ev, () => { lastInteraction = Date.now(); }, { passive: true });
}

function renderBar() {
  $("title").textContent = session.is_owner
    ? session.template.name
    : `${session.template.name} — ${session.user.full_name || session.user.username}`;
  document.title = `${session.template.name} · Робочий стіл`;
  $("status").replaceChildren(badge(session.status));
  $("btn-pause").textContent = session.status === "paused" ? "▶ Продовжити" : "⏸ Пауза";
  $("btn-pause").disabled = !["running", "paused"].includes(session.status);
  $("btn-stop").disabled = !["running", "paused"].includes(session.status);
  $("btn-submit").classList.toggle("hidden", !(session.is_owner && me && me.role === "student"));
  $("btn-files").classList.toggle("hidden", !session.is_owner);
  const note = $("helper-note");
  note.classList.toggle("hidden", session.is_owner);
  if (!session.is_owner) note.textContent = `Ви підключені до столу студента ${session.user.full_name || session.user.username}. Підключення записано в журнал.`;
}

async function refresh() {
  try {
    session = await api(`/api/sessions/${sessionId}`);
  } catch (err) {
    clearInterval(pollTimer);
    if (err.status === 401) { location.href = "/"; return; }
    showWait(err.message, [h("a", { class: "btn", href: "/" }, "До порталу")]);
    return;
  }
  renderBar();
  const start = h("button", { class: "primary", onclick: () => action("resume") }, "▶ Запустити стіл");
  switch (session.status) {
    case "creating":
      showWait("Готуємо робочий стіл… Перший запуск образу може тривати кілька хвилин.");
      break;
    case "running":
      if (session.ready) { showDesktop(); clearInterval(pollTimer); pollTimer = null; } else showWait("Стіл запускається…");
      break;
    case "paused":
      showWait("Стіл на паузі. Програми збережено в пам'яті.", [h("button", { class: "primary", onclick: () => action("resume") }, "▶ Продовжити")]);
      break;
    case "stopped":
      showWait("Стіл зупинено (вручну або через простій). Файли в «Мої_файли» збережено.", [start]);
      break;
    default:
      showWait(`Не вдалося запустити стіл: ${session.error || "невідома помилка"}`,
        [start, h("button", { onclick: () => action("reset") }, "↺ Скинути")]);
  }
  if (!["running"].includes(session.status) || !session.ready) ensurePolling();
}

function ensurePolling() {
  if (!pollTimer) pollTimer = setInterval(refresh, 2500);
}

async function action(name) {
  try {
    if (name === "reset" && !await confirmDialog("Скинути середовище?",
      "Стіл буде створено заново з шаблону. Усе, що не збережено в папці «Мої_файли», зникне.", "Скинути")) return;
    if (name === "stop" && !await confirmDialog("Зупинити стіл?", "Відкриті програми буде закрито. Файли в «Мої_файли» залишаться.", "Зупинити")) return;
    await api(`/api/sessions/${sessionId}/${name}`, { method: "POST" });
    frame.classList.add("hidden");
    frame.removeAttribute("src");
    await refresh();
    ensurePolling();
  } catch (err) { handleError(err); }
}

$("btn-pause").onclick = () => action(session.status === "paused" ? "resume" : "pause");
$("btn-stop").onclick = () => action("stop");
$("btn-reset").onclick = () => action("reset");
$("btn-files").onclick = () => window.open("/#/files", "portal");
$("btn-full").onclick = () => (frame.classList.contains("hidden") ? document.documentElement : frame).requestFullscreen?.();
$("btn-submit").onclick = () => submitDialog({ templateId: session.template.id }).catch(handleError);

setInterval(async () => {
  if (!session || !session.is_owner || session.status !== "running") return;
  if (document.hidden || Date.now() - lastInteraction > INTERACTION_WINDOW_MS) return;
  try {
    const res = await api(`/api/sessions/${sessionId}/heartbeat`, { method: "POST" });
    if (res.status !== "running") { toast("Стіл зупинено"); await refresh(); }
  } catch { /* мережа — спробуємо пізніше */ }
}, HEARTBEAT_MS);

(async () => {
  try { me = await api("/api/auth/me"); } catch { location.href = "/"; return; }
  await refresh();
})();
