"use strict";
// Panel Kontrol tlkdoc. All document-derived text is rendered with textContent only.

const ROLE_RANK = { VIEWER: 1, OPERATOR: 2, ADMIN: 3 };
const MODE_LABEL = {
  rules: "Aturan judul (tidak cocok → UNKNOWN)",
  rules_then_llm: "Aturan judul, lalu LLM (wajib kutip bukti)",
  llm: "LLM saja (wajib kutip bukti)",
};
const S = { me: null, tab: "overview", timers: [], docs: [], selected: new Set(), runtime: null, detail: null };

const $ = (id) => document.getElementById(id);
function el(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (k === "checked" || k === "disabled" || k === "selected") e[k] = true;
    else if (k === "value") e.value = v;
    else e.setAttribute(k, v);
  }
  for (const c of kids.flat()) if (c !== undefined && c !== null && c !== false) e.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return e;
}
function put(node, ...kids) {
  node.replaceChildren(...kids.flat().filter((k) => k !== null && k !== undefined && k !== false));
}
const can = (role) => S.me && ROLE_RANK[S.me.role] >= ROLE_RANK[role];
const pct = (a, b) => (b ? Math.round((100 * a) / b) + "%" : "—");
const fmtTime = (iso) => (iso ? new Date(iso).toLocaleString("id-ID") : "—");
const kb = (n) => (n > 1048576 ? (n / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1024)) + " KB");

function toast(message, bad) {
  const t = $("toast");
  t.textContent = message;
  t.className = "toast" + (bad ? " bad" : "");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.classList.add("hidden"), 4500);
}

const ERRORS = {
  LOGIN_REQUIRED: "Sesi berakhir, silakan masuk lagi.", INVALID_CREDENTIALS: "Nama pengguna atau kata sandi salah.",
  TOO_MANY_ATTEMPTS: "Terlalu banyak percobaan. Coba lagi dalam 15 menit.", CSRF_REJECTED: "Sesi tidak valid, muat ulang halaman.",
  ROLE_REQUIRED_OPERATOR: "Butuh peran OPERATOR.", ROLE_REQUIRED_ADMIN: "Butuh peran ADMIN.",
  UNSUPPORTED_MEDIA_TYPE: "Format tidak didukung (PDF, PNG, JPEG, TIFF).", MODEL_NOT_INSTALLED: "Model tidak terpasang di LM Studio.",
  LMS_CLI_NOT_FOUND: "CLI LM Studio (lms) tidak ditemukan.", FOLDER_NOT_FOUND: "Folder tidak ditemukan di server.",
  PASSWORD_TOO_WEAK: "Kata sandi minimal 12 karakter dan bervariasi.", AT_LEAST_ONE_ACTIVE_ADMIN_REQUIRED: "Harus ada minimal satu ADMIN aktif.",
};
const errText = (code) => ERRORS[code] || code;

async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: {}, credentials: "same-origin" };
  if (init.method !== "GET") {
    init.headers["X-CSRF-Token"] = S.me ? S.me.csrf : "";
    if (opts.raw !== undefined) { init.body = opts.raw; init.headers["Content-Type"] = "application/octet-stream"; }
    else { init.body = JSON.stringify(opts.body || {}); init.headers["Content-Type"] = "application/json"; }
  }
  const res = await fetch(path, init);
  let data = null;
  try { data = await res.json(); } catch (_) { data = null; }
  if (res.status === 401 && path !== "/api/login") { showLogin(); throw new Error("LOGIN_REQUIRED"); }
  if (!res.ok) throw new Error((data && data.error) || "HTTP_" + res.status);
  return data;
}
async function act(fn, okMessage) {
  try { const r = await fn(); if (okMessage) toast(okMessage); return r; }
  catch (e) { if (e.message !== "LOGIN_REQUIRED") toast("Gagal: " + errText(e.message), true); return null; }
}

// ---------------------------------------------------------------- auth & shell
function showLogin() {
  S.me = null; stopTimers();
  $("app").classList.add("hidden"); $("login").classList.remove("hidden"); $("login-user").focus();
}
async function boot() {
  try { S.me = await api("/api/me"); } catch (_) { return; }
  $("login").classList.add("hidden"); $("app").classList.remove("hidden");
  $("who").textContent = `${S.me.username} · ${S.me.role}`;
  for (const b of document.querySelectorAll("#tabs button")) b.classList.toggle("hidden", !!b.dataset.role && !can(b.dataset.role));
  openTab(location.hash.slice(1) || "overview");
}
$("login-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  $("login-error").textContent = "";
  try {
    S.me = await api("/api/login", { method: "POST", body: { username: $("login-user").value, password: $("login-pass").value } });
    $("login-pass").value = "";
    boot();
  } catch (e) { $("login-error").textContent = errText(e.message); }
});
$("logout").addEventListener("click", async () => { await act(() => api("/api/logout", { method: "POST" })); showLogin(); });
for (const b of document.querySelectorAll("#tabs button")) b.addEventListener("click", () => openTab(b.dataset.tab));
function stopTimers() { S.timers.forEach(clearInterval); S.timers = []; }
function every(ms, fn) { S.timers.push(setInterval(fn, ms)); }

function openTab(tab) {
  if (!TABS[tab]) tab = "overview";
  S.tab = tab; history.replaceState(null, "", "#" + tab); stopTimers();
  for (const b of document.querySelectorAll("#tabs button")) b.setAttribute("aria-selected", String(b.dataset.tab === tab));
  for (const s of document.querySelectorAll(".tab")) s.classList.toggle("hidden", s.id !== "tab-" + tab);
  TABS[tab]($("tab-" + tab));
}

