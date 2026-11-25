// Діалог «Здати роботу»: вибір завдання і файлів з «Моїх файлів». Використовується в порталі і на сторінці столу.
import { api, fmtBytes, h, modal, toast } from "./ui.js";

export async function submitDialog({ assignmentId = null, templateId = null } = {}) {
  const assignments = await api("/api/assignments");
  if (!assignments.length) { toast("Для вашої групи ще немає завдань", true); return null; }
  let preselect = assignmentId;
  if (!preselect && templateId) {
    const match = assignments.find((a) => a.template && a.template.id === templateId && !a.submission);
    if (match) preselect = match.id;
  }
  const selected = new Set();
  let currentPath = "";

  return modal("Здати роботу", (body) => {
    const select = h("select", {}, assignments.map((a) => h("option", { value: a.id, selected: a.id === preselect },
      `${a.title}${a.submission ? " (вже здано — буде замінено)" : ""}`)));
    const listBox = h("div", { class: "panel", style: "box-shadow:none;border:1px solid var(--line);max-height:280px;overflow:auto;padding:.4rem" });
    const crumbs = h("div", { class: "breadcrumbs small" });
    const chosen = h("div", { class: "muted small" });
    const comment = h("textarea", { placeholder: "Коментар для викладача (необов'язково)" });

    const renderChosen = () => {
      chosen.textContent = selected.size ? `Вибрано: ${[...selected].join(", ")}` : "Файли не вибрано";
    };
    async function load(path) {
      currentPath = path;
      const data = await api(`/api/files?path=${encodeURIComponent(path)}`);
      crumbs.replaceChildren(h("a", { href: "#", onclick: (e) => { e.preventDefault(); load(""); } }, "Мої файли"),
        ...path.split("/").filter(Boolean).map((part, i, arr) => [" / ",
          h("a", { href: "#", onclick: (e) => { e.preventDefault(); load(arr.slice(0, i + 1).join("/")); } }, part)]));
      if (!data.items.length) {
        listBox.replaceChildren(h("div", { class: "empty small" },
          "Папка порожня. Збережіть файли в домашню папку столу → «Мої_файли» або завантажте їх у розділі «Мої файли»."));
        return;
      }
      listBox.replaceChildren(...data.items.map((item) => {
        const cb = h("input", { type: "checkbox", checked: selected.has(item.path), style: "width:auto",
          onchange: () => { cb.checked ? selected.add(item.path) : selected.delete(item.path); renderChosen(); } });
        return h("div", { class: "row", style: "padding:.25rem .3rem" }, cb,
          item.is_dir
            ? h("a", { href: "#", onclick: (e) => { e.preventDefault(); load(item.path); } }, `📁 ${item.name}`)
            : h("span", {}, `📄 ${item.name}`),
          h("span", { class: "spacer" }), h("span", { class: "muted small" }, item.is_dir ? "папка → zip" : fmtBytes(item.size)));
      }));
    }
    body.append(
      h("div", { class: "field" }, h("label", {}, "Завдання"), select),
      h("div", { class: "field" }, h("label", {}, "Файли"), crumbs, listBox, chosen),
      h("div", { class: "field" }, h("label", {}, "Коментар"), comment));
    renderChosen();
    load(currentPath).catch((e) => { listBox.textContent = e.message; });
    return () => ({ id: Number(select.value), files: [...selected], comment: comment.value });
  }, {
    submitText: "Здати",
    onSubmit: async (data) => {
      if (!data.files.length) throw new Error("Виберіть хоча б один файл або папку");
      const result = await api(`/api/assignments/${data.id}/submit`, { method: "POST", body: { files: data.files, comment: data.comment } });
      toast("Роботу здано ✔");
      return result;
    },
  });
}
