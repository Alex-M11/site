import {
  ago, api, ApiError, badge, confirmDialog, field, fmtBytes, fmtDate, h, handleError, modal, OS_ICON, ROLE,
  table, toast,
} from "./ui.js";
import { submitDialog } from "./submit.js";

const state = { user: null };
const root = document.getElementById("root");

// ---------------------------------------------------------------- вхід
function takeLoginError() {
  const params = new URLSearchParams(location.search);
  const msg = params.get("login_error");
  if (msg) history.replaceState(null, "", location.pathname + location.hash);
  return msg;
}

function renderLogin(message) {
  message = message || takeLoginError();
  const error = h("div", { class: "error-box" + (message ? "" : " hidden") }, message || "");
  const username = h("input", { name: "username", autocomplete: "username", required: true, placeholder: "напр. student1" });
  const password = h("input", { name: "password", type: "password", autocomplete: "current-password", required: true });
  const btn = h("button", { class: "primary", type: "submit", style: "width:100%;justify-content:center" }, "Увійти");
  const form = h("form", { class: "stack" }, error, field("Логін", username), field("Пароль", password), btn);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    btn.disabled = true;
    try {
      await api("/api/auth/login", { method: "POST", body: { username: username.value, password: password.value } });
      await boot();
    } catch (err) {
      error.textContent = err.message; error.classList.remove("hidden");
    } finally { btn.disabled = false; }
  });
  const sso = h("div", { class: "stack hidden" });
  root.replaceChildren(h("div", { class: "login-wrap" }, h("div", { class: "login-card stack" },
    h("div", { class: "logo" }, h("div", { class: "logo-mark" }, "☁"), "Хмарний робочий стіл"),
    h("p", { class: "muted" }, "Робочі столи Ubuntu, Kali Linux та середовища для програмування просто в браузері. Увійдіть обліковим записом коледжу."),
    sso,
    form,
    h("p", { class: "muted small" }, "Забули пароль? Зверніться до викладача або адміністратора — вам видадуть тимчасовий."))));
  username.focus();
  api("/api/auth/oidc/config").then((cfg) => {
    if (!cfg.enabled) return;
    sso.append(h("a", { class: "btn primary", href: "/api/auth/oidc/login", style: "justify-content:center;width:100%" }, `✉ ${cfg.label}`),
      h("div", { class: "divider" }, "або логін і пароль"));
    sso.classList.remove("hidden");
  }).catch(() => {});
}

// Тимчасовий пароль від адміністратора/викладача: поки не змінено — інші розділи закриті.
function renderForcePassword() {
  const error = h("div", { class: "error-box hidden" });
  const oldPw = h("input", { type: "password", autocomplete: "current-password", required: true });
  const newPw = h("input", { type: "password", autocomplete: "new-password", required: true });
  const newPw2 = h("input", { type: "password", autocomplete: "new-password", required: true });
  const btn = h("button", { class: "primary", type: "submit", style: "width:100%;justify-content:center" }, "Зберегти пароль");
  const form = h("form", { class: "stack" }, error, field("Тимчасовий пароль", oldPw),
    field("Новий пароль", newPw, "Щонайменше 8 символів, літери й цифри"), field("Новий пароль ще раз", newPw2), btn);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (newPw.value !== newPw2.value) { error.textContent = "Паролі не збігаються"; error.classList.remove("hidden"); return; }
    btn.disabled = true;
    try {
      await api("/api/auth/password", { method: "POST", body: { old_password: oldPw.value, new_password: newPw.value } });
      toast("Пароль змінено");
      await boot();
    } catch (err) { error.textContent = err.message; error.classList.remove("hidden"); } finally { btn.disabled = false; }
  });
  root.replaceChildren(h("div", { class: "login-wrap" }, h("div", { class: "login-card stack" },
    h("div", { class: "logo" }, h("div", { class: "logo-mark" }, "☁"), "Новий пароль"),
    h("p", { class: "muted" }, `${state.user.full_name || state.user.username}, вам видали тимчасовий пароль. Придумайте власний, щоб продовжити.`),
    form, h("button", { class: "ghost", onclick: logout }, "Вийти"))));
  oldPw.focus();
}

// ---------------------------------------------------------------- маршрути
const routes = {
  catalog: { title: "Середовища", icon: "🖥️", roles: ["student", "teacher", "admin"], render: viewCatalog },
  sessions: { title: "Мої столи", icon: "▶️", roles: ["student", "teacher", "admin"], render: viewMySessions },
  files: { title: "Мої файли", icon: "📁", roles: ["student", "teacher", "admin"], render: viewFiles },
  assignments: { title: "Завдання", icon: "📝", roles: ["student"], render: viewStudentAssignments },
  templates: { title: "Шаблони", icon: "🧩", roles: ["teacher", "admin"], section: "Викладач", render: viewTemplates },
  "teach-assignments": { title: "Завдання й роботи", icon: "📝", roles: ["teacher", "admin"], section: "Викладач", render: viewTeacherAssignments },
  groups: { title: "Мої групи", icon: "👥", roles: ["teacher"], section: "Викладач", render: viewTeacherGroups },
  students: { title: "Столи студентів", icon: "🛟", roles: ["teacher", "admin"], section: "Викладач", render: viewStudentSessions },
  dashboard: { title: "Навантаження", icon: "📊", roles: ["admin"], section: "Адміністратор", render: viewDashboard },
  users: { title: "Користувачі", icon: "👤", roles: ["admin"], section: "Адміністратор", render: viewUsers },
  "admin-groups": { title: "Групи", icon: "👥", roles: ["admin"], section: "Адміністратор", render: viewAdminGroups },
  settings: { title: "Ліміти й образи", icon: "⚙️", roles: ["admin"], section: "Адміністратор", render: viewSettings },
  audit: { title: "Журнал дій", icon: "📜", roles: ["admin"], section: "Адміністратор", render: viewAudit },
  profile: { title: "Профіль", icon: "🔑", roles: ["student", "teacher", "admin"], render: viewProfile },
};

function currentRoute() {
  const name = location.hash.replace(/^#\/?/, "").split("?")[0] || "catalog";
  const route = routes[name];
  return route && route.roles.includes(state.user.role) ? name : "catalog";
}

let refreshTimer = null;
async function renderRoute() {
  clearInterval(refreshTimer);
  const name = currentRoute();
  document.querySelectorAll(".nav a").forEach((a) => a.classList.toggle("active", a.dataset.route === name));
  document.querySelector(".sidebar")?.classList.remove("open");
  const main = document.querySelector(".main");
  main.replaceChildren(h("div", { class: "empty" }, "Завантаження…"));
  try {
    state.user = await api("/api/auth/me");
    if (state.user.must_change_password) return renderForcePassword();
    renderQuotaBanner();
    await routes[name].render(main);
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) return renderLogin("Сеанс завершився, увійдіть знову");
    main.replaceChildren(h("div", { class: "panel error-box" }, err.message));
  }
}