// ---------------------------------------------------------------- overview
async function renderOverview(root) {
  const draw = async () => {
    const r = await act(() => api("/api/runtime"));
    if (!r) return;
    S.runtime = r;
    const lm = r.lmstudio;
    const lmCard = el("div", { class: "card" }, el("h2", {}, "LM Studio (model lokal)"),
      el("dl", { class: "kv" },
        el("dt", {}, "CLI"), el("dd", { class: lm.cli_found ? "ok" : "bad" }, lm.cli_found ? "ditemukan" : "tidak ditemukan"),
        el("dt", {}, "Server"), el("dd", { class: lm.running ? "ok" : "warn" }, lm.running ? `berjalan (port ${lm.port})` : "mati"),
        el("dt", {}, "Model dimuat"), el("dd", {}, (lm.loaded || []).join(", ") || "—"),
        el("dt", {}, "Model terpasang"), el("dd", {}, String((lm.models || []).length))),
      lm.error ? el("p", { class: "bad" }, errText(lm.error)) : null);
    if (can("ADMIN") && lm.cli_found) {
      const sel = el("select", { "aria-label": "Model" }, (lm.models || []).map((m) => el("option", { value: m.key }, `${m.name} (${m.params || "?"}, ${m.size_gb} GB)`)));
      sel.value = r.pipeline.model;
      lmCard.append(el("div", { class: "row" },
        el("button", { class: "ghost", onclick: () => act(() => api("/api/runtime/lmstudio", { method: "POST", body: { action: lm.running ? "stop" : "start" } }), "Perintah dikirim").then(draw) }, lm.running ? "Matikan server" : "Nyalakan server"),
        el("button", { class: "ghost", onclick: () => act(() => api("/api/runtime/lmstudio", { method: "POST", body: { action: "unload" } }), "Model dilepas").then(draw) }, "Lepas semua model")),
        el("label", {}, "Muat model"), el("div", { class: "row" }, el("div", { class: "grow" }, sel),
          el("button", { onclick: () => act(() => api("/api/runtime/lmstudio", { method: "POST", body: { action: "load", model: sel.value } }), "Model dimuat").then(draw) }, "Muat")));
    }
    const gpuCard = el("div", { class: "card" }, el("h2", {}, "GPU"),
      r.gpu.length ? r.gpu.map((g) => el("dl", { class: "kv" },
        el("dt", {}, "Nama"), el("dd", {}, g.name),
        el("dt", {}, "VRAM"), el("dd", {}, `${g.memory_used_mib} / ${g.memory_total_mib} MiB`),
        el("dt", {}, "Utilisasi"), el("dd", {}, g.utilization_pct + "%"))) : el("p", { class: "mute" }, "Tidak ada GPU NVIDIA terdeteksi."));
    const pinText = { PINNED_OK: ["terverifikasi", "ok"], NOT_PINNED: ["belum di-pin", "warn"], MISMATCH: ["DIGEST BERBEDA", "bad"], MISSING: ["folder tidak ada", "bad"] };
    const ocrCard = el("div", { class: "card" }, el("h2", {}, "OCR (PaddleOCR)"),
      el("dl", { class: "kv" },
        el("dt", {}, "Runtime"), el("dd", { class: r.ocr.runtime_found ? "ok" : "bad" }, r.ocr.runtime_found ? "terpasang" : "tidak ditemukan"),
        el("dt", {}, "Deteksi"), el("dd", {}, r.ocr.det, " ", el("span", { class: pinText[r.ocr.pins.det][1] }, `(${pinText[r.ocr.pins.det][0]})`)),
        el("dt", {}, "Pengenalan"), el("dd", {}, r.ocr.rec, " ", el("span", { class: pinText[r.ocr.pins.rec][1] }, `(${pinText[r.ocr.pins.rec][0]})`))));
    const pipeCard = el("div", { class: "card" }, el("h2", {}, "Pipeline aktif"),
      el("dl", { class: "kv" },
        el("dt", {}, "Klasifikasi"), el("dd", {}, MODE_LABEL[r.pipeline.mode] || r.pipeline.mode),
        el("dt", {}, "Model ekstraksi"), el("dd", {}, r.pipeline.model),
        el("dt", {}, "Halaman maks"), el("dd", {}, String(r.pipeline.max_pages)),
        el("dt", {}, "Job"), el("dd", {}, `${r.jobs.running} berjalan, ${r.jobs.queued} antre`),
        el("dt", {}, "Koneksi"), el("dd", { class: r.tls ? "ok" : "warn" }, r.tls ? "HTTPS" : "HTTP (hanya lokal)")));
    put(root, el("div", { class: "grid" }, lmCard, gpuCard, ocrCard, pipeCard));
  };
  put(root, el("p", { class: "mute" }, "Memuat…"));
  await draw();
  every(10000, draw);
}

