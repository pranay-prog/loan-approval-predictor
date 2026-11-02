/* LoanSense – Loan Approval Predictor front-end (vanilla JS, no CDN needed). */
(() => {
  "use strict";

  // ------------------------------------------------------------ helpers
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const inr = (n) => (n == null || isNaN(n) ? "—" : "₹" + Math.round(n).toLocaleString("en-IN"));
  const pct = (n, d = 1) => (n == null || isNaN(n) ? "—" : (n * 100).toFixed(d) + "%");
  const fmtTime = (iso) => { const d = new Date(iso); return isNaN(d) ? iso : d.toLocaleString([], { dateStyle: "medium", timeStyle: "short" }); };
  const ALGO = { decision_tree: "Decision Tree", logistic_regression: "Logistic Regression" };
  const C = { ok: "#0f9d68", bad: "#d93a3a", brand: "#1f4ed8", soft: "#c7d4f7", warn: "#c98a07" };

  async function api(path, opts = {}) {
    const init = { ...opts };
    if (init.body && !(init.body instanceof FormData)) {
      init.headers = { "Content-Type": "application/json", ...(init.headers || {}) };
      init.body = JSON.stringify(init.body);
    }
    const res = await fetch(path, init);
    let data = null;
    try { data = await res.json(); } catch { /* non-JSON */ }
    if (!res.ok) { const e = new Error((data && data.error) || res.statusText); e.data = data; e.status = res.status; throw e; }
    return data;
  }

  function toast(msg, kind = "") {
    const t = document.createElement("div");
    t.className = "toast " + kind;
    t.textContent = msg;
    $("#toasts").appendChild(t);
    setTimeout(() => t.remove(), 3500);
  }

  function busy(btn, on) { btn.classList.toggle("loading", on); btn.disabled = on; }
  const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

  // ------------------------------------------------------------ routing
  const TITLES = {
    predict: "Predict a loan decision", dashboard: "Dashboard", history: "Prediction history",
    batch: "Batch upload", model: "Model lab", dataset: "Training dataset", system: "Container & system",
  };
  const loaders = {};
  function show(view) {
    if (!TITLES[view]) view = "predict";
    $$(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + view));
    $$("nav a").forEach((a) => a.classList.toggle("active", a.dataset.view === view));
    $("#view-title").textContent = TITLES[view];
    $("#sidebar").classList.remove("open");
    if (loaders[view]) loaders[view]();
  }
  window.addEventListener("hashchange", () => show(location.hash.slice(1)));
  $("#menu-btn").addEventListener("click", () => $("#sidebar").classList.toggle("open"));

  // ------------------------------------------------------------ health
  async function refreshHealth() {
    try {
      const h = await api("/api/health");
      $("#health-dot").className = "dot ok";
      $("#health-text").textContent = `Healthy · ${h.database.backend}`;
      $("#active-model-pill").textContent = "Model: " + ALGO[h.model.active];
      return h;
    } catch (e) {
      $("#health-dot").className = "dot bad";
      $("#health-text").textContent = "Unhealthy";
      return e.data;
    }
  }

  // ============================================================ PREDICT
  const OPTIONS = {
    Gender: ["Male", "Female"], Married: ["Yes", "No"], Dependents: ["0", "1", "2", "3+"],
    Education: ["Graduate", "Not Graduate"], Self_Employed: ["No", "Yes"],
    Property_Area: ["Urban", "Semiurban", "Rural"], Credit_History: [1, 0],
  };
  const DEFAULTS = { Gender: "Male", Married: "Yes", Dependents: "0", Education: "Graduate", Self_Employed: "No", Property_Area: "Semiurban", Credit_History: 1 };
  const SAMPLES = {
    good: { applicant_name: "Priya Sharma", Gender: "Female", Married: "Yes", Dependents: "1", Education: "Graduate", Self_Employed: "No", Property_Area: "Semiurban", Credit_History: 1, ApplicantIncome: 8500, CoapplicantIncome: 3000, LoanAmount: 160, Loan_Amount_Term: 360 },
    risky: { applicant_name: "Rahul Verma", Gender: "Male", Married: "No", Dependents: "3+", Education: "Not Graduate", Self_Employed: "Yes", Property_Area: "Rural", Credit_History: 0, ApplicantIncome: 2100, CoapplicantIncome: 0, LoanAmount: 320, Loan_Amount_Term: 180 },
  };
  const state = { seg: { ...DEFAULTS } };

  function buildSegs() {
    $$(".seg[data-name]").forEach((seg) => {
      const name = seg.dataset.name;
      seg.innerHTML = OPTIONS[name].map((o) => {
        const label = name === "Credit_History" ? (o === 1 ? "✓ Meets guidelines (1)" : "✗ Does not meet (0)") : o;
        return `<button type="button" data-v="${esc(o)}">${esc(label)}</button>`;
      }).join("");
      seg.addEventListener("click", (e) => {
        const b = e.target.closest("button"); if (!b) return;
        state.seg[name] = name === "Credit_History" ? Number(b.dataset.v) : b.dataset.v;
        paintSeg(seg); onFormChange();
      });
      paintSeg(seg);
    });
  }
  function paintSeg(seg) {
    const v = String(state.seg[seg.dataset.name]);
    $$("button", seg).forEach((b) => b.classList.toggle("on", b.dataset.v === v));
  }

  function formData() {
    return {
      applicant_name: $("#applicant_name").value.trim(),
      ...state.seg,
      ApplicantIncome: $("#ApplicantIncome").value,
      CoapplicantIncome: $("#CoapplicantIncome").value || 0,
      LoanAmount: $("#LoanAmount").value,
      Loan_Amount_Term: $("#Loan_Amount_Term").value,
    };
  }

  function fillForm(d) {
    $("#applicant_name").value = d.applicant_name || "";
    Object.keys(OPTIONS).forEach((k) => { if (d[k] !== undefined) state.seg[k] = d[k]; });
    $$(".seg[data-name]").forEach(paintSeg);
    ["ApplicantIncome", "CoapplicantIncome", "LoanAmount"].forEach((k) => { $("#" + k).value = d[k]; syncRange(k); });
    $("#Loan_Amount_Term").value = d.Loan_Amount_Term;
    onFormChange();
  }

  function syncRange(id) {
    const r = $(`.range[data-for="${id}"]`);
    if (r) r.value = $("#" + id).value;
  }

  function updateQuickStats() {
    const ai = +$("#ApplicantIncome").value || 0, ci = +$("#CoapplicantIncome").value || 0;
    const la = +$("#LoanAmount").value || 0, term = +$("#Loan_Amount_Term").value || 360;
    const total = ai + ci, emi = (la * 1000) / term, ratio = total ? emi / total : NaN;
    $("#qs-income").textContent = inr(total);
    $("#qs-emi").textContent = inr(emi);
    const r = $("#qs-ratio");
    r.textContent = isNaN(ratio) ? "—" : pct(ratio);
    r.style.color = isNaN(ratio) ? "" : ratio > 0.5 ? C.bad : ratio > 0.3 ? C.warn : C.ok;
  }

  const livePredict = debounce(() => runPredict(false), 450);
  function onFormChange() {
    updateQuickStats();
    clearErrors();
    if ($("#live-mode").checked) livePredict();
  }

  function clearErrors() {
    $$(".field.error").forEach((f) => f.classList.remove("error"));
    $$(".err-msg").forEach((e) => e.remove());
  }
  function showErrors(fields) {
    Object.entries(fields || {}).forEach(([k, msg]) => {
      const el = $("#" + k) || $(`.seg[data-name="${k}"]`);
      if (!el) return;
      const f = el.closest(".field"); f.classList.add("error");
      const m = document.createElement("div"); m.className = "err-msg"; m.textContent = msg; f.appendChild(m);
    });
  }

  async function runPredict(save = true) {
    const btn = $("#predict-btn");
    if (save) busy(btn, true);
    try {
      const body = { ...formData(), save };
      const [res, cmp] = await Promise.all([
        api("/api/predict", { method: "POST", body }),
        api("/api/compare", { method: "POST", body }),
      ]);
      renderResult(res, cmp, save);
      if (save) { toast(`Saved prediction #${res.id}: ${res.decision}`, res.decision === "Approved" ? "ok" : "bad"); loadRecent(); }
    } catch (e) {
      if (e.data && e.data.fields) { showErrors(e.data.fields); if (save) toast("Please fix the highlighted fields", "bad"); }
      else toast(e.message, "bad");
    } finally { if (save) busy(btn, false); }
  }

  function renderResult(r, cmp, saved) {
    $("#result-empty").classList.add("hidden");
    $("#result-body").classList.remove("hidden");
    const p = r.probability, ok = r.decision === "Approved";
    const color = p >= 0.65 ? C.ok : p >= 0.5 ? C.warn : C.bad;
    const fill = $("#g-fill");
    fill.style.stroke = color;
    fill.style.strokeDashoffset = 251.3 * (1 - p);
    $("#g-needle").style.transform = `rotate(${-90 + 180 * p}deg)`;
    $("#r-prob").textContent = pct(p, 1);
    const d = $("#r-decision");
    d.textContent = ok ? "✓ APPROVED" : "✗ REJECTED";
    d.className = "decision " + (ok ? "ok" : "bad");
    $("#r-meta").textContent = `${r.model_label} · v${r.model_version}` + (saved && r.id ? ` · saved as #${r.id}` : " · live preview (not saved)");

    const ex = r.explanation, box = $("#r-explain");
    if (ex && ex.type === "decision_path") {
      box.innerHTML = `<h4>Why? Decision path through the tree</h4>` +
        ex.rules.map((t, i) => `<div class="rule"><span class="rule-num">${i + 1}</span><span>${esc(t)}</span></div>`).join("") +
        `<div class="muted small" style="margin-top:8px">Final leaf: ${ex.leaf_samples} training applicants, ${pct(ex.leaf_approval_share, 0)} of them approved.</div>`;
    } else if (ex && ex.type === "contributions") {
      const max = Math.max(...ex.factors.map((f) => Math.abs(f.impact)), 0.01);
      box.innerHTML = `<h4>Why? Top factors vs. an average applicant</h4>` + ex.factors.map((f) => {
        const w = (Math.abs(f.impact) / max) * 50, pos = f.impact > 0;
        const style = pos ? `left:50%;width:${w}%;background:${C.ok}` : `right:50%;width:${w}%;background:${C.bad}`;
        return `<div class="factor"><span>${esc(f.label)}</span><div class="factor-bar"><i style="${style}"></i></div><span style="color:${pos ? C.ok : C.bad};text-align:right">${pos ? "+" : ""}${f.impact.toFixed(2)}</span></div>`;
      }).join("");
    } else box.innerHTML = "";

    if (cmp) {
      $("#r-compare").innerHTML = `<h4>Both models on this applicant</h4>` + Object.entries(cmp).map(([k, v]) =>
        `<div class="cmp-row"><span>${ALGO[k]}</span><span><span class="tag ${v.decision === "Approved" ? "ok" : "bad"}">${v.decision}</span> &nbsp;${pct(v.probability)}</span></div>`).join("");
    }
  }

  async function loadRecent() {
    try {
      const { items } = await api("/api/predictions?limit=6");
      $("#recent-list").innerHTML = items.length ? items.map((p) => `
        <li><div><b>${esc(p.applicant_name || "Applicant #" + p.id)}</b><div class="muted small">${inr(p.loan_amount * 1000)} loan · ${esc(p.property_area)} · ${fmtTime(p.created_at)}</div></div>
        <span class="tag ${p.decision === "Approved" ? "ok" : "bad"}">${p.decision} · ${pct(p.probability, 0)}</span></li>`).join("")
        : `<li class="muted">No predictions yet.</li>`;
    } catch { /* ignore */ }
  }

  function initPredict() {
    buildSegs();
    ["ApplicantIncome", "CoapplicantIncome", "LoanAmount"].forEach((id) => {
      $("#" + id).addEventListener("input", () => { syncRange(id); onFormChange(); });
    });
    $$(".range").forEach((r) => r.addEventListener("input", () => { $("#" + r.dataset.for).value = r.value; onFormChange(); }));
    $("#Loan_Amount_Term").addEventListener("change", onFormChange);
    $("#applicant_name").addEventListener("input", () => {});
    $$("[data-sample]").forEach((b) => b.addEventListener("click", () => fillForm(SAMPLES[b.dataset.sample])));
    $("#live-mode").addEventListener("change", (e) => { if (e.target.checked) runPredict(false); });
    $("#predict-form").addEventListener("submit", (e) => { e.preventDefault(); runPredict(true); });
    $$("[data-view-link]").forEach((a) => a.addEventListener("click", () => {}));
    updateQuickStats();
    loadRecent();
  }

  // ============================================================ CHARTS (SVG)
  function stackedBars(el, rows, labelFn = (k) => k) {
    if (!rows.length) { el.innerHTML = `<div class="chart-empty">No data yet — make some predictions.</div>`; return; }
    const W = 480, rowH = 40, pad = 110, H = rows.length * rowH + 20;
    const max = Math.max(...rows.map((r) => r.total));
    let s = `<svg viewBox="0 0 ${W} ${H}">`;
    rows.forEach((r, i) => {
      const y = 10 + i * rowH, w = W - pad - 60;
      const aw = (r.approved / max) * w, rw = ((r.total - r.approved) / max) * w;
      s += `<text x="${pad - 10}" y="${y + 18}" text-anchor="end" class="lbl-strong">${esc(labelFn(r.key))}</text>`;
      s += `<rect x="${pad}" y="${y + 4}" width="${Math.max(aw, 0)}" height="22" rx="4" fill="${C.ok}"><title>${r.approved} approved</title></rect>`;
      s += `<rect x="${pad + aw}" y="${y + 4}" width="${Math.max(rw, 0)}" height="22" rx="4" fill="${C.bad}" opacity=".85"><title>${r.total - r.approved} rejected</title></rect>`;
      s += `<text x="${pad + aw + rw + 8}" y="${y + 19}">${pct(r.approved / r.total, 0)} of ${r.total}</text>`;
    });
    el.innerHTML = s + `</svg><div class="legend"><span><i style="background:${C.ok}"></i>Approved</span><span><i style="background:${C.bad}"></i>Rejected</span></div>`;
  }

  function columnChart(el, labels, series, colors, opts = {}) {
    if (!labels.length || series.every((s) => s.every((v) => !v))) { el.innerHTML = `<div class="chart-empty">No data yet.</div>`; return; }
    const W = 480, H = 220, L = 34, B = 30, T = 10;
    const max = Math.ceil(Math.max(4, ...series.flat()) / 4) * 4;
    const n = labels.length, slot = (W - L - 10) / n, bw = Math.min(36, (slot * 0.7) / series.length);
    let s = `<svg viewBox="0 0 ${W} ${H}">`;
    for (let i = 0; i <= 4; i++) {
      const y = T + ((H - B - T) * i) / 4, v = Math.round(max * (1 - i / 4));
      s += `<line x1="${L}" x2="${W - 10}" y1="${y}" y2="${y}" class="axis"/><text x="${L - 6}" y="${y + 4}" text-anchor="end">${v}</text>`;
    }
    labels.forEach((lab, i) => {
      const cx = L + slot * i + slot / 2;
      series.forEach((ser, j) => {
        const h = ((H - B - T) * ser[i]) / max;
        const x = cx - (bw * series.length) / 2 + j * bw;
        s += `<rect x="${x}" y="${H - B - h}" width="${bw - 2}" height="${h}" rx="3" fill="${colors[j]}"><title>${esc(lab)}: ${ser[i]}</title></rect>`;
      });
      s += `<text x="${cx}" y="${H - 10}" text-anchor="middle">${esc(lab)}</text>`;
    });
    s += `</svg>`;
    if (opts.legend) s += `<div class="legend">${opts.legend.map((l, i) => `<span><i style="background:${colors[i]}"></i>${l}</span>`).join("")}</div>`;
    el.innerHTML = s;
  }

  function hBars(el, items, color = C.brand, fmt = (v) => pct(v)) {
    if (!items.length) { el.innerHTML = `<div class="chart-empty">No data.</div>`; return; }
    const W = 480, rowH = 28, pad = 150, H = items.length * rowH + 10;
    const max = Math.max(...items.map((i) => i.value), 1e-9);
    let s = `<svg viewBox="0 0 ${W} ${H}">`;
    items.forEach((it, i) => {
      const y = 5 + i * rowH, w = ((W - pad - 60) * it.value) / max;
      s += `<text x="${pad - 10}" y="${y + 16}" text-anchor="end">${esc(it.label)}</text>`;
      s += `<rect x="${pad}" y="${y + 4}" width="${Math.max(w, 1)}" height="16" rx="4" fill="${color}"/>`;
      s += `<text x="${pad + w + 6}" y="${y + 16}" class="lbl-strong">${fmt(it.value)}</text>`;
    });
    el.innerHTML = s + `</svg>`;
  }

  // ============================================================ DASHBOARD
  loaders.dashboard = async () => {
    try {
      const s = await api("/api/stats");
      $("#kpis").innerHTML = [
        ["Total predictions", s.total.toLocaleString(), `${s.approved} approved · ${s.rejected} rejected`],
        ["Approval rate", pct(s.approval_rate), "share of predictions approved"],
        ["Average loan", inr(s.avg_loan_amount * 1000), "requested amount"],
        ["Avg. household income", inr(s.avg_total_income), "applicant + co-applicant / month"],
      ].map(([l, v, sub]) => `<div class="kpi"><div class="k-label">${l}</div><div class="k-val">${v}</div><div class="k-sub">${sub}</div></div>`).join("");
      stackedBars($("#ch-area"), s.by_property_area);
      stackedBars($("#ch-credit"), s.by_credit_history, (k) => (k.startsWith("1") ? "Good (1)" : k.startsWith("0") ? "Poor (0)" : k));
      columnChart($("#ch-daily"), s.daily.map((d) => d.date.slice(5)), [s.daily.map((d) => d.approved), s.daily.map((d) => d.total - d.approved)], [C.ok, C.bad], { legend: ["Approved", "Rejected"] });
      columnChart($("#ch-hist"), ["0–20%", "20–40%", "40–60%", "60–80%", "80–100%"], [s.probability_histogram], [C.brand]);
    } catch (e) { toast(e.message, "bad"); }
  };

  // ============================================================ HISTORY
  const hist = { offset: 0, limit: 15 };
  loaders.history = async () => {
    const q = new URLSearchParams({ limit: hist.limit, offset: hist.offset });
    const search = $("#h-search").value.trim(), dec = $("#h-decision").value, src = $("#h-source").value;
    if (search) q.set("search", search);
    if (dec) q.set("decision", dec);
    if (src) q.set("source", src);
    try {
      const { items, total } = await api("/api/predictions?" + q);
      $("#h-table tbody").innerHTML = items.length ? items.map((p) => {
        const col = p.probability >= 0.5 ? C.ok : C.bad;
        return `<tr>
          <td>#${p.id}</td><td>${fmtTime(p.created_at)}</td><td>${esc(p.applicant_name || "—")}</td>
          <td>${inr((p.applicant_income || 0) + (p.coapplicant_income || 0))}</td><td>${inr(p.loan_amount * 1000)}</td>
          <td>${p.credit_history == 1 ? "Good" : "Poor"}</td><td>${esc(p.property_area)}</td>
          <td><span class="tag neutral">${ALGO[p.model] || esc(p.model)}</span></td>
          <td><span class="prob-bar"><i style="width:${p.probability * 100}%;background:${col}"></i></span>${pct(p.probability, 0)}</td>
          <td><span class="tag ${p.decision === "Approved" ? "ok" : "bad"}">${p.decision}</span></td>
          <td><button class="row-del" title="Delete" data-del="${p.id}">✕</button></td></tr>`;
      }).join("") : `<tr><td colspan="11" class="muted">No predictions match.</td></tr>`;
      const end = Math.min(hist.offset + hist.limit, total);
      $("#h-count").textContent = total ? `Showing ${hist.offset + 1}–${end} of ${total}` : "";
      $("#h-prev").disabled = hist.offset === 0;
      $("#h-next").disabled = end >= total;
    } catch (e) { toast(e.message, "bad"); }
  };
  function initHistory() {
    const reload = debounce(() => { hist.offset = 0; loaders.history(); }, 300);
    $("#h-search").addEventListener("input", reload);
    $("#h-decision").addEventListener("change", reload);
    $("#h-source").addEventListener("change", reload);
    $("#h-prev").addEventListener("click", () => { hist.offset = Math.max(0, hist.offset - hist.limit); loaders.history(); });
    $("#h-next").addEventListener("click", () => { hist.offset += hist.limit; loaders.history(); });
    $("#h-table").addEventListener("click", async (e) => {
      const id = e.target.dataset.del; if (!id) return;
      try { await api(`/api/predictions/${id}`, { method: "DELETE" }); toast(`Deleted #${id}`); loaders.history(); loadRecent(); }
      catch (err) { toast(err.message, "bad"); }
    });
    $("#h-clear").addEventListener("click", async () => {
      const b = $("#h-clear");
      if (b.dataset.confirm !== "1") { b.dataset.confirm = "1"; b.textContent = "Click again to confirm"; setTimeout(() => { b.dataset.confirm = ""; b.textContent = "Clear all"; }, 3000); return; }
      b.dataset.confirm = ""; b.textContent = "Clear all";
      const r = await api("/api/predictions", { method: "DELETE" });
      toast(`Deleted ${r.deleted} predictions`); loaders.history(); loadRecent();
    });
  }

  // ============================================================ BATCH
  function initBatch() {
    const input = $("#batch-file"), drop = $("#batch-drop"), run = $("#batch-run");
    const setFile = () => { const f = input.files[0]; $("#batch-filename").textContent = f ? `${f.name} · ${(f.size / 1024).toFixed(1)} KB` : "Max 1,000 rows · 5 MB"; run.disabled = !f; };
    input.addEventListener("change", setFile);
    ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
    ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
    drop.addEventListener("drop", (e) => { if (e.dataTransfer.files.length) { input.files = e.dataTransfer.files; setFile(); } });
    run.addEventListener("click", async () => {
      const fd = new FormData(); fd.append("file", input.files[0]);
      busy(run, true);
      try {
        const r = await api("/api/batch", { method: "POST", body: fd });
        $("#batch-summary").textContent = `${r.results.length} scored · ${r.approved} approved · ${r.errors.length} invalid`;
        $("#batch-table tbody").innerHTML = r.results.length ? r.results.map((x) =>
          `<tr><td>${x.row}</td><td>${esc(x.applicant_name || "—")}</td><td>${pct(x.probability)}</td><td><span class="tag ${x.decision === "Approved" ? "ok" : "bad"}">${x.decision}</span></td></tr>`).join("")
          : `<tr><td colspan="4" class="muted">No valid rows.</td></tr>`;
        $("#batch-errors").innerHTML = r.errors.length ? `<div class="err-box"><b>${r.errors.length} row(s) skipped:</b><br>` +
          r.errors.slice(0, 10).map((e) => `Row ${e.row}: ${Object.entries(e.errors).map(([k, v]) => `${esc(k)} – ${esc(v)}`).join(", ")}`).join("<br>") + `</div>` : "";
        toast(`Batch complete: ${r.results.length} predictions saved`, "ok");
        loadRecent();
      } catch (e) { toast(e.message, "bad"); } finally { busy(run, false); }
    });
  }

  // ============================================================ MODEL LAB
  let trainAlgo = "decision_tree";
  loaders.model = async () => {
    try {
      const m = await api("/api/model");
      $("#model-cards").innerHTML = Object.entries(m.models).map(([k, meta]) => {
        if (!meta) return `<div class="model-card"><h3>${ALGO[k]}</h3><p class="muted">Not trained yet.</p></div>`;
        const a = m.active === k, x = meta.metrics;
        return `<div class="model-card ${a ? "active" : ""}">
          <div class="mc-head"><div><h3>${meta.algorithm_label}</h3><div class="muted small">v${meta.version} · ${meta.train_rows} train / ${meta.test_rows} test rows · ${meta.missing_values_imputed} missing values imputed</div></div>
          ${a ? `<span class="tag ok">● Active</span>` : `<button class="btn ghost sm" data-activate="${k}">Use this model</button>`}</div>
          <div class="metrics">
            <div class="metric"><b>${pct(x.accuracy)}</b><span>Accuracy</span></div>
            <div class="metric"><b>${pct(x.precision)}</b><span>Precision</span></div>
            <div class="metric"><b>${pct(x.recall)}</b><span>Recall</span></div>
            <div class="metric"><b>${x.f1.toFixed(3)}</b><span>F1 score</span></div>
            <div class="metric"><b>${x.roc_auc.toFixed(3)}</b><span>ROC-AUC</span></div>
            <div class="metric"><b>${pct(x.cv_accuracy_mean)}</b><span>5-fold CV</span></div>
            <div class="metric"><b>±${pct(x.cv_accuracy_std)}</b><span>CV std</span></div>
            <div class="metric"><b>${meta.training_seconds}s</b><span>Train time</span></div>
          </div></div>`;
      }).join("");
      const act = m.models[m.active];
      if (act) {
        $("#fi-label").textContent = act.algorithm_label;
        hBars($("#ch-fi"), act.feature_importance.map((f) => ({ label: f.label, value: f.importance })));
        $("#cm-label").textContent = `${act.algorithm_label} · test set`;
        const [[tp, fn], [fp, tn]] = act.confusion_matrix.matrix, tot = tp + fn + fp + tn;
        const cell = (v, good) => `<div class="cm-c" style="background:${good ? "rgba(15,157,104," : "rgba(217,58,58,"}${0.12 + 0.6 * (v / tot)})"><b>${v}</b>${pct(v / tot, 0)}</div>`;
        $("#cm").innerHTML = `<div class="cm-grid">
          <div class="cm-h"></div><div class="cm-h">Predicted Approved</div><div class="cm-h">Predicted Rejected</div>
          <div class="cm-h">Actual Approved</div>${cell(tp, true)}${cell(fn, false)}
          <div class="cm-h">Actual Rejected</div>${cell(fp, false)}${cell(tn, true)}</div>`;
      }
      $("#th-table tbody").innerHTML = m.history.slice().reverse().map((h) =>
        `<tr><td>${h.version}</td><td>${ALGO[h.algorithm]}</td><td class="small">${esc(Object.entries(h.params || {}).map(([k, v]) => `${k}=${v}`).join(", ") || "defaults")}</td><td><b>${pct(h.accuracy)}</b></td></tr>`).join("")
        || `<tr><td colspan="4" class="muted">No training runs yet.</td></tr>`;
    } catch (e) { toast(e.message, "bad"); }
  };
  function initModel() {
    $("#model-cards").addEventListener("click", async (e) => {
      const k = e.target.dataset.activate; if (!k) return;
      await api("/api/model/activate", { method: "POST", body: { algorithm: k } });
      toast(`${ALGO[k]} is now active`, "ok"); refreshHealth(); loaders.model();
    });
    $("#train-algo").addEventListener("click", (e) => {
      const b = e.target.closest("button"); if (!b) return;
      trainAlgo = b.dataset.v;
      $$("#train-algo button").forEach((x) => x.classList.toggle("on", x === b));
      $$(".dt-only").forEach((x) => x.classList.toggle("hidden", trainAlgo !== "decision_tree"));
      $$(".lr-only").forEach((x) => x.classList.toggle("hidden", trainAlgo !== "logistic_regression"));
    });
    const cVal = () => Math.pow(10, +$("#t-c").value);
    $("#t-depth").addEventListener("input", (e) => ($("#v-depth").textContent = e.target.value));
    $("#t-leaf").addEventListener("input", (e) => ($("#v-leaf").textContent = e.target.value));
    $("#t-c").addEventListener("input", () => ($("#v-c").textContent = cVal().toFixed(2)));
    $("#t-test").addEventListener("input", (e) => ($("#v-test").textContent = e.target.value + "%"));
    $("#train-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const btn = $("#train-btn"); busy(btn, true);
      try {
        const body = { algorithm: trainAlgo, test_size: +$("#t-test").value / 100, activate: $("#t-activate").checked };
        if (trainAlgo === "decision_tree") Object.assign(body, { max_depth: +$("#t-depth").value, min_samples_leaf: +$("#t-leaf").value, criterion: $("#t-crit").value });
        else body.C = +cVal().toFixed(3);
        const meta = await api("/api/model/train", { method: "POST", body });
        toast(`${meta.algorithm_label} retrained · accuracy ${pct(meta.metrics.accuracy)}`, "ok");
        refreshHealth(); loaders.model();
      } catch (err) { toast(err.message, "bad"); } finally { busy(btn, false); }
    });
  }

  // ============================================================ DATASET
  loaders.dataset = async () => {
    try {
      const d = await api("/api/dataset");
      const cb = d.class_balance;
      $("#ds-kpis").innerHTML = [
        ["Rows", d.rows.toLocaleString(), d.path],
        ["Columns", d.columns.length, "incl. Loan_ID & target"],
        ["Missing values", d.missing_total, "imputed during training"],
        ["Approved in data", pct(cb.approved / (cb.approved + cb.rejected)), `${cb.approved} Y · ${cb.rejected} N`],
      ].map(([l, v, sub]) => `<div class="kpi"><div class="k-label">${l}</div><div class="k-val">${v}</div><div class="k-sub">${esc(sub)}</div></div>`).join("");
      const miss = Object.entries(d.missing).map(([k, v]) => ({ label: k, value: v })).sort((a, b) => b.value - a.value);
      hBars($("#ch-missing"), miss, C.warn, (v) => v);
      $("#ds-name").textContent = `first ${d.preview.length} rows · red = missing`;
      const cols = d.columns;
      $("#ds-table").innerHTML = `<thead><tr>${cols.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>` +
        d.preview.map((r) => `<tr>${cols.map((c) => r[c] == null ? `<td class="null">NaN</td>` : `<td>${esc(r[c])}</td>`).join("")}</tr>`).join("") + `</tbody>`;
    } catch (e) { toast(e.message, "bad"); }
  };
  function initDataset() {
    $("#ds-upload").addEventListener("click", async () => {
      const f = $("#ds-file").files[0]; if (!f) return toast("Choose a CSV first", "bad");
      const btn = $("#ds-upload"); busy(btn, true);
      const fd = new FormData(); fd.append("file", f);
      try {
        const r = await api("/api/dataset/upload", { method: "POST", body: fd });
        toast(`Dataset replaced (${r.rows} rows) and models retrained`, "ok");
        loaders.dataset();
      } catch (e) { toast(e.message, "bad"); } finally { busy(btn, false); }
    });
  }

  // ============================================================ SYSTEM
  loaders.system = async () => {
    const h = await refreshHealth();
    if (!h) return;
    const up = h.uptime_seconds, upStr = `${Math.floor(up / 3600)}h ${Math.floor((up % 3600) / 60)}m ${up % 60}s`;
    const rows = [
      ["Status", h.status], ["App version", h.version], ["Container ID / host", h.hostname],
      ["Running in container", h.in_container ? "yes" : "no"], ["Python", h.python], ["Uptime", upStr],
      ["Database", `${h.database.backend} · ${h.database.connected ? "connected" : "DOWN"}`],
      ["Active model", `${ALGO[h.model.active]} · v${h.model.version}`],
      ["Model dir", h.paths.models], ["Data dir", h.paths.data], ["Log dir", h.paths.logs], ["Server time", h.time],
    ];
    $("#sys-kv").innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join("");
    const origin = location.origin;
    $("#api-snippet").textContent =
`# Health check (used by the container HEALTHCHECK)
curl ${origin}/api/health

# Predict via REST
curl -X POST ${origin}/api/predict \\
  -H "Content-Type: application/json" \\
  -d '{"applicant_name":"API test","Gender":"Male","Married":"Yes","Dependents":"0",
       "Education":"Graduate","Self_Employed":"No","ApplicantIncome":5000,
       "CoapplicantIncome":1500,"LoanAmount":150,"Loan_Amount_Term":360,
       "Credit_History":1,"Property_Area":"Urban","source":"api"}'

# Statistics, model info, history
curl ${origin}/api/stats
curl ${origin}/api/model
curl "${origin}/api/predictions?limit=5"`;
  };
  $("#sys-refresh").addEventListener("click", () => loaders.system());

  // ------------------------------------------------------------ boot
  initPredict(); initHistory(); initBatch(); initModel(); initDataset();
  refreshHealth();
  setInterval(refreshHealth, 15000);
  show(location.hash.slice(1) || "predict");
})();