function renderQuotaBanner() {
  const box = document.querySelector(".quota-banner");
  const q = state.user.quota || {};
  const texts = {
    warn: `«Мої файли» майже заповнені: ${fmtBytes(q.used)} з ${fmtBytes(q.quota)}.`,
    over: `«Мої файли» перевищили квоту (${fmtBytes(q.used)} з ${fmtBytes(q.quota)}). Нові столи не запустяться — видаліть зайве.`,
    blocked: `«Мої файли» значно перевищили квоту (${fmtBytes(q.used)} з ${fmtBytes(q.quota)}). Столи зупинено — видаліть зайве.`,
  };
  box.classList.toggle("hidden", !texts[q.level]);
  box.className = `quota-banner ${q.level === "warn" ? "warn" : "danger"}${texts[q.level] ? "" : " hidden"}`;
  box.replaceChildren(texts[q.level] || "", " ", texts[q.level] ? h("a", { href: "#/files" }, "Відкрити «Мої файли»") : "");
}

function autoRefresh(fn, ms = 5000) {
  clearInterval(refreshTimer);
  refreshTimer = setInterval(() => { if (!document.hidden && !document.querySelector(".modal-back")) fn().catch(() => {}); }, ms);
}

function renderShell() {
  const nav = h("nav", { class: "nav" });
  let section = null;
  for (const [name, r] of Object.entries(routes)) {
    if (!r.roles.includes(state.user.role)) continue;
    if (r.section !== section && r.section) nav.append(h("div", { class: "nav-section" }, r.section));
    section = r.section;
    nav.append(h("a", { href: `#/${name}`, "data-route": name }, h("span", {}, r.icon), r.title));
  }
  const sidebar = h("aside", { class: "sidebar" },
    h("div", { class: "logo" }, h("div", { class: "logo-mark" }, "☁"), "Хмарний стіл"),
    nav,
    h("div", { class: "user-box" },
      h("div", { class: "name" }, state.user.full_name || state.user.username),
      h("div", {}, ROLE[state.user.role], state.user.group ? ` · ${state.user.group}` : ""),
      h("button", { onclick: logout }, "Вийти")));
  const main = h("main", { class: "main" });
  const banner = h("div", { class: "quota-banner hidden" });
  root.replaceChildren(h("div", { class: "shell" }, sidebar,
    h("div", {}, h("div", { style: "padding:.6rem 1rem 0" },
      h("button", { class: "menu-toggle", onclick: () => sidebar.classList.toggle("open") }, "☰ Меню")), banner, main)));
}

async function logout() {
  try { await api("/api/auth/logout", { method: "POST" }); } catch { /* ignore */ }
  state.user = null;
  location.hash = "";
  renderLogin();
}

function pageHead(title, subtitle, ...actions) {
  return h("div", { class: "page-head" },
    h("div", {}, h("h2", {}, title), subtitle ? h("p", { class: "muted" }, subtitle) : null),
    h("div", { class: "spacer" }), ...actions);
}

function openDesktop(sessionId) {
  window.open(`/session/${sessionId}`, `desktop-${sessionId}`);
}

// ---------------------------------------------------------------- студент: каталог
async function startTemplate(t) {
  const sess = await api("/api/sessions", { method: "POST", body: { template_id: t.id } });
  openDesktop(sess.id);
  return sess;
}

async function sessionAction(sess, action) {
  const labels = { pause: "призупинено", resume: "запущено", stop: "зупинено", reset: "скинуто до початкового стану" };
  if (action === "reset" && !await confirmDialog("Скинути середовище?",
    "Стіл буде створено заново з шаблону. Усе, що не збережено в папці «Мої_файли», зникне.", "Скинути")) return false;
  if (action === "delete") {
    if (!await confirmDialog("Видалити стіл?", "Контейнер буде видалено. Файли в «Мої_файли» залишаться.", "Видалити")) return false;
    await api(`/api/sessions/${sess.id}`, { method: "DELETE" });
    toast("Стіл видалено");
    return true;
  }
  await api(`/api/sessions/${sess.id}/${action}`, { method: "POST" });
  toast(`Стіл ${labels[action]}`);
  return true;
}

function sessionButtons(sess, after, { compact = false } = {}) {
  const run = async (action) => {
    try { if (await sessionAction(sess, action)) { await after(); return true; } } catch (e) { handleError(e); }
    return false;
  };
  const buttons = [];
  if (!compact && ["running", "creating"].includes(sess.status)) buttons.push(h("button", { class: "primary small", onclick: () => openDesktop(sess.id) }, "Відкрити"));
  if (!compact && ["paused", "stopped", "error"].includes(sess.status)) {
    buttons.push(h("button", { class: "small primary", onclick: async () => { if (await run("resume")) openDesktop(sess.id); } }, sess.status === "paused" ? "Продовжити" : "Запустити"));
  }
  if (sess.status === "running") buttons.push(h("button", { class: "small", onclick: () => run("pause") }, "Пауза"));
  if (["running", "paused"].includes(sess.status)) buttons.push(h("button", { class: "small", onclick: () => run("stop") }, "Зупинити"));
  buttons.push(h("button", { class: "small", onclick: () => run("reset"), title: "Повернути середовище до початкового стану" }, "Скинути"));
  if (!compact) buttons.push(h("button", { class: "small danger", onclick: () => run("delete") }, "Видалити"));
  return buttons;
}

async function viewCatalog(main) {
  const draw = async () => {
    const templates = await api("/api/templates");
    const bySubject = new Map();
    for (const t of templates) {
      const key = t.subject || "Інше";
      if (!bySubject.has(key)) bySubject.set(key, []);
      bySubject.get(key).push(t);
    }
    const content = templates.length ? [...bySubject].map(([subject, list]) => h("section", { style: "margin-bottom:1.5rem" },
      h("h3", { class: "muted" }, subject),
      h("div", { class: "cards" }, list.map((t) => {
        const s = t.session;
        const startBtn = h("button", { class: "primary" }, !s ? "Запустити" : { running: "Відкрити", creating: "Відкрити", paused: "Продовжити" }[s.status] || "Запустити");
        startBtn.onclick = async () => { startBtn.disabled = true; try { await startTemplate(t); await draw(); } catch (e) { handleError(e); } finally { startBtn.disabled = false; } };
        return h("div", { class: "card" },
          h("div", { class: "row" }, h("div", { class: `os os-${t.os_family}` }, OS_ICON[t.os_family] || OS_ICON.other),
            h("div", {}, h("h3", { style: "margin:0" }, t.name), h("div", { class: "meta" }, `${t.cpu} CPU · ${(t.memory_mb / 1024).toFixed(1)} ГБ RAM`)),
            h("span", { class: "spacer" }), s ? badge(s.status) : null, !t.is_active ? h("span", { class: "badge plain" }, "вимкнено") : null),
          h("div", { class: "desc" }, t.description || "Без опису"),
          t.created_by ? h("div", { class: "meta" }, `Викладач: ${t.created_by}`) : null,
          h("div", { class: "actions" }, startBtn, s ? sessionButtons(s, draw, { compact: true }) : null));
      })))) : [h("div", { class: "panel empty" }, state.user.role === "student" && !state.user.group
        ? "Вас ще не додали до групи. Зверніться до викладача або адміністратора."
        : "Для вашої групи ще немає середовищ. Зверніться до викладача.")];
    main.replaceChildren(pageHead("Середовища", "Оберіть середовище і запустіть робочий стіл. Файли з папки «Мої_файли» доступні в кожному столі."), ...content);
  };
  await draw();
  autoRefresh(draw, 8000);
}

