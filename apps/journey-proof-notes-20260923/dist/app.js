const config = {"schema":"neyvia.app-factory-project/v1","appId":"local.journey.proof.notes","name":"Journey Proof Notes","brief":"Keep short visual design notes while refining a local app, search them, and retain them after a restart.","template":"notes","revision":1,"storageKey":"neyvia.app-factory.local.journey.proof.notes.items.v1","noun":"note","nounPlural":"notes","verb":"Save note","placeholder":"Write one useful thought…","emptyTitle":"No notes yet","emptyDetail":"Your first saved note will appear here and remain on this device."};
const form = document.querySelector("#item-form");
const input = document.querySelector("#item-input");
const search = document.querySelector("#item-search");
const list = document.querySelector("#item-list");
const empty = document.querySelector("#empty-state");
const count = document.querySelector("#item-count");
const exportButton = document.querySelector("#export-button");

function readItems() {
  try {
    const value = JSON.parse(localStorage.getItem(config.storageKey) || "[]");
    return Array.isArray(value) ? value.filter(item => item && typeof item.text === "string") : [];
  } catch {
    return [];
  }
}

let items = readItems();

function saveItems() {
  localStorage.setItem(config.storageKey, JSON.stringify(items));
}

function render() {
  const needle = String(search.value || "").trim().toLowerCase();
  const visible = items.filter(item => !needle || item.text.toLowerCase().includes(needle));
  list.replaceChildren(...visible.map(item => {
    const row = document.createElement("li");
    row.className = "item";
    row.dataset.complete = item.complete ? "true" : "false";

    const toggle = document.createElement("input");
    toggle.type = "checkbox";
    toggle.checked = Boolean(item.complete);
    toggle.setAttribute("aria-label", `Mark ${item.text} complete`);
    toggle.addEventListener("change", () => {
      item.complete = toggle.checked;
      item.updatedAt = new Date().toISOString();
      saveItems();
      render();
    });

    const text = document.createElement("p");
    text.textContent = item.text;

    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Remove";
    remove.addEventListener("click", () => {
      items = items.filter(candidate => candidate.id !== item.id);
      saveItems();
      render();
    });

    row.append(toggle, text, remove);
    return row;
  }));

  empty.hidden = visible.length > 0;
  count.textContent = `${items.length} ${items.length === 1 ? config.noun : config.nounPlural}`;
}

form.addEventListener("submit", event => {
  event.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  items.unshift({
    id: globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    text,
    complete: false,
    createdAt: new Date().toISOString(),
  });
  saveItems();
  input.value = "";
  render();
  input.focus();
});

search.addEventListener("input", render);

exportButton.addEventListener("click", () => {
  const payload = {
    schema: "neyvia.local-app-export/v1",
    appId: config.appId,
    exportedAt: new Date().toISOString(),
    items,
  };
  const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${config.appId.replaceAll(".", "-")}-export.json`;
  anchor.click();
  URL.revokeObjectURL(url);
});

render();
