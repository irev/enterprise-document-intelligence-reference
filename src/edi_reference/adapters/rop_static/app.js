"use strict";
const $ = id => document.getElementById(id);
const labels = {document_number:"Nomor dokumen", document_date:"Tanggal dokumen", total_idr:"Total (IDR)", npwp:"NPWP"};
const stages = {QUEUED:"Dalam antrean", PREPROCESSING:"Menyiapkan halaman", OCR:"Membaca teks", VISION:"Membaca tata letak", NORMALIZING:"Menata nilai", REVIEW_REQUIRED:"Siap diperiksa", FAILED:"Pemrosesan gagal", INTERRUPTED:"Pemrosesan terhenti"};
const terminal = new Set(["REVIEW_REQUIRED", "FAILED", "INTERRUPTED"]);
let documents = [], selected = null, stream = null, queueSignature = "", baseline = {}, loading = false;
function element(tag, text, className) { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node; }
function notice(message) { $("notice").textContent = message; $("notice").hidden = !message; }
function errorText(code) { return ({REVIEW_CONFLICT:"Koreksi lain sudah tersimpan. Muat ulang dokumen sebelum menyimpan kembali.", QUEUE_FULL:"Antrean penuh. Tunggu pemrosesan selesai lalu coba lagi.", FILE_TYPE_INVALID:"Isi file tidak sesuai format PDF, PNG, atau JPEG yang dinyatakan.", FILE_SIZE_INVALID:"File harus berisi data dan berukuran maksimal 20 MB.", SOURCE_HOST_FORBIDDEN:"Alamat penyimpanan belum diizinkan oleh administrator.", LOGIN_REQUIRED:"Sesi berakhir. Masuk kembali untuk melanjutkan."})[code] || "Permintaan belum berhasil. Periksa masukan atau hubungi administrator."; }
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method:"POST", headers:{"Content-Type":"application/json", "X-Workspace-Request":"1"}, body:JSON.stringify(body)});
  const value = await response.json();
  if (!response.ok) { if (response.status === 401) login(); throw new Error(errorText(value.error)); }
  return value;
}
function login() { if (stream) stream.close(); $("login").hidden = false; $("shell").hidden = true; }
function navigate(view) {
  document.querySelectorAll(".view").forEach(node => node.hidden = node.id !== view);
  document.querySelectorAll("nav button").forEach(node => { if (node.dataset.view === view) node.setAttribute("aria-current", "page"); else node.removeAttribute("aria-current"); });
}
document.querySelectorAll("nav button").forEach(node => node.addEventListener("click", () => navigate(node.dataset.view)));
document.querySelector(".brand").addEventListener("click", event => { event.preventDefault(); navigate("dashboard"); });
function localDate(value) { return new Date(value).toLocaleString("id-ID", {dateStyle:"medium", timeStyle:"short"}); }
function renderQueue(rows) {
  documents = rows;
  $("count-all").textContent = rows.length;
  $("count-active").textContent = rows.filter(row => !terminal.has(row.stage)).length;
  $("count-review").textContent = rows.filter(row => row.stage === "REVIEW_REQUIRED").length;
  $("queue-count").textContent = `${rows.length} dokumen terbaru`;
  $("empty-queue").hidden = rows.length > 0;
  const signature = JSON.stringify(rows);
  if (signature !== queueSignature) {
    queueSignature = signature; $("queue").replaceChildren();
    rows.forEach(row => {
      const tr = element("tr"); tr.append(element("td", row.name), element("td", localDate(row.created)));
      const state = element("td"); state.append(element("span", stages[row.stage] || "Menunggu", "badge")); tr.append(state);
      const progress = element("progress"); progress.max = 100; progress.value = row.progress; progress.setAttribute("aria-label", `${row.name}: ${stages[row.stage] || "Menunggu"}`);
      const progressCell = element("td"); progressCell.append(progress); tr.append(progressCell);
      const button = element("button", "Buka", "secondary"); button.addEventListener("click", () => openDocument(row.id));
      const action = element("td"); action.append(button); tr.append(action); $("queue").append(tr);
    });
  }
  if (selected && !selected.result && !loading) {
    const latest = rows.find(row => row.id === selected.id);
    if (latest && latest.stage !== selected.stage) refreshDocument(selected.id);
  }
}
async function start() {
  try {
    const response = await api("/workspace/documents");
    $("actor").textContent = response.actor; $("login").hidden = true; $("shell").hidden = false;
    renderQueue(response.documents);
    if (stream) stream.close();
    stream = new EventSource("/workspace/events");
    stream.onmessage = event => { $("connection").textContent = "Terhubung"; renderQueue(JSON.parse(event.data).documents); };
    stream.onerror = () => { $("connection").textContent = "Menghubungkan kembali…"; };
  } catch { login(); }
}
$("login-form").addEventListener("submit", async event => {
  event.preventDefault(); const button = event.submitter; button.disabled = true;
  try { await api("/workspace/session", {token:$("token").value}); $("token").value = ""; $("login-error").textContent = ""; await start(); }
  catch (error) { $("login-error").textContent = error.message; }
  finally { button.disabled = false; }
});
function upload(file) {
  return new Promise(resolve => {
    const row = element("div", undefined, "upload-row"), text = element("span", file.name), progress = element("progress"); progress.max = 100; progress.value = 0; progress.setAttribute("aria-label", `Unggah ${file.name}`); row.append(text, progress); $("uploads").append(row);
    if (!file.size || file.size > 20*1024*1024 || !["application/pdf","image/png","image/jpeg"].includes(file.type)) { text.textContent = `${file.name}: format atau ukuran tidak didukung.`; progress.remove(); resolve(); return; }
    const request = new XMLHttpRequest(); request.open("POST", "/workspace/documents"); request.setRequestHeader("X-Workspace-Request", "1"); request.timeout = 120000;
    request.upload.onprogress = event => { if (event.lengthComputable) progress.value = event.loaded/event.total*100; };
    request.onload = () => { let result = {}; try { result = JSON.parse(request.responseText); } catch { /* Generic operator error below. */ }
      text.textContent = request.status === 202 ? `${file.name}: masuk antrean.` : `${file.name}: ${errorText(result.error)}`; progress.remove(); resolve(); };
    request.onerror = request.ontimeout = () => { text.textContent = `${file.name}: unggah terputus. Coba kembali.`; progress.remove(); resolve(); };
    const form = new FormData(); form.append("file", file); request.send(form);
  });
}
async function uploadFiles(files) { for (const file of Array.from(files)) await upload(file); $("files").value = ""; }
$("files").addEventListener("change", event => uploadFiles(event.target.files));
for (const type of ["dragenter","dragover"]) $("dropzone").addEventListener(type, event => { event.preventDefault(); $("dropzone").classList.add("dragging"); });
for (const type of ["dragleave","drop"]) $("dropzone").addEventListener(type, event => { event.preventDefault(); $("dropzone").classList.remove("dragging"); if (type === "drop") uploadFiles(event.dataTransfer.files); });
$("source-form").addEventListener("submit", async event => {
  event.preventDefault(); const button = event.submitter; button.disabled = true; button.textContent = "Mengambil…";
  try { await api("/workspace/source", {name:$("source-name").value, url:$("source-url").value}); $("source-url").value = ""; notice("Dokumen masuk antrean."); }
  catch (error) { notice(error.message); } finally { button.disabled = false; button.textContent = "Ambil dokumen"; }
});
function dirty() { return Object.keys(baseline).some(name => $(`field-${name}`)?.value !== baseline[name]); }
async function openDocument(id) {
  if (dirty() && !window.confirm("Ada koreksi yang belum disimpan. Buka dokumen lain?")) return;
  await refreshDocument(id); navigate("workspace");
}
async function refreshDocument(id) {
  loading = true;
  try { selected = await api(`/workspace/documents/${id}`); renderDocument(); }
  catch (error) { notice(error.message); } finally { loading = false; }
}
function changePage(page) {
  $("page-select").value = String(page); $("page-image").src = `/workspace/documents/${selected.id}/pages/${page}`;
  $("evidence-box").setAttribute("hidden", "");
}
function showEvidence(evidence) {
  changePage(evidence.page); const [x0,y0,x1,y1] = evidence.bbox; const rect = $("evidence-box");
  for (const [key,value] of Object.entries({x:x0*1000,y:y0*1000,width:(x1-x0)*1000,height:(y1-y0)*1000})) rect.setAttribute(key,String(value));
  rect.removeAttribute("hidden");
}
$("page-select").addEventListener("change", event => changePage(event.target.value));
$("zoom").addEventListener("change", event => { $("page-canvas").className = `page-canvas ${event.target.value}`; });
function displayValue(value) { if (value === null || value === undefined) return "Belum tersedia"; if (typeof value === "object" && value.currency === "IDR") return `${value.amount} IDR`; return String(value); }
function renderDocument() {
  const doc = selected; baseline = {}; $("fields").replaceChildren(); notice("");
  $("document-title").textContent = doc.name; $("document-subtitle").textContent = `${stages[doc.stage]} · ${localDate(doc.created)}`;
  $("reprocess").hidden = !terminal.has(doc.stage); $("workspace-content").hidden = !doc.result; $("empty-workspace").hidden = !!doc.result;
  $("empty-workspace").textContent = doc.stage === "FAILED" || doc.stage === "INTERRUPTED" ? "Dokumen belum berhasil diproses. Hubungi administrator untuk memeriksa layanan lokal, lalu pilih Proses ulang." : "Dokumen sedang diproses. Hasil akan tampil di sini saat tersedia.";
  if (doc.result) {
    const result = doc.result; $("subtype").textContent = result.subtype === "UNKNOWN" ? "Jenis belum diketahui" : result.subtype;
    $("result-warning").hidden = !result.warnings.length;
    $("result-warning").textContent = "Pembacaan tata letak belum tersedia. Hasil di bawah berasal dari OCR dan perlu diperiksa dengan cermat.";
    $("page-select").replaceChildren(); for (let page=1;page<=result.page_count;page++) { const option = element("option",String(page)); option.value=page; $("page-select").append(option); } changePage(1);
    const corrections = {}; doc.reviews.forEach(review => Object.assign(corrections, review.actions));
    Object.entries(labels).forEach(([name,label]) => {
      const field = result.fields[name], section = element("div", undefined,"field"), heading = element("div", undefined,"field-heading");
      const title = element("label",label); title.htmlFor=`field-${name}`;
      const confidence = field.confidence; const known = typeof confidence === "number";
      const score = element("span", known ? `${Math.round(confidence*100)}% · belum terkalibrasi` : "Confidence tidak tersedia", `confidence ${known && confidence >= .9 ? "high" : known && confidence >= .7 ? "medium" : "low"}`);
      heading.append(title,score); section.append(heading);
      const input = element("input"); input.id=`field-${name}`; input.maxLength=2000;
      input.value = corrections[name] ?? field.raw_value ?? ""; baseline[name]=input.value;
      input.addEventListener("input",() => input.classList.toggle("changed",input.value!==baseline[name])); section.append(input);
      section.append(element("p", `Hasil mesin: ${field.raw_value ?? ({AMBIGUOUS:"Ambigu",ILLEGIBLE:"Tidak terbaca",NOT_PRESENT:"Tidak ditemukan"})[field.state] ?? "Belum tersedia"}`));
      if (field.state === "PRESENT") section.append(element("p", field.normalization_error ? "Format belum dapat dinormalisasi. Periksa nilai sumber." : `Normalisasi: ${displayValue(field.normalized_value)}`));
      if (field.evidence) { const button = element("button", `Lihat bukti · halaman ${field.evidence.page}`,"evidence"); button.type="button"; button.addEventListener("click",()=>showEvidence(field.evidence)); section.append(button); }
      $("fields").append(section);
    });
    $("review-state").textContent = doc.review_version ? `Revisi koreksi ${doc.review_version} tersimpan. Ini bukan persetujuan pembayaran.` : "Belum ada koreksi operator.";
    $("line-items").replaceChildren(); result.line_items.forEach(item => { const li=element("li",item.raw_value || "Baris belum terbaca"); if (item.evidence) { const button=element("button","Lihat bukti","secondary"); button.addEventListener("click",()=>showEvidence(item.evidence)); li.append(document.createTextNode(" "),button); } $("line-items").append(li); });
    $("items-panel").hidden = !result.line_items.length;
  }
  renderAudit();
}
$("review-form").addEventListener("submit", async event => {
  event.preventDefault(); const values={}; Object.keys(baseline).forEach(name=>{ const value=$(`field-${name}`).value; if(value!==baseline[name]) values[name]=value; });
  if (!Object.keys(values).length) { notice("Belum ada nilai yang diubah."); return; }
  const button=event.submitter; button.disabled=true;
  try { await api(`/workspace/documents/${selected.id}/review`,{expected_version:selected.review_version,values}); await refreshDocument(selected.id); notice("Koreksi tersimpan. Hasil mesin tetap dipertahankan."); }
  catch(error) { notice(error.message); } finally { button.disabled=false; }
});
$("reprocess").addEventListener("click",async()=>{
  if(dirty() && !window.confirm("Ada koreksi yang belum disimpan. Lanjutkan proses ulang?")) return;
  $("reprocess").disabled=true;
  try {const value=await api(`/workspace/documents/${selected.id}/reprocess`,{}); await refreshDocument(value.id); notice("Pemrosesan baru dibuat. Hasil sebelumnya tetap tersimpan.");}
  catch(error){notice(error.message);}finally{$("reprocess").disabled=false;}
});
function renderAudit(){
  const target=$("audit-content"); target.className=""; target.replaceChildren();
  const original=element("article",undefined,"audit-entry"); original.append(element("h2",selected.name),element("p",`Diterima ${localDate(selected.created)} · ${stages[selected.stage]}`));
  if(selected.parent_id){const link=element("button","Buka versi sebelumnya","secondary");link.addEventListener("click",()=>openDocument(selected.parent_id));original.append(link);}
  target.append(original); const previous={}; Object.entries(selected.result?.fields || {}).forEach(([name,field])=>previous[name]=field.raw_value || "Belum tersedia");
  selected.reviews.forEach(review=>{const entry=element("article",undefined,"audit-entry");entry.append(element("h2",`Revisi ${review.version}`),element("p",`${review.actor} · ${localDate(review.created)}`));
    Object.entries(review.actions).forEach(([name,value])=>{const change=element("div",undefined,"audit-change");change.append(element("p",labels[name]),element("del",previous[name]),document.createTextNode(" → "),element("ins",value || "Dikosongkan"));entry.append(change);previous[name]=value;});target.append(entry);
  });
  if(!selected.reviews.length)target.append(element("p","Belum ada koreksi operator.","empty"));
}
window.addEventListener("beforeunload",event=>{if(dirty()){event.preventDefault();event.returnValue="";}});
start();
