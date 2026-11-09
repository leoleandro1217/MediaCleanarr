let path = "", parent = null, rows = [];
const $ = id => document.getElementById(id);
async function api(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok) throw Error(payload.error || "Erreur réseau");
  return payload;
}
const post = (url, data) => api(url, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)});
function notify(message) { $("notice").textContent = message; $("notice").style.display = "block"; }

async function browse(next = "") {
  try {
    const data = await api("/api/browse?path=" + encodeURIComponent(next));
    path = data.path; parent = data.parent;
    $("current").textContent = "/media" + (path ? "/" + path : "");
    $("up").disabled = parent === null;
    const area = $("folders"); area.replaceChildren();
    if (!data.directories.length) area.textContent = "Aucun sous-dossier";
    for (const folder of data.directories) {
      const button = document.createElement("button");
      button.className = "folder"; button.textContent = "📁 " + folder.name;
      button.addEventListener("click", () => browse(folder.path)); area.append(button);
    }
  } catch (e) { notify(e.message); }
}
function updateApply() { $("apply").disabled = !rows.some(r => r.checked && r.status === "ready"); }
function validateEdit(row, value) {
  const original = row.source.split("/").pop();
  const extension = original.slice(original.lastIndexOf(".")).toLowerCase();
  row.proposed = value; row.checked = false;
  row.status = !value || value === "." || value === ".." || value.includes("/") ||
    value.includes("\\") || !value.toLowerCase().endsWith(extension) ||
    value.toLowerCase() === extension ? "conflict" : value === original ? "skip" : "ready";
  row.reason = row.status === "conflict" ? "Nom ou extension invalide" : "";
}
function render() {
  const area = $("results"); area.replaceChildren();
  $("count").textContent = "(" + rows.length + " vidéos)";
  if (!rows.length) {
    const tr = document.createElement("tr"), td = document.createElement("td");
    td.colSpan = 4; td.textContent = "Aucune vidéo trouvée."; tr.append(td); area.append(tr);
  }
  for (const row of rows) {
    const tr = document.createElement("tr"), cells = Array.from({length:4}, () => document.createElement("td"));
    const check = document.createElement("input"); check.type = "checkbox";
    check.checked = Boolean(row.checked); check.disabled = row.status !== "ready";
    check.addEventListener("change", () => {row.checked = check.checked; updateApply();});
    cells[0].append(check); cells[1].textContent = row.source;
    const edit = document.createElement("input"); edit.type = "text";
    edit.value = row.proposed || ""; edit.disabled = !row.proposed;
    edit.addEventListener("change", () => {validateEdit(row, edit.value); render();});
    cells[2].append(edit); cells[3].className = row.status;
    const label = {ready:"Prêt",skip:"Ignoré",conflict:"À vérifier"}[row.status] || row.status;
    cells[3].textContent = label + " " + (row.reason || "") +
      (row.metadata ? " · " + row.metadata.source + (row.metadata.id ? " #" + row.metadata.id : "") :
      row.lookup === "not_found" ? " · Aucune correspondance API" : "");
    tr.append(...cells); area.append(tr);
  }
  updateApply();
}
$("up").addEventListener("click", () => parent !== null && browse(parent));
$("scan").addEventListener("click", async () => {
  try {
    $("scan").disabled = true; notify("Analyse en cours...");
    const result = await post("/api/scan", {path, recursive:$("recursive").checked,
      category:$("category").value, provider:$("provider").value, language:$("language").value});
    rows = result.rows.map(r => ({...r,checked:r.status === "ready"}));
    render(); notify(rows.length + " vidéos analysées, " + rows.filter(r => r.status === "ready").length + " propositions prêtes.");
  } catch (e) { notify(e.message); } finally { $("scan").disabled = false; }
});
$("selectAll").addEventListener("click", () => {rows.forEach(r => r.checked = r.status === "ready"); render();});
$("selectNone").addEventListener("click", () => {rows.forEach(r => r.checked = false); render();});
$("apply").addEventListener("click", async () => {
  const items = rows.filter(r => r.checked && r.status === "ready").map(r => ({source:r.source,proposed:r.proposed}));
  if (!items.length || !confirm("Renommer " + items.length + " fichier(s) ? Les dossiers ne seront pas modifiés.")) return;
  try {
    $("apply").disabled = true;
    const result = await post("/api/rename", {items});
    notify(result.renamed.length + " fichiers renommés. " + result.errors.length + " erreur(s)." +
      (result.errors.length ? " " + result.errors.slice(0,3).map(e => e.error).join(" ; ") : ""));
    rows = []; render(); refreshHistory();
  } catch (e) { notify(e.message); } finally { updateApply(); }
});
async function refreshHistory() {
  try {
    const result = await api("/api/history"), area = $("history"); area.replaceChildren();
    const batches = new Map();
    for (const entry of result.rows) {
      if (!batches.has(entry.batch)) batches.set(entry.batch, []);
      batches.get(entry.batch).push(entry);
    }
    if (!batches.size) area.textContent = "Aucune modification pour le moment.";
    for (const [batch, entries] of batches) {
      const article = document.createElement("article"), heading = document.createElement("div");
      heading.textContent = "Lot " + batch + " — " + entries.length + " fichier(s)";
      const info = document.createElement("small");
      info.textContent = new Date(entries[0].time).toLocaleString("fr-FR") +
        " · " + entries.filter(r => r.undone).length + " déjà annulés";
      heading.append(info);
      const button = document.createElement("button"); button.textContent = "Annuler ce lot";
      button.disabled = entries.every(r => r.undone);
      button.addEventListener("click", async () => {
        if (!confirm("Annuler les renommages du lot " + batch + " ?")) return;
        try {
          const result = await post("/api/undo", {batch});
          notify(result.restored.length + " fichiers restaurés. " + result.errors.length + " erreur(s).");
          refreshHistory();
        } catch (e) { notify(e.message); }
      });
      article.append(heading, button); area.append(article);
    }
  } catch (e) { notify(e.message); }
}
$("refreshHistory").addEventListener("click", refreshHistory);
async function providerInfo() {
  try {
    const p = await api("/api/providers");
    $("providerInfo").textContent = "Clés configurées : " +
      ["OMDb","TheTVDB","TMDB"].map((name,i) => name + " " + (p[["omdb","tvdb","tmdb"][i]] ? "✓" : "✗")).join(" · ") +
      ". OMDb Title n'est pas forcément le titre original. Les traductions TheTVDB absentes ne sont pas remplacées.";
  } catch (e) { notify(e.message); }
}
$("provider").addEventListener("change", () => { $("language").disabled = $("provider").value !== "tvdb"; });
$("provider").dispatchEvent(new Event("change"));
browse(); refreshHistory(); providerInfo();