async function viewMySessions(main) {
  const draw = async () => {
    const sessions = await api("/api/sessions");
    main.replaceChildren(pageHead("Мої робочі столи", "Неактивні столи автоматично зупиняються, щоб звільнити пам'ять сервера. Файли при цьому не зникають."),
      table(["Середовище", "Стан", "Остання активність", "Дії"], sessions.map((s) => [
        h("div", {}, h("strong", {}, s.template.name), h("div", { class: "muted small" }, s.template.subject)),
        h("div", {}, badge(s.status), s.error ? h("div", { class: "muted small" }, s.error) : null),
        ago(s.last_activity),
        h("div", { class: "row" }, sessionButtons(s, draw)),
      ]), "У вас ще немає запущених столів. Відкрийте «Середовища», щоб почати."));
  };
  await draw();
  autoRefresh(draw);
}

// ---------------------------------------------------------------- файли
async function viewFiles(main) {
  let path = new URLSearchParams(location.hash.split("?")[1] || "").get("path") || "";
  const draw = async () => {
    const data = await api(`/api/files?path=${encodeURIComponent(path)}`);
    const go = (p) => (e) => { e.preventDefault(); path = p; draw().catch(handleError); };
    const parts = data.path ? data.path.split("/") : [];
    const crumbs = h("div", { class: "breadcrumbs" }, h("a", { href: "#", onclick: go("") }, "Мої файли"),
      parts.map((p, i) => [" / ", h("a", { href: "#", onclick: go(parts.slice(0, i + 1).join("/")) }, p)]));
    const fileInput = h("input", { type: "file", multiple: true, class: "hidden", onchange: async () => {
      for (const f of fileInput.files) {
        const form = new FormData(); form.append("path", path); form.append("file", f);
        try { await api("/api/files/upload", { method: "POST", form }); toast(`Завантажено: ${f.name}`); } catch (e) { handleError(e); }
      }
      await draw();
    } });
    const pct = Math.min(100, Math.round((data.used / data.quota) * 100));
    main.replaceChildren(
      pageHead("Мої файли", `У робочому столі це папка ${data.desktop_path.replace("/home/kasm-user", "~")}. Вміст однаковий у всіх середовищах і зберігається між сесіями.`,
        h("button", { onclick: async () => {
          const name = await modal("Нова папка", (b) => { const i = h("input", { required: true }); b.append(field("Назва", i)); return () => i.value; },
            { submitText: "Створити", onSubmit: async (name) => { await api("/api/files/mkdir", { method: "POST", body: { path, name } }); return name; } });
          if (name) await draw();
        } }, "📁 Нова папка"),
        h("button", { class: "primary", onclick: () => fileInput.click() }, "⬆ Завантажити"), fileInput),
      h("div", { class: "panel", style: "margin-bottom:1rem" },
        h("div", { class: "row" }, h("span", {}, `Використано ${fmtBytes(data.used)} з ${fmtBytes(data.quota)}`), h("span", { class: "spacer" }), h("span", { class: "muted" }, `${pct}%`)),
        h("div", { class: "bar" + (pct > 90 ? " danger" : pct > 75 ? " warn" : "") }, h("div", { style: `width:${pct}%` }))),
      h("div", { style: "margin-bottom:.6rem" }, crumbs),
      table(["Назва", "Розмір", "Змінено", ""], data.items.map((item) => [
        item.is_dir ? h("a", { href: "#", onclick: go(item.path) }, `📁 ${item.name}`) : h("span", {}, `📄 ${item.name}`),
        item.is_dir ? "—" : fmtBytes(item.size),
        fmtDate(new Date(item.modified * 1000).toISOString()),
        h("div", { class: "row" },
          item.is_dir ? null : h("a", { class: "btn small", href: `/api/files/download?path=${encodeURIComponent(item.path)}` }, "Завантажити"),
          h("button", { class: "small danger", onclick: async () => {
            if (!await confirmDialog("Видалити?", `«${item.name}» буде видалено назавжди.`, "Видалити")) return;
            try { await api(`/api/files?path=${encodeURIComponent(item.path)}`, { method: "DELETE" }); await draw(); } catch (e) { handleError(e); }
          } }, "Видалити")),
      ]), "Тут поки порожньо. Збережіть файл у столі в папку ~/Мої_файли або завантажте його сюди."));
  };
  await draw();
}

// ---------------------------------------------------------------- автоперевірка
const CHECK = {
  pending: ["creating", "⏳ Перевіряється…"], passed: ["running", "✔ Автоперевірка пройдена"],
  failed: ["error", "✘ Автоперевірка не пройдена"], error: ["paused", "⚠ Перевірку не вдалося виконати"],
  hidden: ["plain", "🤖 Перевірено (результат бачить викладач)"],
};

function checkBadge(status) {
  const [cls, text] = CHECK[status] || ["plain", status];
  return h("span", { class: `badge ${cls}` }, text);
}

function checkBlock(sub) {
  return h("div", {}, checkBadge(sub.check_status),
    sub.check_output ? h("details", { style: "margin-top:.3rem" }, h("summary", { class: "small muted" }, "Вивід перевірки"),
      h("pre", { class: "log" }, sub.check_output)) : null);
}

