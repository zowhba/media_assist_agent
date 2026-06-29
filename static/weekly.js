// ---------- helpers ----------
function setStatus(el, kind, msg) {
  el.className = "status " + kind;
  el.textContent = msg;
}
function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => {
      const res = r.result || "";
      const comma = res.indexOf(",");
      resolve(comma >= 0 ? res.slice(comma + 1) : res);
    };
    r.onerror = reject;
    r.readAsDataURL(file);
  });
}
function fileToText(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result || "");
    r.onerror = reject;
    r.readAsText(file);
  });
}

// ---------- format assets (persisted per user) ----------
const $formatText = document.getElementById("formatText");
const $formatDrop = document.getElementById("formatDrop");
const $formatFiles = document.getElementById("formatFiles");
const $formatThumbs = document.getElementById("formatThumbs");
const $saveFormat = document.getElementById("saveFormat");
const $formatStatus = document.getElementById("formatStatus");
const $guidePrompt = document.getElementById("guidePrompt");
const $settingsCard = document.getElementById("settingsCard");
const $settingsState = document.getElementById("settingsState");

// 설정(형식/가이드) 등록 여부를 요약 헤더에 표시
function updateSettingsState() {
  const hasFormat = !!($formatText.value.trim()) || formatAssets.length > 0;
  const hasGuide = !!($guidePrompt.value.trim());
  if (hasFormat || hasGuide) {
    const parts = [];
    if (hasFormat) parts.push("형식 ✓");
    if (hasGuide) parts.push("가이드 ✓");
    $settingsState.textContent = parts.join(" · ");
  } else {
    $settingsState.textContent = "미등록 — 먼저 설정해 주세요";
  }
}

// each: { name, media_type, data(base64) }
let formatAssets = [];

function renderFormatThumbs() {
  $formatThumbs.innerHTML = "";
  formatAssets.forEach((a, idx) => {
    const wrap = document.createElement("div");
    wrap.className = "thumb";
    const img = document.createElement("img");
    img.src = `data:${a.media_type};base64,${a.data}`;
    img.alt = a.name || "format";
    wrap.appendChild(img);
    const btn = document.createElement("button");
    btn.className = "remove";
    btn.textContent = "×";
    btn.title = "제거";
    btn.onclick = () => { formatAssets.splice(idx, 1); renderFormatThumbs(); };
    wrap.appendChild(btn);
    $formatThumbs.appendChild(wrap);
  });
  updateSettingsState();
}

$formatText.addEventListener("input", updateSettingsState);
$guidePrompt.addEventListener("input", updateSettingsState);

async function handleFormatFiles(files) {
  for (const f of files) {
    if (f.type.startsWith("image/")) {
      const data = await fileToBase64(f);
      formatAssets.push({ name: f.name || "image.png", media_type: f.type || "image/png", data });
    } else if (f.type === "text/plain" || f.name.endsWith(".txt")) {
      // 텍스트 형식 파일 → 형식 텍스트에 채워넣음
      const t = await fileToText(f);
      $formatText.value = $formatText.value ? ($formatText.value + "\n\n" + t) : t;
    }
  }
  renderFormatThumbs();
}

$formatDrop.addEventListener("click", () => $formatFiles.click());
$formatFiles.addEventListener("change", (e) => { handleFormatFiles(e.target.files); $formatFiles.value = ""; });
["dragenter", "dragover"].forEach(ev =>
  $formatDrop.addEventListener(ev, (e) => { e.preventDefault(); $formatDrop.classList.add("dragover"); }));
["dragleave", "drop"].forEach(ev =>
  $formatDrop.addEventListener(ev, (e) => { e.preventDefault(); $formatDrop.classList.remove("dragover"); }));
$formatDrop.addEventListener("drop", (e) => {
  if (e.dataTransfer?.files?.length) handleFormatFiles(e.dataTransfer.files);
});

async function loadFormat() {
  try {
    const r = await fetch("/api/weekly/config", { cache: "no-store" });
    if (!r.ok) return;
    const cfg = await r.json();
    $formatText.value = cfg.format_text || "";
    $guidePrompt.value = cfg.guide_prompt || "";
    formatAssets = Array.isArray(cfg.format_assets) ? cfg.format_assets : [];
    renderFormatThumbs();
    updateSettingsState();
    // 설정이 비어 있으면 자동으로 펼쳐서 입력을 유도
    const empty = !$formatText.value.trim() && formatAssets.length === 0 && !$guidePrompt.value.trim();
    if (empty) $settingsCard.open = true;
  } catch (e) { console.error(e); }
}

$saveFormat.addEventListener("click", async () => {
  $saveFormat.disabled = true;
  setStatus($formatStatus, "info", "저장 중...");
  try {
    const r = await fetch("/api/weekly/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        format_text: $formatText.value,
        format_assets: formatAssets,
        guide_prompt: $guidePrompt.value,
      }),
    });
    if (!r.ok) throw new Error(await r.text());
    setStatus($formatStatus, "success", "✓ 설정이 저장되었습니다. (다음 접속에도 유지됩니다)");
    updateSettingsState();
  } catch (e) {
    setStatus($formatStatus, "error", "저장 실패: " + e.message);
  } finally {
    $saveFormat.disabled = false;
  }
});

