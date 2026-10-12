const STATUS_NAMES = {
  NORMAL: "Normal", LOW: "Low", HIGH: "High",
  "CRITICAL LOW": "Critical low", "CRITICAL HIGH": "Critical high",
  TEXT: "Descriptive", UNKNOWN: "Unknown",
};
const FOOD_OPTIONS_FALLBACK = ["After food", "Before food", "With food", "Empty stomach", "Any time"];

let currentResult = null;

const el = (id) => document.getElementById(id);
const esc = (s) => (s ?? "").toString().replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const bullets = (items) => `<ul>${(items || []).map((i) => `<li>${esc(i)}</li>`).join("")}</ul>`;

// ---------------- file + analyze ----------------
el("file-input").addEventListener("change", () => {
  el("analyze-btn").disabled = !el("file-input").files.length;
});

el("analyze-btn").addEventListener("click", async () => {
  const file = el("file-input").files[0];
  if (!file) return;

  el("upload-error").hidden = true;
  el("workspace").hidden = false;
  el("results").hidden = true;
  el("analyzing").hidden = false;
  el("image-preview").innerHTML = "";

  const form = new FormData();
  form.append("file", file);
  form.append("name", el("f-name").value);
  form.append("age", el("f-age").value);
  form.append("sex", el("f-sex").value);
  form.append("weight", el("f-weight").value);
  form.append("height", el("f-height").value);

  try {
    const res = await fetch("/api/analyze", { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Could not analyse the document.");
    currentResult = data.result;
    renderResult(currentResult);
    renderImagePreview(currentResult);
  } catch (e) {
    el("upload-error").textContent = e.message;
    el("upload-error").hidden = false;
  } finally {
    el("analyzing").hidden = true;
  }
});

function renderImagePreview(result) {
  const box = el("image-preview");
  if (!result || !result.img_key) { box.innerHTML = ""; return; }
  let html = "";
  for (let i = 0; i < result.image_count; i++) {
    html += `<img src="/api/images/${result.img_key}/${i}" alt="page ${i + 1}">`;
  }
  box.innerHTML = html;
}

// ---------------- render top-level result ----------------
function renderResult(r) {
  el("results").hidden = false;

  el("profile-line").textContent = r.profile_lines.map(([k, v]) => `${k}: ${v}`).join("  ·  ");
  el("doc-meta").textContent =
    `Document: ${r.document.type} · Date: ${r.document.date} · Doctor: ${r.document.doctor} · Lab: ${r.document.facility}`;

  el("m-checked").textContent = r.counts.checked;
  el("m-normal").textContent = r.counts.normal;
  el("m-attention").textContent = r.counts.attention;

  if (r.critical.length) {
    el("critical-alert").hidden = false;
    el("critical-alert").textContent =
      `🔴 Some values are far outside the normal range: ${r.critical.join(", ")}. Please contact your doctor today.`;
  } else {
    el("critical-alert").hidden = true;
  }

  renderReportTab(r);
  renderTestsTab(r);
  renderMedsTab(r);
  renderDoctorTab(r);
  renderDataTab(r);
}

el("pdf-top").addEventListener("click", () => window.open("/api/report.pdf", "_blank"));
el("pdf-bottom").addEventListener("click", () => window.open("/api/report.pdf", "_blank"));

// ---------------- tabs ----------------
document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => (p.hidden = true));
    btn.classList.add("active");
    el(`tab-${btn.dataset.tab}`).hidden = false;
  });
});