// ---------------------------------------------------------------- студент: завдання
async function viewStudentAssignments(main) {
  const draw = async () => {
    const items = await api("/api/assignments");
    if (items.some((a) => a.submission?.check_status === "pending")) setTimeout(() => draw().catch(() => {}), 3000);
    main.replaceChildren(pageHead("Завдання", "Збережіть результат у «Мої_файли» і натисніть «Здати». Здати можна й просто зі столу."),
      items.length ? h("div", { class: "cards" }, items.map((a) => {
        const s = a.submission;
        const overdue = a.due_at && new Date(a.due_at) < new Date() && !s;
        return h("div", { class: "card" },
          h("div", { class: "row" }, h("h3", { style: "margin:0" }, a.title), h("span", { class: "spacer" }),
            s ? (s.grade ? h("span", { class: "badge running" }, `Оцінка: ${s.grade}`) : h("span", { class: "badge creating" }, "Здано"))
              : h("span", { class: "badge" + (overdue ? " error" : "") }, overdue ? "Прострочено" : "Не здано")),
          h("div", { class: "desc" }, a.description),
          h("div", { class: "meta" }, `Термін: ${fmtDate(a.due_at)}`, a.template ? ` · Середовище: ${a.template.name}` : ""),
          s ? h("div", { class: "meta" }, `Здано ${fmtDate(s.submitted_at)}: ${s.files.join(", ")}`) : null,
          s && s.check_status ? checkBlock(s) : (a.has_check && !s ? h("div", { class: "meta" }, "🤖 Роботу автоматично перевірить скрипт викладача") : null),
          s && s.feedback ? h("div", { class: "panel small", style: "box-shadow:none;background:#f6f8fb" }, h("strong", {}, "Відгук викладача: "), s.feedback) : null,
          h("div", { class: "actions" },
            a.template ? h("button", { onclick: async () => { try { await startTemplate(a.template); } catch (e) { handleError(e); } } }, "Відкрити середовище") : null,
            h("button", { class: "primary", onclick: async () => { if (await submitDialog({ assignmentId: a.id })) await draw(); } }, s ? "Здати повторно" : "Здати")));
      })) : h("div", { class: "panel empty" }, "Завдань поки немає."));
  };
  await draw();
}

// ---------------------------------------------------------------- викладач: шаблони
async function templateForm(t) {
  const [images, groups] = await Promise.all([
    api("/api/templates/images"),
    state.user.role === "admin" ? api("/api/admin/groups") : api("/api/teacher/groups"),
  ]);
  const v = t || { name: "", subject: "", description: "", image: images[0]?.image, cpu: 1, memory_mb: 2048, shm_mb: 512, env: {}, is_active: true, groups: [] };
  return modal(t ? "Редагувати шаблон" : "Новий шаблон середовища", (body) => {
    const name = h("input", { value: v.name, required: true, placeholder: "напр. Мережі — лабораторна 3" });
    const subject = h("input", { value: v.subject, placeholder: "напр. Комп'ютерні мережі" });
    const description = h("textarea", { placeholder: "Що встановлено, як працювати, що здати" }, v.description);
    const image = h("select", {}, images.map((i) => h("option", { value: i.image, selected: i.image === v.image }, `${i.label} — ${i.image}`)));
    const cpu = h("input", { type: "number", step: "0.25", min: "0.25", value: v.cpu });
    const mem = h("input", { type: "number", step: "256", min: "256", value: v.memory_mb });
    const startUrl = h("input", { value: (v.env || {}).LAUNCH_URL || "", placeholder: "https://… (необов'язково)" });
    const active = h("input", { type: "checkbox", checked: v.is_active });
    const groupChecks = groups.map((g) => ({ id: g.id, el: h("input", { type: "checkbox", checked: v.groups.some((x) => x.id === g.id) }), name: g.name }));
    body.append(field("Назва", name), field("Предмет", subject), field("Опис для студентів", description),
      field("Базовий образ", image, "Список образів задає адміністратор"),
      h("div", { class: "grid2" }, field("CPU (ядер)", cpu), field("Пам'ять (МБ)", mem)),
      field("Стартова сторінка браузера", startUrl, "Для образів Kasm з браузером: змінна LAUNCH_URL"),
      field("Групи, яким доступний шаблон", h("div", { class: "checks" }, groupChecks.length ? groupChecks.map((g) => h("label", {}, g.el, g.name)) : h("span", { class: "muted" }, "У вас ще немає груп"))),
      h("div", { class: "checks" }, h("label", {}, active, "Шаблон активний (видно студентам)")));
    return () => {
      const env = { ...(v.env || {}) };
      if (startUrl.value.trim()) env.LAUNCH_URL = startUrl.value.trim(); else delete env.LAUNCH_URL;
      return { name: name.value, subject: subject.value, description: description.value, image: image.value,
        cpu: Number(cpu.value), memory_mb: Number(mem.value), shm_mb: v.shm_mb || 512, env, is_active: active.checked,
        group_ids: groupChecks.filter((g) => g.el.checked).map((g) => g.id) };
    };
  }, { onSubmit: (data) => api(t ? `/api/templates/${t.id}` : "/api/templates", { method: t ? "PUT" : "POST", body: data }) });
}

async function viewTemplates(main) {
  const draw = async () => {
    const items = await api("/api/templates/manage");
    main.replaceChildren(pageHead("Шаблони середовищ", "Підготуйте середовище під предмет і призначте його групам.",
      h("button", { class: "primary", onclick: async () => { if (await templateForm()) { toast("Шаблон створено"); await draw(); } } }, "+ Новий шаблон")),
    table(["Шаблон", "Образ", "Ресурси", "Групи", "Автор", ""], items.map((t) => [
      h("div", {}, h("strong", {}, `${OS_ICON[t.os_family] || ""} ${t.name}`), h("div", { class: "muted small" }, t.subject), !t.is_active ? h("span", { class: "badge plain" }, "вимкнено") : null),
      h("code", { class: "small" }, t.image),
      `${t.cpu} CPU · ${t.memory_mb} МБ`,
      t.groups.map((g) => g.name).join(", ") || "—",
      t.created_by || "—",
      t.editable ? h("div", { class: "row" },
        h("button", { class: "small", onclick: async () => { if (await templateForm(t)) { toast("Збережено"); await draw(); } } }, "Змінити"),
        h("button", { class: "small danger", onclick: async () => {
          if (!await confirmDialog("Видалити шаблон?", `«${t.name}» буде видалено.`, "Видалити")) return;
          try { await api(`/api/templates/${t.id}`, { method: "DELETE" }); await draw(); } catch (e) { handleError(e); }
        } }, "Видалити")) : h("span", { class: "muted small" }, "чужий"),
    ]), "Шаблонів ще немає"));
  };
  await draw();
}

// ---------------------------------------------------------------- викладач: завдання й здані роботи
const CHECK_EXAMPLE = `# Скрипт bash. Здані файли — у поточній папці (/work), лише для читання. Мережі немає.
# Код 0 — перевірку пройдено; будь-який інший — ні. Усе виведене побачить викладач (і студент, якщо дозволено).
set -e
test -f lab1.py || { echo "Немає файлу lab1.py"; exit 1; }
echo "3 4" | python3 lab1.py > /tmp/out.txt
grep -qx "7" /tmp/out.txt && echo "Тест 1: OK"`;