// ---------------------------------------------------------------- documents
async function loadDocs() {
  const r = await act(() => api("/api/documents"));
  if (r) S.docs = r.documents;
  return S.docs;
}
function labelSelect(doc) {
  const sel = el("select", { "aria-label": "Label", disabled: !can("OPERATOR") },
    el("option", { value: "" }, "—"), S.me.types.map((t) => el("option", { value: t }, t)));
  sel.value = doc.label || "";
  sel.addEventListener("change", () => act(() => api(`/api/documents/${doc.document_id}/label`, { method: "POST", body: { label: sel.value } }), "Label disimpan").then(() => { doc.label = sel.value || null; }));
  return sel;
}
async function uploadFiles(files) {
  let ok = 0;
  for (const f of files) {
    const r = await act(() => api("/api/documents?filename=" + encodeURIComponent(f.name), { method: "POST", raw: f }));
    if (r) ok += 1;
  }
  toast(`${ok}/${files.length} dokumen diunggah`);
}
async function renderDocuments(root) {
  const tableHost = el("div");
  const detailHost = el("div");
  const filter = el("input", { placeholder: "Cari nama file…", "aria-label": "Cari" });
  const useLlm = el("input", { type: "checkbox", id: "use-llm", checked: true });
  const draw = async () => {
    await loadDocs();
    const q = filter.value.toLowerCase();
    const rows = S.docs.filter((d) => !q || d.filenames.join(" ").toLowerCase().includes(q));
    const all = el("input", { type: "checkbox", "aria-label": "Pilih semua", onchange: (e) => { rows.forEach((d) => e.target.checked ? S.selected.add(d.document_id) : S.selected.delete(d.document_id)); draw(); } });
    const tb = el("tbody");
    for (const d of rows) {
      const cb = el("input", { type: "checkbox", "aria-label": "Pilih", checked: S.selected.has(d.document_id) });
      cb.addEventListener("change", () => { cb.checked ? S.selected.add(d.document_id) : S.selected.delete(d.document_id); count.textContent = `${S.selected.size} dipilih`; });
      const latest = d.latest;
      tb.append(el("tr", { class: S.detail === d.document_id ? "sel" : "" },
        el("td", {}, cb),
        el("td", {}, el("a", { href: "#documents", onclick: (e) => { e.preventDefault(); S.detail = d.document_id; showDetail(detailHost, d.document_id); draw(); } }, d.filenames[0]),
          el("div", { class: "small mute" }, `${d.media_type} · ${kb(d.byte_length)} · ${d.uploaded_by}`)),
        el("td", {}, labelSelect(d)),
        el("td", {}, latest ? el("span", { class: latest.status === "COMPLETED" ? "" : "bad" }, latest.document_type || "—") : el("span", { class: "mute" }, "belum diproses")),
        el("td", { class: "small mute" }, latest ? `v${latest.version} · ${latest.classification_source || ""} · ${latest.fields_present ?? 0} field` : "")));
    }
    put(tableHost, el("div", { class: "list" }, el("table", {},
      el("thead", {}, el("tr", {}, el("th", {}, all), el("th", {}, "Dokumen"), el("th", {}, "Label"), el("th", {}, "Hasil terakhir"), el("th", {}, ""))), tb)),
      rows.length ? null : el("p", { class: "mute" }, "Belum ada dokumen. Unggah atau impor dulu."));
    count.textContent = `${S.selected.size} dipilih`;
  };
  const count = el("span", { class: "mute" });
  const fileInput = el("input", { type: "file", multiple: true, accept: ".pdf,.png,.jpg,.jpeg,.tif,.tiff", class: "hidden" });
  fileInput.addEventListener("change", async () => { await uploadFiles([...fileInput.files]); fileInput.value = ""; draw(); });
  const drop = el("div", { class: "drop" }, "Tarik file ke sini atau ", el("button", { class: "ghost", onclick: () => fileInput.click() }, "pilih file"));
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", async (e) => { e.preventDefault(); drop.classList.remove("over"); await uploadFiles([...e.dataTransfer.files]); draw(); });
  const folder = el("input", { placeholder: "Folder di server, mis. D:\\sampel", "aria-label": "Folder" });
  const recursive = el("input", { type: "checkbox", id: "imp-rec" });
  const left = el("div", {},
    can("OPERATOR") ? el("div", { class: "card" }, el("h2", {}, "Tambah dokumen"), drop, fileInput,
      can("ADMIN") ? el("div", {}, el("label", {}, "Impor dari folder server (ADMIN)"), el("div", { class: "row" }, el("div", { class: "grow" }, folder),
        el("button", { class: "ghost", onclick: async () => { const r = await act(() => api("/api/documents/import", { method: "POST", body: { folder: folder.value, recursive: recursive.checked } })); if (r) { toast(`${r.imported} diimpor, ${r.skipped} dilewati`); draw(); } } }, "Impor")),
        el("label", {}, recursive, " termasuk subfolder")) : null) : null,
    el("div", { class: "card" }, el("div", { class: "row" }, el("h2", { class: "grow" }, "Dokumen"), count),
      el("div", { class: "row" }, el("div", { class: "grow" }, filter)),
      can("OPERATOR") ? el("div", { class: "row" },
        el("button", { onclick: async () => { if (!S.selected.size) return toast("Pilih dokumen dulu", true); const j = await act(() => api("/api/jobs", { method: "POST", body: { kind: "process", document_ids: [...S.selected], use_llm: useLlm.checked } })); if (j) { toast(`Job ${j.job_id} dibuat`); } } }, "Proses terpilih"),
        el("label", {}, useLlm, " pakai LLM untuk ekstraksi")) : null,
      tableHost));
  filter.addEventListener("input", draw);
  put(root, el("div", { class: "split docs" }, left, detailHost));
  await draw();
  if (S.detail) showDetail(detailHost, S.detail);
  else put(detailHost, el("div", { class: "card mute" }, "Pilih dokumen untuk melihat detail, versi hasil dan bukti."));
}
async function showDetail(host, id) {
  const d = await act(() => api("/api/documents/" + id));
  if (!d) return;
  const resultHost = el("div");
  const versions = d.results.slice().reverse();
  put(host, el("div", { class: "card" },
    el("h2", {}, d.meta.filenames[0]),
    el("dl", { class: "kv" },
      el("dt", {}, "SHA-256"), el("dd", { class: "small" }, d.meta.document_id),
      el("dt", {}, "Nama lain"), el("dd", {}, d.meta.filenames.slice(1).join(", ") || "—"),
      el("dt", {}, "Diunggah"), el("dd", {}, `${fmtTime(d.meta.uploaded_at)} oleh ${d.meta.uploaded_by}`),
      el("dt", {}, "Label"), el("dd", {}, d.meta.label || "—")),
    el("div", { class: "row" }, el("a", { href: `/api/documents/${id}/content` }, "Unduh dokumen asli")),
    el("h3", {}, `Versi hasil (${versions.length})`),
    versions.length ? el("div", { class: "list" }, el("table", {}, el("thead", {}, el("tr", {}, ["Versi", "Status", "Tipe", "Sumber", "Field", "Model", "Oleh", "Selesai"].map((h) => el("th", {}, h)))),
      el("tbody", {}, versions.map((r) => el("tr", { class: "click", onclick: () => showResult(resultHost, id, r.version) },
        el("td", {}, "v" + r.version), el("td", { class: r.status === "COMPLETED" ? "ok" : "bad" }, r.status), el("td", {}, r.document_type || "—"),
        el("td", {}, r.classification_source || "—"), el("td", { class: "n" }, String(r.fields_present ?? 0)), el("td", { class: "small" }, r.llm_model || "—"),
        el("td", {}, r.processed_by || "—"), el("td", { class: "small" }, fmtTime(r.completed_at))))))) : el("p", { class: "mute" }, "Belum ada hasil. Proses dokumen ini dari daftar."),
    resultHost));
  if (versions.length) showResult(resultHost, id, versions[0].version);
}
async function showResult(host, id, version) {
  const r = await act(() => api(`/api/documents/${id}/results/${version}`));
  if (!r) return;
  const check = r.text_layer_check || {};
  put(host, el("h3", {}, `Hasil v${r.version}`),
    r.status !== "COMPLETED" ? el("p", { class: "bad" }, `Gagal aman: ${r.error_code}`) : null,
    el("dl", { class: "kv" },
      el("dt", {}, "Tipe dokumen"), el("dd", {}, el("b", {}, r.document_type || "—"), ` (${r.classification_source || "—"})`),
      el("dt", {}, "Bukti klasifikasi"), el("dd", {}, (r.classification_evidence || []).length ? r.classification_evidence.map((e) => el("div", {}, el("span", { class: "quote" }, e.quote || ""), el("span", { class: "small mute" }, ` hal ${e.page}`))) : "— (abstain)"),
      el("dt", {}, "Konfigurasi"), el("dd", { class: "small" }, Object.entries(r.config || {}).map(([k, v]) => `${k}@v${v}`).join(" · ")),
      el("dt", {}, "OCR"), el("dd", { class: "small" }, `${r.ocr_engine || "—"} · ${r.pages_processed ?? "?"}/${r.total_pages ?? "?"} hal · ${r.lines ?? 0} baris · ${r.ocr_s ?? "?"} s${r.ocr_cached ? " (cache)" : ""}`),
      el("dt", {}, "Model"), el("dd", { class: "small" }, r.llm_model || "tanpa LLM"),
      el("dt", {}, "Schema field"), el("dd", { class: "small" }, r.extraction_schema ? `${r.extraction_schema.id}@${r.extraction_schema.version} (${r.extraction_schema.selection})` : "— (tidak ada ekstraksi)")),
    (r.fields || []).length ? el("div", { class: "scroll" }, el("table", {}, el("thead", {}, el("tr", {}, ["Field", "Status", "Nilai (dari sumber)", "Bukti", "Text layer PDF"].map((h) => el("th", {}, h)))),
      el("tbody", {}, r.fields.map((f) => el("tr", {},
        el("td", {}, f.field_name), el("td", { class: f.state === "PRESENT" ? "ok" : "mute" }, f.state),
        el("td", {}, f.raw_value ?? "—"),
        el("td", { class: "small" }, f.evidence.map((e) => `hal ${e.page} · ${e.block_id}`).join(", ") || "—"),
        el("td", { class: check[f.field_name] === true ? "ok" : check[f.field_name] === false ? "warn" : "mute" },
          check[f.field_name] === true ? "cocok" : check[f.field_name] === false ? "tidak cocok" : f.state === "PRESENT" ? "tidak ada text layer" : "")))))) : el("p", { class: "mute" }, "Tidak ada ekstraksi field pada versi ini."),
    el("p", { class: "small mute" }, "Nilai PRESENT selalu salinan persis dari teks OCR; nilai usulan model yang tidak ditemukan di sumber dijadikan MISSING. Hasil adalah klaim mesin, bukan otorisasi bisnis."));
}

