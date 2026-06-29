// ---------- helpers ----------
function setStatus(el, kind, msg) {
  el.className = "status " + kind;
  el.textContent = msg;
}
function clearStatus(el) { el.className = ""; el.textContent = ""; }

// ---------- elements ----------
const $optCard = document.getElementById("optCard");
const $optState = document.getElementById("optState");
const $allClosed = document.getElementById("allClosed");
const $defaultAssignee = document.getElementById("defaultAssignee");
const $reportMonth = document.getElementById("reportMonth");
const $mdPerMm = document.getElementById("mdPerMm");
const $guidePrompt = document.getElementById("guidePrompt");
const $saveOpt = document.getElementById("saveOpt");
const $optStatus = document.getElementById("optStatus");

const $fileDrop = document.getElementById("fileDrop");
const $fileInput = document.getElementById("fileInput");
const $fileName = document.getElementById("fileName");
const $withAi = document.getElementById("withAi");
const $generate = document.getElementById("generate");
const $reset = document.getElementById("reset");
const $genStatus = document.getElementById("genStatus");

const $resultArea = document.getElementById("resultArea");
const $rowCount = document.getElementById("rowCount");
const $resultTableBody = document.querySelector("#resultTable tbody");
const $download = document.getElementById("download");
const $statsBox = document.getElementById("statsBox");
const $mmSummary = document.getElementById("mmSummary");
const $summaryBox = document.getElementById("summaryBox");
const $insightBox = document.getElementById("insightBox");
const $copyStats = document.getElementById("copyStats");
const $copyText = document.getElementById("copyText");
const $copyStatus = document.getElementById("copyStatus");
const $aiError = document.getElementById("aiError");

let selectedFile = null;
let lastXlsBase64 = null;
let lastDownloadName = "월간운영보고.xls";
let lastResult = null;

// ---------- options (persisted per account) ----------
function updateOptState() {
  const parts = [];
  if ($allClosed.checked) parts.push("모두 종료");
  if ($defaultAssignee.value.trim()) parts.push("담당자 고정");
  if ($guidePrompt.value.trim()) parts.push("가이드 ✓");
  $optState.textContent = parts.length ? parts.join(" · ") : "기본값";
}

async function loadOpts() {
  try {
    const r = await fetch("/api/monthly/config", { cache: "no-store" });
    if (!r.ok) return;
    const o = await r.json();
    $allClosed.checked = !!o.all_closed;
    $defaultAssignee.value = o.default_assignee || "";
    $reportMonth.value = o.report_month || "";
    $mdPerMm.value = o.md_per_mm || 20;
    $guidePrompt.value = o.guide_prompt || "";
    updateOptState();
  } catch (e) { console.error(e); }
}

$saveOpt.addEventListener("click", async () => {
  $saveOpt.disabled = true;
  setStatus($optStatus, "info", "저장 중...");
  try {
    const r = await fetch("/api/monthly/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        all_closed: $allClosed.checked,
        default_assignee: $defaultAssignee.value,
        md_per_mm: parseInt($mdPerMm.value, 10) || 20,
        report_month: $reportMonth.value,
        guide_prompt: $guidePrompt.value,
      }),
    });
    if (!r.ok) throw new Error(await r.text());
    setStatus($optStatus, "success", "✓ 옵션이 저장되었습니다. (다음 접속에도 기본값으로 적용)");
    updateOptState();
  } catch (e) {
    setStatus($optStatus, "error", "저장 실패: " + e.message);
  } finally {
    $saveOpt.disabled = false;
  }
});

[$allClosed, $defaultAssignee, $guidePrompt].forEach(el =>
  el.addEventListener("input", updateOptState));
$allClosed.addEventListener("change", updateOptState);

// ---------- file selection ----------
function setFile(f) {
  if (!f) return;
  selectedFile = f;
  $fileName.textContent = "선택됨: " + f.name;
  clearStatus($genStatus);
}
$fileDrop.addEventListener("click", () => $fileInput.click());
$fileInput.addEventListener("change", (e) => { setFile(e.target.files[0]); $fileInput.value = ""; });
["dragenter", "dragover"].forEach(ev =>
  $fileDrop.addEventListener(ev, (e) => { e.preventDefault(); $fileDrop.classList.add("dragover"); }));
["dragleave", "drop"].forEach(ev =>
  $fileDrop.addEventListener(ev, (e) => { e.preventDefault(); $fileDrop.classList.remove("dragover"); }));
$fileDrop.addEventListener("drop", (e) => {
  if (e.dataTransfer?.files?.length) setFile(e.dataTransfer.files[0]);
});

$reset.addEventListener("click", () => {
  selectedFile = null;
  $fileName.textContent = "";
  $resultArea.style.display = "none";
  clearStatus($genStatus);
});