async function assignmentForm(a) {
  const [groups, templates, checkImages] = await Promise.all([
    state.user.role === "admin" ? api("/api/admin/groups") : api("/api/teacher/groups"),
    api("/api/templates/manage"),
    api("/api/assignments/check-images"),
  ]);
  if (!groups.length) throw new Error("У вас немає груп. Попросіть адміністратора призначити групи.");
  const toLocal = (iso) => { if (!iso) return ""; const d = new Date(iso); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 16); };
  return modal(a ? "Редагувати завдання" : "Нове завдання", (body) => {
    const title = h("input", { value: a?.title || "", required: true });
    const desc = h("textarea", {}, a?.description || "");
    const group = h("select", {}, groups.map((g) => h("option", { value: g.id, selected: a?.group.id === g.id }, g.name)));
    const tpl = h("select", {}, h("option", { value: "" }, "— без середовища —"),
      templates.map((t) => h("option", { value: t.id, selected: a?.template?.id === t.id }, t.name)));
    const due = h("input", { type: "datetime-local", value: toLocal(a?.due_at) });
    const script = h("textarea", { style: "min-height:150px;font-family:monospace;font-size:.85rem", placeholder: CHECK_EXAMPLE }, a?.check_script || "");
    const image = h("select", {}, checkImages.map((i) => h("option", { value: i, selected: (a?.check_image || checkImages[0]) === i }, i)));
    const timeout = h("input", { type: "number", min: "5", max: "600", value: a?.check_timeout || 60 });
    const show = h("input", { type: "checkbox", checked: a ? a.show_check_to_student : true });
    const example = h("button", { type: "button", class: "small", onclick: () => { if (!script.value.trim()) script.value = CHECK_EXAMPLE; } }, "Вставити приклад");
    body.append(field("Назва", title), field("Умова завдання", desc), h("div", { class: "grid2" }, field("Група", group), field("Середовище", tpl)), field("Термін здачі", due),
      h("details", { open: Boolean(a?.check_script) }, h("summary", {}, "🤖 Автоперевірка (необов'язково)"),
        h("div", { style: "margin-top:.6rem" }, field("Скрипт перевірки", script, h("span", {}, "Виконується після кожної здачі в окремому контейнері без мережі. ", example)),
          h("div", { class: "grid2" }, field("Образ", image), field("Ліміт часу, с", timeout)),
          h("div", { class: "checks" }, h("label", {}, show, "Показувати студенту результат перевірки")))));
    return () => ({ title: title.value, description: desc.value, group_id: Number(group.value),
      template_id: tpl.value ? Number(tpl.value) : null, due_at: due.value ? new Date(due.value).toISOString() : null,
      check_script: script.value, check_image: image.value, check_timeout: Number(timeout.value), show_check_to_student: show.checked });
  }, { onSubmit: (data) => api(a ? `/api/assignments/${a.id}` : "/api/assignments", { method: a ? "PUT" : "POST", body: data }) });
}

async function gradeForm(sub) {
  return modal(`Оцінити: ${sub.student.full_name || sub.student.username}`, (body) => {
    const grade = h("input", { value: sub.grade, placeholder: "напр. 10/12 або «зараховано»" });
    const feedback = h("textarea", { placeholder: "Що добре, що виправити" }, sub.feedback);
    body.append(sub.comment ? h("p", {}, h("strong", {}, "Коментар студента: "), sub.comment) : null,
      h("p", {}, "Файли: ", sub.files.map((f, i) => [i ? ", " : "", h("a", { href: `/api/assignments/submissions/${sub.id}/files/${encodeURIComponent(f)}` }, f)])),
      sub.check_status ? h("div", { class: "field" }, checkBadge(sub.check_status), sub.check_output ? h("pre", { class: "log" }, sub.check_output) : null) : null,
      field("Оцінка", grade), field("Відгук", feedback));
    return () => ({ grade: grade.value, feedback: feedback.value });
  }, { onSubmit: (data) => api(`/api/assignments/submissions/${sub.id}/grade`, { method: "PUT", body: data }) });
}

async function showSubmissions(a) {
  const data = await api(`/api/assignments/${a.id}/submissions`);
  const sessions = await api("/api/teacher/sessions");
  await modal(`Здані роботи: ${a.title}`, (body) => {
    const draw = async () => {
      const fresh = await api(`/api/assignments/${a.id}/submissions`);
      body.replaceChildren(content(fresh));
    };
    const recheckAll = h("button", { class: "small", onclick: async () => {
      try { const r = await api(`/api/assignments/${a.id}/recheck`, { method: "POST" }); toast(`У черзі: ${r.queued}`); await draw(); } catch (e) { handleError(e); }
    } }, "🤖 Перевірити всіх заново");
    const content = (d) => h("div", {}, d.assignment.has_check ? h("div", { class: "row", style: "margin-bottom:.6rem" },
      h("span", { class: "muted small" }, `Автоперевірку пройшли: ${d.assignment.stats.passed} з ${d.assignment.stats.submitted}`), h("span", { class: "spacer" }), recheckAll) : null,
    table(["Студент", "Стан", "Файли", "Перевірка", "Оцінка", ""], d.rows.map((r) => {
      const s = r.submission;
      const desk = sessions.find((x) => x.user.id === r.student.id && x.status === "running");
      return [
        r.student.full_name || r.student.username,
        s ? h("div", {}, h("span", { class: "badge " + (s.late ? "paused" : "running") }, s.late ? "Із запізненням" : "Здано"), h("div", { class: "muted small" }, fmtDate(s.submitted_at))) : h("span", { class: "badge" }, "Не здано"),
        s ? s.files.map((f) => h("div", {}, h("a", { href: `/api/assignments/submissions/${s.id}/files/${encodeURIComponent(f)}` }, f))) : "—",
        s?.check_status ? checkBadge(s.check_status) : "—",
        s?.grade || "—",
        h("div", { class: "row" },
          s ? h("button", { class: "small primary", onclick: async () => { if (await gradeForm(s)) await draw(); } }, "Оцінити") : null,
          s && d.assignment.has_check ? h("button", { class: "small", title: "Перевірити заново", onclick: async () => {
            try { await api(`/api/assignments/submissions/${s.id}/recheck`, { method: "POST" }); await draw(); } catch (e) { handleError(e); }
          } }, "🤖") : null,
          desk ? h("button", { class: "small", onclick: () => openDesktop(desk.id), title: "Підключитися до столу студента" }, "🛟 Стіл") : null),
      ];
    }), "У групі немає студентів"));
    body.append(content(data));
    const poll = setInterval(() => {
      if (!body.isConnected) return clearInterval(poll);
      if (body.querySelector(".badge.creating")) draw().catch(() => {});
    }, 3000);
  }, { wide: true });
}