// ---------------------------------------------------------------- jobs
async function renderJobs(root) {
  const logHost = el("div");
  let open = null;
  const draw = async () => {
    const r = await act(() => api("/api/jobs"));
    if (!r) return;
    const tb = el("tbody", {}, r.jobs.map((j) => {
      const bar = el("div"); bar.style.width = pct(j.progress.done, j.progress.total).replace("—", "0%");
      return el("tr", { class: "click" + (open === j.job_id ? " sel" : ""), onclick: () => { open = j.job_id; draw(); } },
        el("td", {}, j.job_id), el("td", {}, j.kind === "process" ? "Proses" : "Benchmark"), el("td", {}, j.actor),
        el("td", { class: j.status === "FAILED" ? "bad" : j.status === "DONE" ? "ok" : "" }, j.status),
        el("td", {}, el("div", { class: "bar" }, bar), el("div", { class: "small mute" }, `${j.progress.done}/${j.progress.total}`)),
        el("td", { class: "small" }, fmtTime(j.created_at)));
    }));
    put(root, el("div", { class: "card" }, el("h2", {}, "Job"),
      r.jobs.length ? el("div", { class: "list" }, el("table", {}, el("thead", {}, el("tr", {}, ["ID", "Jenis", "Oleh", "Status", "Progres", "Dibuat"].map((h) => el("th", {}, h)))), tb)) : el("p", { class: "mute" }, "Belum ada job."),
      el("p", { class: "small mute" }, "Antrean disimpan di memori: job yang masih antre saat layanan dimatikan perlu dikirim ulang. Hasil yang sudah selesai tetap tersimpan.")), logHost);
    if (open) {
      const j = await act(() => api("/api/jobs/" + open));
      if (j) put(logHost, el("div", { class: "card" }, el("div", { class: "row" }, el("h2", { class: "grow" }, "Log " + j.job_id),
        can("OPERATOR") && (j.status === "RUNNING" || j.status === "QUEUED") ? el("button", { class: "danger", onclick: () => act(() => api(`/api/jobs/${j.job_id}/cancel`, { method: "POST" }), "Pembatalan dikirim").then(draw) }, "Batalkan") : null),
        el("pre", {}, (j.log || []).join("\n") || "—")));
    }
  };
  await draw();
  every(2500, draw);
}