// ---------------- report tab ----------------
function renderReportTab(r) {
  let html = `<h3>Summary</h3><p>${esc(r.report.overall_summary)}</p>`;

  if (r.report.normal_results.length) {
    html += `<div class="banner success"><b>✅ Good news: normal results</b><ul>${
      r.report.normal_results.map((n) => `<li>${esc(n.test)}: ${esc(n.value)} is within the normal range (${esc(n.range)})</li>`).join("")
    }</ul></div>`;
  }

  if (r.report.findings.length) {
    html += `<h3>⚠️ What needs attention</h3>`;
    for (const f of r.report.findings) {
      const kind = f.urgency === "urgent" ? "error" : f.urgency === "see_doctor_soon" ? "warning" : "info";
      const icon = f.urgency === "urgent" ? "🔴" : f.urgency === "see_doctor_soon" ? "🟠" : "🟢";
      html += `<details class="finding" open><summary>${esc(f.test_name)} · ${icon} ${esc(f.urgency_label)}</summary>
        <div class="body">`;
      if (f.value) {
        html += `<p><b>Your value: ${esc(f.value.value_fmt)} · Normal for you: ${esc(f.value.range_fmt)} · ${f.value.status_icon} ${esc(STATUS_NAMES[f.value.status] || f.value.status)}</b></p>`;
      }
      html += `<div class="banner ${kind}">${esc(f.what_your_result_means)}</div>
        <p><b>What this test measures:</b> ${esc(f.what_it_measures)}</p>
        <div class="two-col">
          <div><b>Possible causes</b>${bullets(f.possible_causes)}</div>
          <div><b>Food & lifestyle tips</b>${bullets(f.food_and_lifestyle_tips)}</div>
        </div>
        <p><b>What your doctor may do</b>${bullets(f.what_your_doctor_may_do)}</p>
      </div></details>`;
    }
  }

  if (r.report.diet_and_lifestyle.length) {
    html += `<h3>🥗 Diet & lifestyle</h3>${bullets(r.report.diet_and_lifestyle)}`;
  }
  if (r.report.questions_for_doctor.length) {
    html += `<h3>❓ Questions to ask your doctor</h3>${bullets(r.report.questions_for_doctor)}`;
  }
  if (r.report.warning_signs.length) {
    html += `<div class="banner warning"><b>🚨 See a doctor quickly if you notice:</b>${bullets(r.report.warning_signs)}</div>`;
  }

  el("tab-report").innerHTML = html;
}

// ---------------- tests tab ----------------
function renderTestsTab(r) {
  if (!r.flags.length) { el("tab-tests").innerHTML = "<p>-</p>"; return; }
  let rows = r.flags.map((f) => `<tr style="background:${f.status_bg}">
    <td>${f.status_icon} ${esc(STATUS_NAMES[f.status] || f.status)}</td>
    <td>${esc(f.test_name)}</td><td>${esc(f.value_fmt)}</td>
    <td>${esc(f.range_fmt)}</td><td>${esc(f.note)}</td></tr>`).join("");
  el("tab-tests").innerHTML = `<table class="results">
    <thead><tr><th>Status</th><th>Test</th><th>Your value</th><th>Normal range (your age/sex)</th><th>Note</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
}

// ---------------- medicines tab ----------------
function renderMedsTab(r) {
  let html = `<h3>✅ Doctor-approved prescription</h3>`;
  if (r.prescription) {
    const rx = r.prescription;
    html += `<table class="results"><thead><tr><th>Medicine</th><th>Form</th><th>M-A-N</th><th>Food</th><th>Duration</th><th>Instructions</th></tr></thead><tbody>`;
    for (const m of rx.medicines) {
      const pattern = `${m.morning ? 1 : 0}-${m.afternoon ? 1 : 0}-${m.night ? 1 : 0}`;
      html += `<tr><td>${esc(m.name)} ${esc(m.strength)}</td><td>${esc(m.form)}</td>
        <td>${pattern}</td><td>${esc(m.food)}</td><td>${esc(m.duration)}</td><td>${esc(m.instructions)}</td></tr>`;
    }
    html += `</tbody></table>`;
    if (rx.tests.length) html += `<p><b>Tests advised:</b> ${esc(rx.tests.join(", "))}</p>`;
    if (rx.advice) html += `<p><b>Doctor's advice:</b> ${esc(rx.advice)}</p>`;
    if (rx.review_after) html += `<p><b>Review:</b> ${esc(rx.review_after)}</p>`;
    html += `<p class="caption">Approved by Dr. ${esc(rx.doctor_name)} (Reg. No. ${esc(rx.registration_no)}) on ${esc(rx.approved_at)}</p>`;
    html += `<button id="rx-pdf-btn">⬇️ Download prescription (PDF)</button>`;
  } else {
    html += `<div class="banner info">⏳ No doctor-approved prescription yet. Medicines are shown here only after a doctor reviews this report and approves them.</div>`;
  }

  html += `<hr><h3>💊 Medicines written on the uploaded document</h3>`;
  if (r.report.medicines.length) {
    for (const m of r.report.medicines) {
      html += `<div class="medicine-card"><h4>💊 ${esc(m.name)}</h4>
        <p><b>Usually used for:</b> ${esc(m.used_for)}</p>
        <p><b>How to take (as written):</b> ${esc(m.how_to_take)}</p>
        <p><b>Common side effects:</b> ${esc(m.common_side_effects.join(", "))}</p>
        <p><b>Precautions:</b> ${esc(m.precautions.join("; "))}</p></div>`;
    }
    html += `<p class="caption">Do not start, stop or change any medicine without asking your doctor.</p>`;
  } else {
    html += `<p>No medicines in this document.</p>`;
  }

  el("tab-meds").innerHTML = html;
  const rxBtn = document.getElementById("rx-pdf-btn");
  if (rxBtn) rxBtn.addEventListener("click", () => window.open("/api/prescription.pdf", "_blank"));
}