async function viewTeacherAssignments(main) {
  const draw = async () => {
    const items = await api("/api/assignments");
    main.replaceChildren(pageHead("Завдання й здані роботи", "Створюйте завдання для груп, переглядайте й оцінюйте роботи.",
      h("button", { class: "primary", onclick: async () => { try { if (await assignmentForm()) await draw(); } catch (e) { handleError(e); } } }, "+ Нове завдання")),
    table(["Завдання", "Група", "Термін", "Здано", ""], items.map((a) => [
      h("div", {}, h("strong", {}, a.title), a.template ? h("div", { class: "muted small" }, a.template.name) : null),
      a.group.name, fmtDate(a.due_at),
      h("div", {}, `${a.stats.submitted} / ${a.stats.students}` + (a.stats.graded ? ` (оцінено ${a.stats.graded})` : ""),
        a.has_check ? h("div", { class: "muted small" }, `🤖 пройшли: ${a.stats.passed}`) : null),
      h("div", { class: "row" },
        h("button", { class: "small primary", onclick: () => showSubmissions(a).catch(handleError) }, "Роботи"),
        h("button", { class: "small", onclick: async () => { try { if (await assignmentForm(a)) await draw(); } catch (e) { handleError(e); } } }, "Змінити"),
        h("button", { class: "small danger", onclick: async () => {
          if (!await confirmDialog("Видалити завдання?", "Разом із ним зникнуть записи про здані роботи.", "Видалити")) return;
          await api(`/api/assignments/${a.id}`, { method: "DELETE" }).catch(handleError); await draw();
        } }, "Видалити")),
    ]), "Завдань ще немає"));
  };
  await draw();
}

async function resetPassword(student) {
  if (!await confirmDialog("Скинути пароль?", `${student.full_name || student.username} отримає тимчасовий пароль і має змінити його при вході. Поточні входи студента буде завершено.`, "Скинути")) return;
  const res = await api(`/api/teacher/students/${student.id}/reset-password`, { method: "POST" });
  await modal("Тимчасовий пароль", (body) => {
    body.append(h("p", {}, `Логін: `, h("strong", {}, res.username)),
      h("p", {}, "Пароль: ", h("code", { style: "font-size:1.3rem;letter-spacing:.08em" }, res.temporary_password)),
      h("p", { class: "muted small" }, "Пароль показано лише один раз. Продиктуйте його студенту — після входу він придумає власний."));
  });
}

async function viewTeacherGroups(main) {
  const groups = await api("/api/teacher/groups");
  main.replaceChildren(pageHead("Мої групи", "Групи призначає адміністратор."),
    ...(groups.length ? groups.map((g) => h("section", { style: "margin-bottom:1.2rem" },
      h("h3", {}, `${g.name} `, h("span", { class: "muted small" }, `${g.student_count} студ.`)),
      table(["Студент", "Логін", ""], g.students.map((s) => [s.full_name || "—", s.username,
        h("button", { class: "small", onclick: () => resetPassword(s).catch(handleError) }, "🔑 Скинути пароль")]), "У групі немає студентів")))
      : [h("div", { class: "panel empty" }, "Вам ще не призначили групи.")]));
}

async function viewStudentSessions(main) {
  const draw = async () => {
    const sessions = await api("/api/teacher/sessions");
    main.replaceChildren(pageHead("Столи студентів", "Підключіться до столу студента, щоб показати, що виправити. Кожне підключення записується в журнал."),
      table(["Студент", "Група", "Середовище", "Стан", "Активність", ""], sessions.map((s) => [
        s.user.full_name || s.user.username, s.user.group || "—", s.template.name, badge(s.status), ago(s.last_activity),
        h("div", { class: "row" },
          s.status === "running" ? h("button", { class: "small primary", onclick: () => openDesktop(s.id) }, "🛟 Підключитися") : null,
          ["running", "paused"].includes(s.status) ? h("button", { class: "small", onclick: async () => { await sessionAction(s, "stop").catch(handleError); await draw(); } }, "Зупинити") : null,
          h("button", { class: "small", onclick: async () => { if (await sessionAction(s, "reset").catch(handleError)) await draw(); } }, "Скинути")),
      ]), "Студенти ваших груп ще не запускали столи"));
  };
  await draw();
  autoRefresh(draw, 10000);
}

// ---------------------------------------------------------------- адміністратор
function statCard(title, value, sub, pct) {
  return h("div", { class: "stat" }, h("div", { class: "muted small" }, title), h("div", { class: "value" }, value),
    sub ? h("div", { class: "muted small" }, sub) : null,
    pct !== undefined ? h("div", { class: "bar" + (pct > 90 ? " danger" : pct > 75 ? " warn" : "") }, h("div", { style: `width:${Math.min(100, pct)}%` })) : null);
}

async function viewDashboard(main) {
  const draw = async () => {
    const [s, settings, sessions] = await Promise.all([api("/api/admin/stats"), api("/api/admin/settings"), api("/api/admin/sessions")]);
    const mem = s.memory || {};
    const memPct = mem.total ? Math.round((1 - mem.available / mem.total) * 100) : 0;
    const diskPct = s.disk ? Math.round((s.disk.used / s.disk.total) * 100) : 0;
    const loadPct = s.cpu_count ? Math.round((s.load[0] / s.cpu_count) * 100) : 0;
    const sessPct = Math.round((s.active_sessions / settings.max_active_sessions) * 100);
    main.replaceChildren(pageHead("Навантаження сервера", `Драйвер: ${s.driver}. Оновлюється автоматично.`),
      h("div", { class: "stats" },
        statCard("Активні столи", `${s.active_sessions} / ${settings.max_active_sessions}`, `працює ${s.sessions.running || 0}, пауза ${s.sessions.paused || 0}`, sessPct),
        statCard("Пам'ять", `${memPct}%`, mem.total ? `вільно ${fmtBytes(mem.available)} з ${fmtBytes(mem.total)}` : "немає даних", memPct),
        statCard("Процесор (load 1 хв)", s.load[0], `${s.cpu_count} ядер · 5 хв: ${s.load[1]} · 15 хв: ${s.load[2]}`, loadPct),
        statCard("Диск сховища", `${diskPct}%`, s.disk ? `вільно ${fmtBytes(s.disk.free)}` : "", diskPct),
        statCard("Користувачі", s.users, `входів за 24 год: ${s.logins_24h}`)),
      h("h3", {}, "Усі робочі столи"),
      table(["Користувач", "Середовище", "Стан", "Активність", ""], sessions.map((x) => [
        `${x.user.full_name || x.user.username} (${x.user.username})`, x.template.name, badge(x.status), ago(x.last_activity),
        h("div", { class: "row" },
          x.status === "running" ? h("button", { class: "small", onclick: () => openDesktop(x.id) }, "Відкрити") : null,
          ["running", "paused", "creating"].includes(x.status) ? h("button", { class: "small danger", onclick: async () => {
            await api(`/api/admin/sessions/${x.id}/stop`, { method: "POST" }).catch(handleError); await draw();
          } }, "Зупинити") : null),
      ]), "Столів немає"));
  };
  await draw();
  autoRefresh(draw, 10000);
}