// ---------------------------------------------------------------- benchmark
function compareTable(run) {
  const rows = Object.entries(run.models || {}).map(([m, v]) => ({ m, s: v.summary, err: v.error }));
  if (!rows.length) return el("p", { class: "mute" }, "Belum ada hasil.");
  const many = rows.length > 1;
  const acc = (s) => (s.labelled ? s.correct / s.labelled : -1);
  const gr = (s) => (s.text_layer_checked ? s.text_layer_confirmed / s.text_layer_checked : -1);
  const bestAcc = many ? Math.max(...rows.map((x) => acc(x.s))) : NaN;
  const bestGr = many ? Math.max(...rows.map((x) => gr(x.s))) : NaN;
  const lat = rows.filter((x) => x.s.llm_median_s != null).map((x) => x.s.llm_median_s);
  const fastest = many && lat.length ? Math.min(...lat) : NaN;
  return el("div", {}, el("div", { class: "scroll" }, el("table", {},
    el("thead", {}, el("tr", {}, ["Model", "Akurasi", "UNKNOWN", "Salah label", "Field PRESENT", "Cocok text layer", "LLM median", "LLM maks", "Error"].map((h, i) => el("th", { class: i ? "n" : "" }, h)))),
    el("tbody", {}, rows.map(({ m, s, err }) => el("tr", {},
      el("td", {}, m, err ? el("div", { class: "bad small" }, errText(err)) : null),
      el("td", { class: "n" + (acc(s) === bestAcc && s.labelled ? " best ok" : "") }, s.labelled ? `${s.correct}/${s.labelled} (${pct(s.correct, s.labelled)})` : "tanpa label"),
      el("td", { class: "n" }, String(s.unknown)), el("td", { class: "n" + (s.wrong_not_unknown ? " bad" : "") }, String(s.wrong_not_unknown)),
      el("td", { class: "n" }, String(s.fields_present)),
      el("td", { class: "n" + (gr(s) === bestGr && s.text_layer_checked ? " best ok" : "") }, s.text_layer_checked ? `${s.text_layer_confirmed}/${s.text_layer_checked} (${pct(s.text_layer_confirmed, s.text_layer_checked)})` : "—"),
      el("td", { class: "n" + (s.llm_median_s === fastest ? " best ok" : "") }, s.llm_median_s != null ? s.llm_median_s + " s" : "—"),
      el("td", { class: "n" }, s.llm_max_s != null ? s.llm_max_s + " s" : "—"),
      el("td", { class: "n" + (s.errors ? " bad" : "") }, String(s.errors))))))),
    rows.some((x) => x.s.confusion.length) ? el("div", { class: "small" }, el("h3", {}, "Salah klasifikasi"),
      rows.filter((x) => x.s.confusion.length).map((x) => el("div", {}, el("b", {}, x.m + ": "), x.s.confusion.map((c) => `${c.label}→${c.predicted} ×${c.count}`).join(", ")))) : null,
    el("p", { class: "small mute" }, "\"Salah label\" = prediksi tipe lain selain label dan bukan UNKNOWN (paling berisiko). \"Cocok text layer\" = cek independen nilai PRESENT terhadap teks asli PDF; dokumen scan tidak dihitung."));
}
function runDetail(run) {
  const host = el("div");
  const show = (m) => {
    const docs = (run.models[m] || {}).documents || [];
    put(host, el("div", { class: "scroll" }, el("table", {}, el("thead", {}, el("tr", {}, ["Dokumen", "Label", "Prediksi", "Sumber", "PRESENT", "OCR s", "LLM s", "Catatan"].map((h) => el("th", {}, h)))),
      el("tbody", {}, docs.map((d) => {
        const cls = d.label ? (d.predicted === d.label ? "ok" : d.predicted === "UNKNOWN" ? "warn" : "bad") : "";
        const miss = Object.entries(d.text_layer_check || {}).filter(([, v]) => v === false).map(([k]) => k);
        return el("tr", {}, el("td", {}, d.file), el("td", {}, d.label || "—"), el("td", { class: cls }, d.predicted || "—"), el("td", { class: "mute" }, d.source || ""),
          el("td", { class: "n" }, String(d.present)), el("td", { class: "n" }, d.ocr_s ?? "—"), el("td", { class: "n" }, d.llm_s ?? "—"),
          el("td", { class: d.error ? "bad" : "mute small" }, d.error || (miss.length ? "tidak cocok text layer: " + miss.join(", ") : "")));
      })))));
  };
  const models = Object.keys(run.models || {});
  if (models.length) show(models[0]);
  return el("div", {}, el("div", { class: "row" }, models.map((m) => el("button", { class: "ghost", onclick: () => show(m) }, m))), host);
}
async function renderBenchmark(root) {
  const docs = await loadDocs();
  const runtime = S.runtime || (await act(() => api("/api/runtime"))) || { lmstudio: { models: [] } };
  const models = runtime.lmstudio.models || [];
  const chosen = new Set(docs.filter((d) => d.label).map((d) => d.document_id));
  const docList = el("div", { class: "list" }, el("table", {}, el("tbody", {}, docs.map((d) => {
    const cb = el("input", { type: "checkbox", checked: chosen.has(d.document_id), "aria-label": d.filenames[0] });
    cb.addEventListener("change", () => (cb.checked ? chosen.add(d.document_id) : chosen.delete(d.document_id)));
    return el("tr", {}, el("td", {}, cb), el("td", {}, d.filenames[0]), el("td", { class: d.label ? "" : "mute" }, d.label || "tanpa label"));
  }))));
  const modelBoxes = models.map((m) => ({ m, cb: el("input", { type: "checkbox", checked: m.key === runtime.pipeline?.model }) }));
  const mode = el("select", { "aria-label": "Mode" }, Object.entries(MODE_LABEL).map(([k, v]) => el("option", { value: k }, v)));
  const resultHost = el("div");
  const runsHost = el("div");
  const openRun = async (id) => {
    const run = await act(() => api("/api/benchmarks/" + id));
    if (run) put(resultHost, el("div", { class: "card" }, el("h2", {}, `Run ${run.run_id} · ${MODE_LABEL[run.mode] || run.mode}`),
      el("p", { class: "small mute" }, `oleh ${run.actor} · ${fmtTime(run.started_at)}`), compareTable(run), el("h3", {}, "Per dokumen"), runDetail(run)));
  };
  const drawRuns = async () => {
    const r = await act(() => api("/api/benchmarks"));
    if (r) put(runsHost, el("div", { class: "card" }, el("h2", {}, "Riwayat benchmark"),
      r.runs.length ? r.runs.map((x) => el("div", {}, el("a", { href: "#benchmark", onclick: (e) => { e.preventDefault(); openRun(x.run_id); } }, x.run_id),
        ` · ${MODE_LABEL[x.mode] || x.mode} · ${x.models.join(", ")} · ${x.actor} · ${fmtTime(x.started_at)}`)) : el("p", { class: "mute" }, "Belum ada run.")));
  };
  put(root, el("div", { class: "split" },
    el("div", {}, el("div", { class: "card" }, el("h2", {}, "Benchmark model"),
      el("p", { class: "small mute" }, "Dokumen berlabel dipilih otomatis. Beri label di tab Dokumen; UNKNOWN untuk dokumen di luar taksonomi."),
      el("label", {}, "Dokumen"), docList,
      el("label", {}, "Model LLM"), modelBoxes.length ? el("div", { class: "list" }, el("table", {}, el("tbody", {}, modelBoxes.map(({ m, cb }) => el("tr", {}, el("td", {}, cb), el("td", {}, m.name), el("td", { class: "small mute n" }, `${m.params || ""} · ${m.size_gb} GB`)))))) : el("p", { class: "warn" }, "LM Studio tidak tersedia; hanya mode aturan yang bisa dijalankan."),
      el("label", {}, "Mode klasifikasi"), mode,
      can("OPERATOR") ? el("div", { class: "row" }, el("button", { onclick: async () => {
        const body = { kind: "benchmark", document_ids: [...chosen], models: modelBoxes.filter((x) => x.cb.checked).map((x) => x.m.key), mode: mode.value };
        if (!body.document_ids.length) return toast("Pilih dokumen dulu", true);
        const j = await act(() => api("/api/jobs", { method: "POST", body }));
        if (j) toast(`Benchmark ${j.job_id} masuk antrean — pantau di tab Job`);
      } }, "Jalankan benchmark")) : null), runsHost),
    resultHost));
  await drawRuns();
  every(5000, drawRuns);
}