// ---------- this week's memo ----------
const $memoText = document.getElementById("memoText");
const $memoFiles = document.getElementById("memoFiles");
const $memoThumbs = document.getElementById("memoThumbs");
const $generate = document.getElementById("generate");
const $resetMemo = document.getElementById("resetMemo");
const $genStatus = document.getElementById("genStatus");
const $resultCard = document.getElementById("resultCard");
const $draft = document.getElementById("draft");
const $copyRich = document.getElementById("copyRich");
const $copyText = document.getElementById("copyText");
const $copyStatus = document.getElementById("copyStatus");
const $regen = document.getElementById("regen");

// Claude가 준 HTML에서 위험 요소(script/style/on*)를 제거
function sanitizeHtml(html) {
  const tpl = document.createElement("template");
  tpl.innerHTML = html || "";
  tpl.content.querySelectorAll("script, style, link, meta").forEach(n => n.remove());
  tpl.content.querySelectorAll("*").forEach(el => {
    [...el.attributes].forEach(attr => {
      if (/^on/i.test(attr.name)) el.removeAttribute(attr.name);
    });
  });
  return tpl.innerHTML;
}

let memoImages = []; // { file, url }

function renderMemoThumbs() {
  $memoThumbs.innerHTML = "";
  memoImages.forEach((it, idx) => {
    const wrap = document.createElement("div");
    wrap.className = "thumb";
    const img = document.createElement("img");
    img.src = it.url;
    wrap.appendChild(img);
    const btn = document.createElement("button");
    btn.className = "remove";
    btn.textContent = "×";
    btn.onclick = () => { URL.revokeObjectURL(it.url); memoImages.splice(idx, 1); renderMemoThumbs(); };
    wrap.appendChild(btn);
    $memoThumbs.appendChild(wrap);
  });
}
function addMemoImage(file) {
  if (!file || !file.type.startsWith("image/")) return;
  memoImages.push({ file, url: URL.createObjectURL(file) });
  renderMemoThumbs();
}
$memoFiles.addEventListener("change", (e) => { for (const f of e.target.files) addMemoImage(f); $memoFiles.value = ""; });
document.addEventListener("paste", (e) => {
  // 메모 영역에 포커스가 있을 때만 이미지 붙여넣기 처리
  const items = e.clipboardData?.items || [];
  let pasted = false;
  for (const it of items) {
    if (it.type && it.type.startsWith("image/")) {
      const f = it.getAsFile();
      if (f) { addMemoImage(f); pasted = true; }
    }
  }
  if (pasted) e.preventDefault();
});
$resetMemo.addEventListener("click", () => {
  $memoText.value = "";
  memoImages.forEach(i => URL.revokeObjectURL(i.url));
  memoImages = [];
  renderMemoThumbs();
});

async function generate() {
  if (!$memoText.value.trim() && memoImages.length === 0) {
    setStatus($genStatus, "error", "이번 주 업무 내용을 입력해 주세요.");
    return;
  }
  $generate.disabled = true; $regen.disabled = true;
  setStatus($genStatus, "info", "Claude가 주간 보고 초안을 작성 중입니다...");
  const form = new FormData();
  form.append("text", $memoText.value);
  for (const it of memoImages) form.append("images", it.file, it.file.name || "image.png");
  try {
    const r = await fetch("/api/weekly/generate", { method: "POST", body: form });
    if (!r.ok) throw new Error(await r.text());
    const data = await r.json();
    $draft.innerHTML = sanitizeHtml(data.draft_html || "");
    $resultCard.style.display = "";
    setStatus($genStatus, "success", "✓ 초안이 생성되었습니다. 아래에서 수정 후 '서식 유지 복사'로 아웃룩에 붙여넣으세요.");
    $resultCard.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    setStatus($genStatus, "error", "생성 실패: " + e.message);
  } finally {
    $generate.disabled = false; $regen.disabled = false;
  }
}
$generate.addEventListener("click", generate);
$regen.addEventListener("click", generate);

// 서식 유지(HTML) 복사 — 아웃룩 등에 붙여넣으면 서식 유지
$copyRich.addEventListener("click", async () => {
  const html = $draft.innerHTML;
  const text = $draft.innerText;
  try {
    if (navigator.clipboard && window.ClipboardItem) {
      const item = new ClipboardItem({
        "text/html": new Blob([html], { type: "text/html" }),
        "text/plain": new Blob([text], { type: "text/plain" }),
      });
      await navigator.clipboard.write([item]);
      setStatus($copyStatus, "success", "✓ 서식 유지로 복사됨 — 아웃룩 본문에 Ctrl+V 하세요.");
      return;
    }
    throw new Error("ClipboardItem 미지원");
  } catch (e) {
    // 폴백: 에디터 내용을 선택 후 execCommand('copy')
    try {
      const range = document.createRange();
      range.selectNodeContents($draft);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
      const ok = document.execCommand("copy");
      sel.removeAllRanges();
      if (!ok) throw new Error("execCommand 실패");
      setStatus($copyStatus, "success", "✓ 서식 유지로 복사됨 — 아웃룩 본문에 Ctrl+V 하세요.");
    } catch (e2) {
      setStatus($copyStatus, "error", "자동 복사 실패 — 본문을 드래그해서 직접 복사하세요.");
    }
  }
});

// 텍스트만 복사
$copyText.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText($draft.innerText);
    setStatus($copyStatus, "success", "✓ 텍스트로 복사되었습니다.");
  } catch (e) {
    setStatus($copyStatus, "error", "복사 실패 — 직접 선택해 복사하세요.");
  }
});

loadFormat();