// ---------------- extracted data tab ----------------
function renderDataTab(r) {
  let html = "";
  if (r.low_confidence.length) {
    html += `<div class="banner warning">Please check these against the original: ${esc(r.low_confidence.join(", "))}</div>`;
  }
  html += `<pre style="white-space:pre-wrap;font-size:12px;background:var(--bg-secondary);padding:10px;border-radius:8px;">${esc(JSON.stringify(r.raw_document, null, 2))}</pre>`;
  el("tab-data").innerHTML = html;
}

// ---------------- doctor review tab ----------------
function renderDoctorTab(r) {
  if (!r.doctor_ok) {
    el("tab-doctor").innerHTML = `
      <h3>🩺 Doctor review & approval</h3>
      <p class="caption">For the treating doctor only. AI treatment suggestions are shown here and are never shown to the patient until a doctor approves them.</p>
      <div class="pin-box">
        <input type="password" id="doctor-pin" placeholder="Doctor PIN">
        <button id="doctor-unlock-btn" class="primary">Unlock</button>
        <p id="doctor-pin-error" class="problems" hidden>Wrong PIN.</p>
      </div>`;
    el("doctor-unlock-btn").addEventListener("click", async () => {
      const pin = el("doctor-pin").value;
      const res = await fetch("/api/doctor/unlock", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pin }),
      });
      const data = await res.json();
      if (data.ok) {
        currentResult.doctor_ok = true;
        loadDoctorPanel();
      } else {
        el("doctor-pin-error").hidden = false;
      }
    });
    return;
  }
  loadDoctorPanel();
}

async function loadDoctorPanel() {
  el("tab-doctor").innerHTML = `<h3>🩺 Doctor review & approval</h3><p>Loading...</p>`;
  const res = await fetch("/api/doctor/state");
  const data = await res.json();
  if (!res.ok) { el("tab-doctor").innerHTML = `<p class="problems">${esc(data.error)}</p>`; return; }
  renderDoctorPanel(data);
}