// ---------------------------------------------------------------- config
const KIND_LABEL = { pipeline: "Pipeline (model, mode, OCR)", title_rules: "Profil aturan judul", extraction_registry: "Katalog field & schema per kategori", extraction_schema: "Schema field global (lama)" };
async function renderConfig(root) {
  const host = el("div");
  const tabs = el("div", { class: "row" }, Object.entries(KIND_LABEL).map(([k, v]) => el("button", { class: "ghost", onclick: () => show(k) }, v)));
  const show = async (kind) => {
    const c = await act(() => api("/api/config/" + kind));
    if (!c) return;
    const editor = el("textarea", { "aria-label": "JSON", spellcheck: "false", disabled: !can("ADMIN") });
    editor.value = JSON.stringify(c.active.content, null, 2);
    const comment = el("input", { placeholder: "Alasan perubahan (wajib dicatat)", "aria-label": "Komentar" });
    put(host, el("div", { class: "split" },
      el("div", { class: "card" }, el("h2", {}, KIND_LABEL[kind]),
        el("p", { class: "small mute" }, `Aktif: v${c.active_version} oleh ${c.active.author} · ${fmtTime(c.active.created_at)}`),
        el("div", { class: "list" }, el("table", {}, el("thead", {}, el("tr", {}, ["Versi", "Oleh", "Waktu", "Komentar", ""].map((h) => el("th", {}, h)))),
          el("tbody", {}, c.versions.slice().reverse().map((v) => el("tr", { class: v.version === c.active_version ? "sel" : "" },
            el("td", {}, "v" + v.version), el("td", {}, v.author), el("td", { class: "small" }, fmtTime(v.created_at)), el("td", { class: "small" }, v.comment || ""),
            el("td", {}, can("ADMIN") && v.version !== c.active_version ? el("button", { class: "ghost", onclick: () => act(() => api(`/api/config/${kind}/activate`, { method: "POST", body: { version: v.version } }), `v${v.version} diaktifkan`).then(() => show(kind)) }, "Aktifkan") : v.version === c.active_version ? el("span", { class: "chip" }, "aktif") : null)))))),
        kind === "pipeline" && can("ADMIN") ? el("div", { class: "row" }, el("button", { class: "ghost", onclick: () => act(() => api("/api/config/pipeline/pin-ocr", { method: "POST" }), "Digest model OCR di-pin sebagai versi baru").then(() => show(kind)) }, "Pin digest model OCR")) : null,
        el("p", { class: "small mute" }, "Setiap simpan membuat versi baru; versi lama tidak pernah ditimpa dan bisa diaktifkan kembali. Hasil dokumen mencatat versi konfigurasi yang dipakai.")),
      el("div", { class: "card" }, el("h2", {}, can("ADMIN") ? "Ubah (JSON)" : "Isi versi aktif"), editor,
        can("ADMIN") ? el("div", {}, comment, el("div", { class: "row" }, el("button", { onclick: async () => {
          let content;
          try { content = JSON.parse(editor.value); } catch (_) { return toast("JSON tidak valid", true); }
          if (!comment.value.trim()) return toast("Isi alasan perubahan", true);
          const r = await act(() => api("/api/config/" + kind, { method: "POST", body: { content, comment: comment.value } }));
          if (r) { toast(`Tersimpan sebagai v${r.version} dan diaktifkan`); show(kind); }
        } }, "Simpan sebagai versi baru"))) : null)));
  };
  put(root, el("div", { class: "card" }, tabs), host);
  show("pipeline");
}