async function userForm(u, groups) {
  return modal(u ? `Користувач ${u.username}` : "Новий користувач", (body) => {
    const username = h("input", { value: u?.username || "", required: true, pattern: "[a-z0-9][a-z0-9._\\-]+" });
    const fullName = h("input", { value: u?.full_name || "" });
    const email = h("input", { type: "email", value: u?.email || "" });
    const role = h("select", {}, Object.entries(ROLE).map(([k, v]) => h("option", { value: k, selected: (u?.role || "student") === k }, v)));
    const group = h("select", {}, h("option", { value: "" }, "—"), groups.map((g) => h("option", { value: g.id, selected: u?.group_id === g.id }, g.name)));
    const teaching = groups.map((g) => ({ id: g.id, el: h("input", { type: "checkbox", checked: (u?.teaching || []).some((t) => t.id === g.id) }), name: g.name }));
    const password = h("input", { type: "password", autocomplete: "new-password", placeholder: u ? "залиште порожнім, щоб не змінювати" : "мін. 8 символів, літери й цифри" });
    const quota = h("input", { type: "number", min: "0", value: u?.quota_mb || "", placeholder: "за замовчуванням" });
    const active = h("input", { type: "checkbox", checked: u ? u.is_active : true });
    const groupField = field("Група студента", group);
    const teachField = field("Групи викладача", h("div", { class: "checks" }, teaching.map((t) => h("label", {}, t.el, t.name))));
    const sync = () => { groupField.classList.toggle("hidden", role.value !== "student"); teachField.classList.toggle("hidden", role.value !== "teacher"); };
    role.addEventListener("change", sync);
    body.append(h("div", { class: "grid2" }, field("Логін", username), field("ПІБ", fullName), field("Роль", role), field("Email", email)),
      groupField, teachField, h("div", { class: "grid2" }, field("Пароль", password), field("Квота диска, МБ", quota)),
      h("div", { class: "checks" }, h("label", {}, active, "Акаунт активний")));
    sync();
    return () => ({ username: username.value, full_name: fullName.value, email: email.value, role: role.value,
      group_id: group.value ? Number(group.value) : null, teaching_ids: teaching.filter((t) => t.el.checked).map((t) => t.id),
      password: password.value || null, quota_mb: quota.value ? Number(quota.value) : null, is_active: active.checked });
  }, { onSubmit: (data) => api(u ? `/api/admin/users/${u.id}` : "/api/admin/users", { method: u ? "PUT" : "POST", body: data }) });
}

async function viewUsers(main) {
  let q = "";
  const draw = async () => {
    const [users, groups] = await Promise.all([api(`/api/admin/users?q=${encodeURIComponent(q)}`), api("/api/admin/groups")]);
    const search = h("input", { placeholder: "Пошук за логіном або ПІБ", value: q, style: "max-width:280px" });
    search.addEventListener("change", () => { q = search.value; draw().catch(handleError); });
    main.replaceChildren(pageHead("Користувачі", `Усього: ${users.length}`, search,
      h("button", { onclick: async () => {
        const res = await modal("Імпорт з CSV", (body) => {
          const ta = h("textarea", { style: "min-height:200px;font-family:monospace", required: true },
            "username,full_name,password,role,group\nivan.petrenko,Петренко Іван,Start2026a,student,КН-21");
          body.append(h("p", { class: "muted small" }, "Перший рядок — заголовки. Групи, яких немає, буде створено."), ta);
          return () => ta.value;
        }, { submitText: "Імпортувати", onSubmit: (csv) => api("/api/admin/users/import", { method: "POST", body: { csv } }) });
        if (res) { toast(`Створено: ${res.created}`); if (res.errors.length) toast(res.errors.slice(0, 5).join("\n"), true); await draw(); }
      } }, "⬆ Імпорт CSV"),
      h("button", { class: "primary", onclick: async () => { if (await userForm(null, groups)) { toast("Користувача створено"); await draw(); } } }, "+ Користувач")),
    table(["Логін", "ПІБ", "Роль", "Група", "Диск", "Останній вхід", ""], users.map((u) => [
      h("span", {}, u.username, !u.is_active ? h("span", { class: "badge plain", style: "margin-left:.4rem" }, "вимкнено") : null,
        u.must_change_password ? h("span", { class: "badge plain", style: "margin-left:.4rem", title: "Має змінити тимчасовий пароль" }, "тимч. пароль") : null),
      u.full_name || "—", ROLE[u.role], u.role === "teacher" ? u.teaching.map((g) => g.name).join(", ") || "—" : u.group || "—",
      u.disk_used_bytes == null ? "—" : fmtBytes(u.disk_used_bytes),
      fmtDate(u.last_login),
      h("div", { class: "row" },
        h("button", { class: "small", onclick: async () => { if (await userForm(u, groups)) { toast("Збережено"); await draw(); } } }, "Змінити"),
        u.id !== state.user.id ? h("button", { class: "small danger", onclick: async () => {
          if (!await confirmDialog("Видалити користувача?", `${u.username}: буде видалено акаунт і його столи. Файли на диску залишаться.`, "Видалити")) return;
          await api(`/api/admin/users/${u.id}`, { method: "DELETE" }).catch(handleError); await draw();
        } }, "Видалити") : null),
    ])));
  };
  await draw();
}

async function viewAdminGroups(main) {
  const draw = async () => {
    const groups = await api("/api/admin/groups");
    const form = (g) => modal(g ? "Редагувати групу" : "Нова група", (body) => {
      const name = h("input", { value: g?.name || "", required: true, placeholder: "напр. КН-21" });
      const desc = h("input", { value: g?.description || "" });
      body.append(field("Назва", name), field("Опис", desc));
      return () => ({ name: name.value, description: desc.value });
    }, { onSubmit: (data) => api(g ? `/api/admin/groups/${g.id}` : "/api/admin/groups", { method: g ? "PUT" : "POST", body: data }) });
    main.replaceChildren(pageHead("Групи", "Викладачів призначають групам у картці користувача.",
      h("button", { class: "primary", onclick: async () => { if (await form()) await draw(); } }, "+ Група")),
    table(["Група", "Опис", "Студентів", "Викладачі", ""], groups.map((g) => [
      h("strong", {}, g.name), g.description || "—", g.student_count, g.teachers.map((t) => t.full_name || t.username).join(", ") || "—",
      h("div", { class: "row" },
        h("button", { class: "small", onclick: async () => { if (await form(g)) await draw(); } }, "Змінити"),
        h("button", { class: "small danger", onclick: async () => {
          if (!await confirmDialog("Видалити групу?", g.name, "Видалити")) return;
          await api(`/api/admin/groups/${g.id}`, { method: "DELETE" }).catch(handleError); await draw();
        } }, "Видалити")),
    ]), "Груп ще немає"));
  };
  await draw();
}