function renderDoctorPanel(data) {
  const rx = data.rx;
  let html = `<h3>🩺 Doctor review & approval</h3>`;
  if (rx) {
    html += `<div class="banner success">Approved by Dr. ${esc(rx.doctor_name)} on ${esc(rx.approved_at)}. Editing below and approving again will replace it.</div>`;
  }

  html += `<button id="gen-draft-btn" ${data.draft ? "disabled" : ""}>🤖 Generate AI treatment suggestions</button>`;

  if (data.draft) {
    const d = data.draft;
    html += `<div class="banner warning">⚠️ AI draft for clinical review only. Verify every suggestion against the patient's history, allergies, current medicines and the original report.</div>
      <p><b>AI clinical note:</b> ${esc(d.clinical_note)}</p>`;
    if (d.referral_or_urgent_action) {
      html += `<div class="banner error"><b>Urgent / referral:</b> ${esc(d.referral_or_urgent_action)}</div>`;
    }
    for (const m of d.medicines) {
      html += `<details class="finding"><summary>💡 ${esc(m.generic_name)} — ${esc(m.purpose)}</summary>
        <div class="body"><p><b>Related results:</b> ${esc(m.related_tests.join(", "))}</p>
        <p><b>Cautions:</b>${bullets(m.cautions)}</p></div></details>`;
    }
  }

  html += `<h4>✍️ Prescription</h4>
    <p class="caption">Edit freely: untick Include to drop a suggestion, add rows with ＋. Strength and duration must be filled by the doctor.</p>
    <table class="rx-editor" id="rx-table">
      <thead><tr><th>Include</th><th>Medicine</th><th>Strength</th><th>Form</th>
        <th>M</th><th>A</th><th>N</th><th>Food</th><th>Duration</th><th>Instructions</th><th></th></tr></thead>
      <tbody id="rx-rows"></tbody>
    </table>
    <button id="rx-add-row">＋ Add row</button>

    <label class="full-label">Tests advised (one per line)</label>
    <textarea class="rx-text" id="rx-tests">${esc(rx ? rx.tests.join("\n") : (data.draft ? data.draft.tests_to_consider.join("\n") : ""))}</textarea>

    <label class="full-label">Advice for the patient</label>
    <textarea class="rx-text" id="rx-advice">${esc(rx ? rx.advice : (data.draft ? data.draft.lifestyle_advice.join("\n") : ""))}</textarea>

    <label class="full-label">Review / follow-up</label>
    <input type="text" id="rx-review" value="${esc(rx ? rx.review_after : "")}" placeholder="e.g. Review with repeat CBC after 4 weeks">

    <div class="form-grid">
      <label>Doctor name<input type="text" id="rx-doctor-name" value="${esc(rx ? rx.doctor_name : "")}"></label>
      <label>Registration No.<input type="text" id="rx-reg-no" value="${esc(rx ? rx.registration_no : "")}"></label>
    </div>
    <label><input type="checkbox" id="rx-confirm"> I have reviewed this patient's report and take clinical responsibility for this prescription.</label>
    <div id="rx-problems" class="problems" hidden></div>
    <button id="rx-approve-btn" class="primary full">✅ Approve & send to patient</button>`;

  el("tab-doctor").innerHTML = html;

  const foodOptions = data.food_options || FOOD_OPTIONS_FALLBACK;
  const seedRows = rx
    ? rx.medicines.map((m) => ({ Include: true, Medicine: m.name, Strength: m.strength, Form: m.form,
        Morning: m.morning, Afternoon: m.afternoon, Night: m.night, Food: m.food,
        Duration: m.duration, Instructions: m.instructions }))
    : (data.rows || []);
  seedRows.forEach((row) => addRxRow(row, foodOptions));

  document.getElementById("gen-draft-btn").addEventListener("click", async () => {
    const btn = document.getElementById("gen-draft-btn");
    btn.disabled = true;
    btn.textContent = "Preparing suggestions for the doctor...";
    const res = await fetch("/api/doctor/generate", { method: "POST" });
    const result = await res.json();
    if (!res.ok) { alert(result.error || "Could not prepare suggestions."); btn.disabled = false; btn.textContent = "🤖 Generate AI treatment suggestions"; return; }
    loadDoctorPanel();
  });

  document.getElementById("rx-add-row").addEventListener("click", () => addRxRow(null, foodOptions));

  document.getElementById("rx-approve-btn").addEventListener("click", async () => {
    const rows = collectRxRows();
    const body = {
      rows,
      tests: document.getElementById("rx-tests").value,
      advice: document.getElementById("rx-advice").value,
      review_after: document.getElementById("rx-review").value,
      doctor_name: document.getElementById("rx-doctor-name").value,
      registration_no: document.getElementById("rx-reg-no").value,
      confirm: document.getElementById("rx-confirm").checked,
    };
    const res = await fetch("/api/doctor/approve", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    const result = await res.json();
    const problemsBox = document.getElementById("rx-problems");
    if (!res.ok) {
      problemsBox.hidden = false;
      problemsBox.innerHTML = "Please fix before approving:<ul>" + result.problems.map((p) => `<li>${esc(p)}</li>`).join("") + "</ul>";
      return;
    }
    problemsBox.hidden = true;
    currentResult.prescription = result.rx;
    renderMedsTab(currentResult);
    loadDoctorPanel();
    alert("Approved. The patient can now see it in the Medicines tab and in the PDF.");
  });
}

function addRxRow(row, foodOptions) {
  const tbody = document.getElementById("rx-rows");
  const tr = document.createElement("tr");
  row = row || { Include: true, Medicine: "", Strength: "", Form: "Tablet",
    Morning: false, Afternoon: false, Night: false, Food: "After food", Duration: "", Instructions: "" };
  const forms = ["Tablet", "Capsule", "Syrup", "Injection", "Drops", "Ointment", "Sachet"];
  tr.innerHTML = `
    <td style="text-align:center"><input type="checkbox" class="c-include" ${row.Include ? "checked" : ""}></td>
    <td><input type="text" class="c-medicine" value="${esc(row.Medicine)}"></td>
    <td><input type="text" class="c-strength" value="${esc(row.Strength)}"></td>
    <td><select class="c-form">${forms.map((f) => `<option ${f === row.Form ? "selected" : ""}>${f}</option>`).join("")}</select></td>
    <td style="text-align:center"><input type="checkbox" class="c-morning" ${row.Morning ? "checked" : ""}></td>
    <td style="text-align:center"><input type="checkbox" class="c-afternoon" ${row.Afternoon ? "checked" : ""}></td>
    <td style="text-align:center"><input type="checkbox" class="c-night" ${row.Night ? "checked" : ""}></td>
    <td><select class="c-food">${foodOptions.map((f) => `<option ${f === row.Food ? "selected" : ""}>${f}</option>`).join("")}</select></td>
    <td><input type="text" class="c-duration" value="${esc(row.Duration)}"></td>
    <td><input type="text" class="c-instructions" value="${esc(row.Instructions)}"></td>
    <td><button class="c-remove" title="Remove row">✕</button></td>`;
  tr.querySelector(".c-remove").addEventListener("click", () => tr.remove());
  tbody.appendChild(tr);
}

function collectRxRows() {
  return Array.from(document.querySelectorAll("#rx-rows tr")).map((tr) => ({
    Include: tr.querySelector(".c-include").checked,
    Medicine: tr.querySelector(".c-medicine").value,
    Strength: tr.querySelector(".c-strength").value,
    Form: tr.querySelector(".c-form").value,
    Morning: tr.querySelector(".c-morning").checked,
    Afternoon: tr.querySelector(".c-afternoon").checked,
    Night: tr.querySelector(".c-night").checked,
    Food: tr.querySelector(".c-food").value,
    Duration: tr.querySelector(".c-duration").value,
    Instructions: tr.querySelector(".c-instructions").value,
  }));
}

// ---------------- restore on page refresh ----------------
(async function restore() {
  const res = await fetch("/api/state");
  const data = await res.json();
  if (data.result) {
    currentResult = data.result;
    el("workspace").hidden = false;
    renderResult(currentResult);
    renderImagePreview(currentResult);
  }
})();