// ---------------------------------------------------------------- admin
async function renderAdmin(root) {
  if (!can("ADMIN")) { put(root, el("p", { class: "bad" }, "Butuh peran ADMIN.")); return; }
  const usersHost = el("div");
  const auditHost = el("div");
  const drawUsers = async () => {
    const r = await act(() => api("/api/users"));
    if (!r) return;
    const name = el("input", { placeholder: "nama (huruf kecil)", "aria-label": "Nama pengguna" });
    const role = el("select", { "aria-label": "Peran" }, ["VIEWER", "OPERATOR", "ADMIN"].map((x) => el("option", { value: x }, x)));
    const pass = el("input", { type: "password", placeholder: "kata sandi baru (≥12 karakter)", autocomplete: "new-password", "aria-label": "Kata sandi" });
    put(usersHost, el("div", { class: "card" }, el("h2", {}, "Pengguna"),
      el("table", {}, el("thead", {}, el("tr", {}, ["Nama", "Peran", "Status", ""].map((h) => el("th", {}, h)))),
        el("tbody", {}, r.users.map((u) => el("tr", {}, el("td", {}, u.username), el("td", {}, u.role), el("td", { class: u.disabled ? "bad" : "ok" }, u.disabled ? "nonaktif" : "aktif"),
          el("td", {}, el("button", { class: u.disabled ? "ghost" : "danger", onclick: () => act(() => api("/api/users", { method: "POST", body: { username: u.username, disabled: !u.disabled } }), "Disimpan").then(drawUsers) }, u.disabled ? "Aktifkan" : "Nonaktifkan")))))),
      el("h3", {}, "Tambah / ubah pengguna"), el("div", { class: "row" }, el("div", { class: "grow" }, name), role), pass,
      el("div", { class: "row" }, el("button", { onclick: async () => {
        const body = { username: name.value.trim(), role: role.value };
        if (pass.value) body.password = pass.value;
        if (await act(() => api("/api/users", { method: "POST", body }), "Pengguna disimpan; sesi lamanya dicabut")) { drawUsers(); }
      } }, "Simpan pengguna")),
      el("p", { class: "small mute" }, "VIEWER: lihat saja · OPERATOR: unggah, label, proses, benchmark · ADMIN: runtime, konfigurasi, pengguna, audit.")));
  };
  const drawAudit = async () => {
    const r = await act(() => api("/api/audit"));
    if (!r) return;
    put(auditHost, el("div", { class: "card" }, el("div", { class: "row" }, el("h2", { class: "grow" }, "Audit log"),
      el("span", { class: r.intact ? "ok" : "bad" }, r.intact ? "Rantai hash utuh" : `RANTAI RUSAK di baris ${r.broken_line}`)),
      el("div", { class: "list" }, el("table", {}, el("thead", {}, el("tr", {}, ["Waktu", "Pelaku", "Aksi", "Target", "Hasil", "Klien"].map((h) => el("th", {}, h)))),
        el("tbody", {}, r.records.map((x) => el("tr", {}, el("td", { class: "small" }, fmtTime(x.ts)), el("td", {}, x.actor), el("td", {}, x.action),
          el("td", { class: "small", title: x.target || "" }, /^[0-9a-f]{64}$/.test(x.target || "") ? x.target.slice(0, 12) + "…" : x.target || ""), el("td", { class: x.outcome === "OK" || x.outcome === "DONE" ? "" : "warn" }, x.outcome), el("td", { class: "small mute" }, x.client || ""))))))));
  };
  put(root, el("div", { class: "split" }, usersHost, auditHost));
  await Promise.all([drawUsers(), drawAudit()]);
}