// ---------- generate ----------
function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function renderResult(data) {
  lastResult = data;
  lastXlsBase64 = data.xls_base64;
  lastDownloadName = data.download_name || "월간운영보고.xls";

  $rowCount.textContent = data.count;
  // 미리보기 표
  $resultTableBody.innerHTML = data.rows.map(r =>
    `<tr><td>${esc(r.issue)}</td><td class="c">${esc(r.note)}</td>` +
    `<td class="c">${esc(r.status)}</td><td class="c">${esc(r.md)}</td>` +
    `<td class="c">${esc(r.assignee)}</td></tr>`
  ).join("");

  // 통계
  $statsBox.innerHTML = data.stats_html || "";
  $mmSummary.textContent = `— 합계 ${data.count}건 · 총 ${data.total_md} M/D · ${data.mm} M/M`;

  // 주요 업무 요약
  const sum = data.summary || {};
  const sysOrder = (data.stats && data.stats.systems) || Object.keys(sum);
  $summaryBox.innerHTML = sysOrder.filter(s => sum[s]).map(s =>
    `<p><b>${esc(s)}</b> – ${esc(sum[s])}</p>`
  ).join("") || `<p class="muted">생성된 요약이 없습니다.</p>`;

  // Insight
  const ins = data.insight || {};
  $insightBox.innerHTML = sysOrder.filter(s => (ins[s] || []).length).map(s =>
    `<div class="insight-sys"><b>${esc(s)}</b><ul>` +
    (ins[s] || []).map(c => `<li>${esc(c)}</li>`).join("") +
    `</ul></div>`
  ).join("") || `<p class="muted">생성된 Insight가 없습니다.</p>`;

  if (data.ai_error) setStatus($aiError, "info", data.ai_error);
  else clearStatus($aiError);

  $resultArea.style.display = "";
  $resultArea.scrollIntoView({ behavior: "smooth", block: "start" });
}

$generate.addEventListener("click", async () => {
  if (!selectedFile) {
    setStatus($genStatus, "error", "먼저 Jira export 파일을 선택해 주세요.");
    return;
  }
  $generate.disabled = true;
  setStatus($genStatus, "info", "파일을 분석하고 보고 내용을 생성 중입니다...");
  const form = new FormData();
  form.append("file", selectedFile, selectedFile.name);
  form.append("all_closed", $allClosed.checked ? "true" : "false");
  form.append("default_assignee", $defaultAssignee.value);
  form.append("md_per_mm", String(parseInt($mdPerMm.value, 10) || 20));
  form.append("report_month", $reportMonth.value);
  form.append("guide_prompt", $guidePrompt.value);
  form.append("with_ai", $withAi.checked ? "true" : "false");
  try {
    const r = await fetch("/api/monthly/generate", { method: "POST", body: form });
    if (!r.ok) throw new Error(await r.text());
    const data = await r.json();
    renderResult(data);
    setStatus($genStatus, "success", `✓ ${data.count}건 정리 완료. 아래에서 다운로드 및 PPT 내용을 확인하세요.`);
  } catch (e) {
    setStatus($genStatus, "error", "생성 실패: " + e.message);
  } finally {
    $generate.disabled = false;
  }
});

// ---------- download ----------
$download.addEventListener("click", () => {
  if (!lastXlsBase64) return;
  const bin = atob(lastXlsBase64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  const blob = new Blob([bytes], { type: "application/vnd.ms-excel" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = lastDownloadName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

// ---------- copy ----------
$copyStats.addEventListener("click", async () => {
  const tbl = $statsBox.querySelector("table");
  if (!tbl) return;
  try {
    const html = tbl.outerHTML;
    const text = tbl.innerText;
    if (navigator.clipboard && window.ClipboardItem) {
      await navigator.clipboard.write([new ClipboardItem({
        "text/html": new Blob([html], { type: "text/html" }),
        "text/plain": new Blob([text], { type: "text/plain" }),
      })]);
    } else {
      await navigator.clipboard.writeText(text);
    }
    setStatus($copyStatus, "success", "✓ 통계표가 복사되었습니다. PPT에 Ctrl+V 하세요.");
  } catch (e) {
    setStatus($copyStatus, "error", "복사 실패 — 표를 직접 드래그해 복사하세요.");
  }
});

$copyText.addEventListener("click", async () => {
  if (!lastResult) return;
  const sum = lastResult.summary || {};
  const ins = lastResult.insight || {};
  const order = (lastResult.stats && lastResult.stats.systems) || [];
  let txt = "[주요 업무]\n";
  order.forEach(s => { if (sum[s]) txt += `${s} – ${sum[s]}\n`; });
  txt += "\n[장애예방 / 운영 Insight]\n";
  order.forEach(s => {
    (ins[s] || []).forEach(c => { txt += `${s}: ${c}\n`; });
  });
  try {
    await navigator.clipboard.writeText(txt.trim());
    setStatus($copyStatus, "success", "✓ 요약·Insight 텍스트가 복사되었습니다.");
  } catch (e) {
    setStatus($copyStatus, "error", "복사 실패 — 직접 선택해 복사하세요.");
  }
});

loadOpts();