async function viewSettings(main) {
  const s = await api("/api/admin/settings");
  const num = (key, step = 1) => h("input", { type: "number", step, value: s[key], "data-key": key });
  const inputs = {
    max_active_sessions: num("max_active_sessions"), max_sessions_per_user: num("max_sessions_per_user"),
    idle_timeout_minutes: num("idle_timeout_minutes"), default_quota_mb: num("default_quota_mb"),
    max_cpu: num("max_cpu", 0.25), max_memory_mb: num("max_memory_mb", 256),
    quota_hard_percent: num("quota_hard_percent", 5), max_container_disk_mb: num("max_container_disk_mb", 512),
  };
  const catalog = h("textarea", { style: "min-height:220px;font-family:monospace;font-size:.85rem" }, JSON.stringify(s.image_catalog, null, 2));
  const checkImages = h("input", { value: (s.check_images || []).join(", ") });
  const save = h("button", { class: "primary" }, "Зберегти");
  save.onclick = async () => {
    try {
      const body = Object.fromEntries(Object.entries(inputs).map(([k, el]) => [k, Number(el.value)]));
      try { body.image_catalog = JSON.parse(catalog.value); } catch { throw new Error("Каталог образів: некоректний JSON"); }
      body.check_images = checkImages.value.split(",").map((x) => x.trim()).filter(Boolean);
      await api("/api/admin/settings", { method: "PUT", body });
      toast("Налаштування збережено");
    } catch (e) { handleError(e); }
  };
  main.replaceChildren(pageHead("Ліміти й образи", "Орієнтир: кожен активний стіл займає 1–2 ГБ RAM. Ліміт столів = (RAM сервера − 4 ГБ) / 1.5 ГБ.", save),
    h("div", { class: "panel" },
      h("div", { class: "grid2" },
        field("Максимум активних столів на сервері", inputs.max_active_sessions, "Коли ліміт досягнуто, новий стіл не запуститься"),
        field("Столів одночасно на користувача", inputs.max_sessions_per_user),
        field("Автовимкнення при простої, хв", inputs.idle_timeout_minutes, "Стіл без активності буде зупинено (файли зберігаються)"),
        field("Квота диска студента за замовчуванням, МБ", inputs.default_quota_mb),
        field("Максимум CPU для шаблону", inputs.max_cpu),
        field("Максимум RAM для шаблону, МБ", inputs.max_memory_mb),
        field("Зупиняти столи, коли «Мої файли» перевищують квоту на, %", inputs.quota_hard_percent, "100 — одразу при перевищенні; 120 — із запасом 20%"),
        field("Максимум запису контейнера поза «Моїми файлами», МБ", inputs.max_container_disk_mb, "Понад це стіл зупиняється і при наступному запуску створюється заново")),
      field("Образи для автоперевірки робіт (через кому)", checkImages, "Викладачі можуть обирати лише ці образи; їх треба завантажити на сервер: docker pull …"),
      field("Каталог дозволених образів (JSON)", catalog, "Викладачі можуть створювати шаблони лише з цих образів. os: ubuntu, kali, vscode, mysql, windows, other")));
}

async function viewAudit(main) {
  let action = "";
  let username = "";
  const draw = async () => {
    const rows = await api(`/api/admin/audit?limit=300&action=${encodeURIComponent(action)}&username=${encodeURIComponent(username)}`);
    const actionSel = h("select", { style: "max-width:220px", onchange: (e) => { action = e.target.value; draw().catch(handleError); } },
      ["", "login", "login_failed", "logout", "password_change", "password_reset", "session_start", "session_stop", "session_idle_stop",
        "session_quota_stop", "session_disk_stop", "session_reset", "session_connect_helper", "submission", "check_rerun", "user_create", "settings_update"]
        .map((a) => h("option", { value: a, selected: a === action }, a || "усі дії")));
    const userInput = h("input", { placeholder: "логін", value: username, style: "max-width:160px", onchange: (e) => { username = e.target.value; draw().catch(handleError); } });
    main.replaceChildren(pageHead("Журнал дій", "Хто, коли і з яким середовищем працював (останні 300 записів).", userInput, actionSel),
      table(["Час", "Користувач", "Дія", "Деталі", "IP"], rows.map((r) => [fmtDate(r.created_at), r.username || "—", h("code", {}, r.action), r.details, r.ip]), "Записів немає"));
  };
  await draw();
}

async function viewProfile(main) {
  const u = await api("/api/auth/me");
  const oldPw = h("input", { type: "password", autocomplete: "current-password", required: true });
  const newPw = h("input", { type: "password", autocomplete: "new-password", required: true });
  const form = h("form", { class: "panel", style: "max-width:420px" }, h("h3", {}, "Змінити пароль"), field("Поточний пароль", oldPw), field("Новий пароль", newPw, "Щонайменше 8 символів, літери й цифри"), h("button", { class: "primary", type: "submit" }, "Змінити"));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    try { await api("/api/auth/password", { method: "POST", body: { old_password: oldPw.value, new_password: newPw.value } }); toast("Пароль змінено"); form.reset(); } catch (err) { handleError(err); }
  });
  main.replaceChildren(pageHead("Профіль"),
    h("div", { class: "panel", style: "max-width:420px;margin-bottom:1rem" },
      h("p", {}, h("strong", {}, u.full_name || u.username)),
      h("p", { class: "muted" }, `Логін: ${u.username} · ${ROLE[u.role]}${u.group ? ` · група ${u.group}` : ""}`),
      h("p", { class: "muted small" }, `Останній вхід: ${fmtDate(u.last_login)}`),
      u.email ? h("p", { class: "muted small" }, `Пошта: ${u.email}`) : null,
      h("p", { class: "muted small" }, `«Мої файли»: ${fmtBytes(u.quota.used)} з ${fmtBytes(u.quota.quota)}`)),
    u.login_method === "oidc"
      ? h("div", { class: "panel muted", style: "max-width:420px" }, "Ви увійшли через пошту коледжу — пароль порталу не потрібен.")
      : form);
}

// ---------------------------------------------------------------- старт
async function boot() {
  try {
    state.user = await api("/api/auth/me");
  } catch {
    return renderLogin();
  }
  if (state.user.must_change_password) return renderForcePassword();
  renderShell();
  await renderRoute();
}

window.addEventListener("hashchange", () => { if (state.user) renderRoute(); });
boot();