// ---------------------------------------------------------------- applications (data-plane API)
async function renderApps(root) {
  if (!can("ADMIN")) { put(root, el("p", { class: "bad" }, "Butuh peran ADMIN.")); return; }
  const tokenHost = el("div");
  const draw = async () => {
    const r = await act(() => api("/api/apps"));
    if (!r) return;
    const appId = el("input", { placeholder: "id aplikasi, mis. pengadaan", "aria-label": "ID aplikasi" });
    const tenant = el("input", { placeholder: "id tenant, mis. kantor-pusat", "aria-label": "ID tenant" });
    const name = el("input", { placeholder: "nama tampilan (opsional)", "aria-label": "Nama" });
    const rate = el("input", { type: "number", value: "60", min: "1", "aria-label": "Permintaan per menit" });
    const queued = el("input", { type: "number", value: "100", min: "1", "aria-label": "Maks antre" });
    const cards = r.applications.map((a) => {
      const boxes = r.scopes.map((s) => ({ s, cb: el("input", { type: "checkbox", checked: s !== "documents:read:tenant" }) }));
      return el("div", { class: "card" },
        el("div", { class: "row" }, el("h2", { class: "grow" }, `${a.name} (${a.application_id})`),
          el("span", { class: a.disabled ? "bad" : "ok" }, a.disabled ? "nonaktif" : "aktif"),
          el("button", { class: a.disabled ? "ghost" : "danger", onclick: () => act(() => api(`/api/apps/${a.application_id}/disable`, { method: "POST", body: { disabled: !a.disabled } }), "Disimpan").then(draw) }, a.disabled ? "Aktifkan" : "Nonaktifkan")),
        el("dl", { class: "kv" }, el("dt", {}, "Tenant"), el("dd", {}, a.tenant_id),
          el("dt", {}, "Batas"), el("dd", {}, `${a.rate_per_minute} req/menit · ${a.max_queued} antre · ${kb(a.max_bytes)} per dokumen`),
          el("dt", {}, "Profil"), el("dd", {}, a.allowed_profiles.join(", "))),
        el("h3", {}, "API key"),
        a.keys.length ? el("table", {}, el("thead", {}, el("tr", {}, ["Key", "Scope", "Dibuat", "Terakhir dipakai", ""].map((h) => el("th", {}, h)))),
          el("tbody", {}, a.keys.map((k) => el("tr", {}, el("td", {}, k.key_id), el("td", { class: "small" }, k.scopes.join(", ")),
            el("td", { class: "small" }, `${fmtTime(k.created_at)} · ${k.created_by}`), el("td", { class: "small" }, fmtTime(k.last_used_at)),
            el("td", {}, k.revoked_at ? el("span", { class: "mute" }, "dicabut") : el("button", { class: "danger", onclick: () => { if (confirm(`Cabut key ${k.key_id}? Aplikasi yang memakainya langsung ditolak.`)) act(() => api(`/api/keys/${k.key_id}/revoke`, { method: "POST" }), "Key dicabut").then(draw); } }, "Cabut")))))) : el("p", { class: "mute" }, "Belum ada key."),
        el("div", { class: "row" }, boxes.map(({ s, cb }) => el("label", {}, cb, " " + s)),
          el("button", { onclick: async () => {
            const k = await act(() => api(`/api/apps/${a.application_id}/keys`, { method: "POST", body: { scopes: boxes.filter((x) => x.cb.checked).map((x) => x.s) } }));
            if (!k) return;
            const box = el("input", { value: k.token, readonly: "readonly", "aria-label": "Token" });
            put(tokenHost, el("div", { class: "card" }, el("h2", {}, `Token baru untuk ${a.application_id}`),
              el("p", { class: "warn" }, "Salin sekarang. Token ini tidak akan ditampilkan lagi; yang disimpan hanya hash-nya."), box,
              el("p", { class: "small mute" }, `Pakai sebagai header: Authorization: Bearer <token>. Key id: ${k.key_id}`)));
            box.select(); draw();
          } }, "Buat key")));
    });
    put(root, el("div", { class: "split" },
      el("div", {}, tokenHost, el("div", { class: "card" }, el("h2", {}, "Tambah aplikasi"),
        el("p", { class: "small mute" }, r.api_port ? `API v1 aktif di port ${r.api_port} (/v1/…).` : "API v1 belum aktif: jalankan serve-panel dengan --api-port."),
        appId, tenant, name, el("div", { class: "row" }, el("label", {}, "Permintaan/menit"), rate, el("label", {}, "Maks antre"), queued),
        el("div", { class: "row" }, el("button", { onclick: async () => {
          const body = { application_id: appId.value.trim(), tenant_id: tenant.value.trim(), name: name.value.trim(), rate_per_minute: +rate.value, max_queued: +queued.value };
          if (await act(() => api("/api/apps", { method: "POST", body }), "Aplikasi dibuat")) draw();
        } }, "Simpan aplikasi")),
        el("p", { class: "small mute" }, "Setiap aplikasi hanya bisa melihat dokumennya sendiri. Scope documents:read:tenant membuka akses ke seluruh dokumen tenant yang sama."))),
      el("div", {}, cards.length ? cards : el("div", { class: "card mute" }, "Belum ada aplikasi."))));
  };
  await draw();
}

const TABS = { apps: renderApps, overview: renderOverview, documents: renderDocuments, jobs: renderJobs, benchmark: renderBenchmark, config: renderConfig, admin: renderAdmin };
boot().then(() => { if (!S.me) showLogin(); });
