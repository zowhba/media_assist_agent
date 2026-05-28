const $text = document.getElementById("text");
const $files = document.getElementById("files");
const $thumbs = document.getElementById("thumbs");
const $analyze = document.getElementById("analyze");
const $reset = document.getElementById("reset");
const $analyzeStatus = document.getElementById("analyzeStatus");
const $results = document.getElementById("results");

let imageBlobs = []; // {file: File, url: string}

function renderThumbs() {
  $thumbs.innerHTML = "";
  imageBlobs.forEach((item, idx) => {
    const wrap = document.createElement("div");
    wrap.className = "thumb";
    const img = document.createElement("img");
    img.src = item.url;
    wrap.appendChild(img);
    const btn = document.createElement("button");
    btn.className = "remove";
    btn.textContent = "×";
    btn.title = "제거";
    btn.onclick = () => {
      URL.revokeObjectURL(item.url);
      imageBlobs.splice(idx, 1);
      renderThumbs();
    };
    wrap.appendChild(btn);
    $thumbs.appendChild(wrap);
  });
}

function addFile(file) {
  if (!file || !file.type.startsWith("image/")) return;
  imageBlobs.push({ file, url: URL.createObjectURL(file) });
  renderThumbs();
}

$files.addEventListener("change", (e) => {
  for (const f of e.target.files) addFile(f);
  $files.value = "";
});

// Paste images directly into the textarea / page
document.addEventListener("paste", (e) => {
  const items = e.clipboardData?.items || [];
  let pastedImage = false;
  for (const item of items) {
    if (item.type && item.type.startsWith("image/")) {
      const f = item.getAsFile();
      if (f) {
        addFile(f);
        pastedImage = true;
      }
    }
  }
  if (pastedImage) e.preventDefault();
});

$reset.addEventListener("click", () => {
  $text.value = "";
  imageBlobs.forEach(i => URL.revokeObjectURL(i.url));
  imageBlobs = [];
  renderThumbs();
  $results.innerHTML = "";
  $analyzeStatus.innerHTML = "";
});

function setStatus(el, kind, msg) {
  el.className = "status " + kind;
  el.textContent = msg;
}

$analyze.addEventListener("click", async () => {
  const text = $text.value.trim();
  if (!text && imageBlobs.length === 0) {
    setStatus($analyzeStatus, "error", "대화 텍스트나 이미지를 입력해 주세요.");
    return;
  }

  $analyze.disabled = true;
  setStatus($analyzeStatus, "info", "Claude가 분석 중입니다...");
  $results.innerHTML = "";

  const form = new FormData();
  form.append("text", text);
  for (const it of imageBlobs) form.append("images", it.file, it.file.name || "image.png");

  try {
    const r = await fetch("/api/analyze", { method: "POST", body: form });
    if (!r.ok) throw new Error(await r.text());
    const data = await r.json();
    setStatus($analyzeStatus, "success", `✓ 이슈 ${data.issues.length}건 추출 완료`);
    renderIssues(data.issues);
  } catch (e) {
    setStatus($analyzeStatus, "error", "분석 실패: " + e.message);
  } finally {
    $analyze.disabled = false;
  }
});

function renderIssues(issues) {
  $results.innerHTML = "";

  const wrap = document.createElement("div");
  wrap.className = "card";
  const h = document.createElement("h2");
  h.textContent = `2. 추출된 업무 (${issues.length}건) — 검토/수정 후 카드별로 등록`;
  wrap.appendChild(h);
  $results.appendChild(wrap);

  issues.forEach((issue, idx) => {
    const card = buildIssueCard(issue, idx);
    wrap.appendChild(card);
  });
}

function buildIssueCard(issue, idx) {
  const card = document.createElement("div");
  card.className = "card issue-card";
  card.dataset.idx = idx;

  const title = document.createElement("h2");
  title.textContent = `업무 #${idx + 1}`;
  title.style.color = "#0969da";
  title.dataset.role = "title";
  card.appendChild(title);

  // placeholder for big "registered" banner (link to Jira)
  const banner = document.createElement("div");
  banner.dataset.role = "banner";
  card.appendChild(banner);

  const lbl1 = document.createElement("label");
  lbl1.textContent = "제목";
  const sumInput = document.createElement("input");
  sumInput.type = "text";
  sumInput.value = issue.summary || "";
  sumInput.dataset.field = "summary";
  card.appendChild(lbl1);
  card.appendChild(sumInput);

  const lbl2 = document.createElement("label");
  lbl2.textContent = "설명";
  const descInput = document.createElement("textarea");
  descInput.value = issue.description || "";
  descInput.dataset.field = "description";
  descInput.style.minHeight = "200px";
  card.appendChild(lbl2);
  card.appendChild(descInput);

  const row = document.createElement("div");
  row.className = "row";

  const prioCol = document.createElement("div");
  const lbl3 = document.createElement("label");
  lbl3.textContent = "우선순위";
  const prioInput = document.createElement("input");
  prioInput.type = "text";
  prioInput.value = issue.priority || "Medium";
  prioInput.dataset.field = "priority";
  prioCol.appendChild(lbl3);
  prioCol.appendChild(prioInput);

  const labCol = document.createElement("div");
  const lbl4 = document.createElement("label");
  lbl4.textContent = "레이블 (쉼표로 구분)";
  const labInput = document.createElement("input");
  labInput.type = "text";
  labInput.value = (issue.labels || []).join(", ");
  labInput.dataset.field = "labels";
  labCol.appendChild(lbl4);
  labCol.appendChild(labInput);

  row.appendChild(prioCol);
  row.appendChild(labCol);
  card.appendChild(row);

  const lbl5 = document.createElement("label");
  lbl5.innerHTML = '최초 추정 시간 <span class="hint">예: 1w, 3d, 4h, 30m</span>';
  const estInput = document.createElement("input");
  estInput.type = "text";
  estInput.value = issue.original_estimate || "1w";
  estInput.dataset.field = "original_estimate";
  estInput.style.maxWidth = "200px";
  card.appendChild(lbl5);
  card.appendChild(estInput);

  const actions = document.createElement("div");
  actions.className = "actions";
  const createBtn = document.createElement("button");
  createBtn.textContent = "🚀 이 업무 등록";
  actions.appendChild(createBtn);
  card.appendChild(actions);

  const status = document.createElement("div");
  card.appendChild(status);

  createBtn.addEventListener("click", () => createSingleIssue(card, status, createBtn));

  return card;
}

async function createSingleIssue(card, status, btn) {
  const issue = {
    summary: card.querySelector('[data-field="summary"]').value.trim(),
    description: card.querySelector('[data-field="description"]').value,
    priority: card.querySelector('[data-field="priority"]').value.trim() || "Medium",
    labels: card.querySelector('[data-field="labels"]').value
      .split(",").map(s => s.trim()).filter(Boolean),
    original_estimate: card.querySelector('[data-field="original_estimate"]').value.trim() || "1w",
  };

  if (!issue.summary) {
    setStatus(status, "error", "제목이 비어 있습니다.");
    return;
  }

  btn.disabled = true;
  const originalLabel = btn.textContent;
  btn.textContent = "등록 중...";
  setStatus(status, "info", "Jira에 등록 중입니다...");

  try {
    const r = await fetch("/api/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ issues: [issue] }),
    });
    if (!r.ok) throw new Error(await r.text());
    const data = await r.json();
    const result = data.results[0];

    if (result.ok) {
      // small status line
      status.className = "status success";
      status.textContent = `✓ 등록 완료`;

      // big banner at top of card with the Jira link
      const banner = card.querySelector('[data-role="banner"]');
      banner.innerHTML = "";
      banner.style.cssText =
        "background:#dafbe1;border:1px solid #2da44e;color:#1a7f37;" +
        "padding:12px 14px;border-radius:6px;margin:8px 0 16px;" +
        "display:flex;align-items:center;gap:10px;font-size:15px;font-weight:600;";

      const check = document.createElement("span");
      check.textContent = "✅";
      check.style.fontSize = "18px";
      banner.appendChild(check);

      const a = document.createElement("a");
      a.href = result.url;
      a.target = "_blank";
      a.rel = "noopener";
      a.textContent = `${result.key} — Jira에서 보기 ↗`;
      a.style.cssText = "color:#1a7f37;text-decoration:underline;";
      banner.appendChild(a);

      const urlSpan = document.createElement("span");
      urlSpan.textContent = result.url;
      urlSpan.style.cssText =
        "margin-left:auto;font-weight:400;font-size:12px;color:#57606a;" +
        "font-family:ui-monospace,SFMono-Regular,Menlo,monospace;";
      banner.appendChild(urlSpan);

      // mark card as done
      card.style.borderLeftColor = "#2da44e";
      card.querySelectorAll("input, textarea").forEach(el => (el.disabled = true));
      btn.textContent = "✓ 등록됨";
      btn.classList.add("secondary");
      btn.disabled = true;
    } else {
      status.className = "status error";
      status.innerHTML = "";

      const head = document.createElement("div");
      head.style.fontWeight = "600";
      head.textContent = `[${result.status || "ERR"}] ${result.error || "알 수 없는 오류"}`;
      status.appendChild(head);

      if (result.blocked) {
        const note = document.createElement("div");
        note.style.cssText = "margin-top:8px;padding:10px;background:#fff8c5;color:#7d4e00;border-radius:4px;line-height:1.5;";
        note.innerHTML =
          "<b>⚠ Jira 관리자 조치 필요</b><br>" +
          "이 계정의 REST API rate limit이 <code>0</code>으로 설정되어 모든 요청이 즉시 차단됩니다.<br>" +
          "Jira 관리자에게 <code>Administration → System → Rate limiting</code>에서 본인 계정의 한도를 올려달라고 요청하세요. " +
          "재시도해도 풀리지 않습니다.";
        status.appendChild(note);
      }

      if (result.response_headers) {
        const rh = document.createElement("details");
        rh.style.marginTop = "8px";
        const sum = document.createElement("summary");
        sum.textContent = "응답 헤더 보기";
        sum.style.cursor = "pointer";
        rh.appendChild(sum);
        const pre = document.createElement("pre");
        pre.style.cssText = "font-size:12px;white-space:pre-wrap;word-break:break-all;margin-top:6px;";
        pre.textContent = JSON.stringify(result.response_headers, null, 2);
        rh.appendChild(pre);
        status.appendChild(rh);
      }

      if (Array.isArray(result.attempts) && result.attempts.length > 0) {
        const at = document.createElement("details");
        at.style.marginTop = "8px";
        const sum = document.createElement("summary");
        sum.textContent = `재시도 이력 (${result.attempts.length}회)`;
        sum.style.cursor = "pointer";
        at.appendChild(sum);
        const pre = document.createElement("pre");
        pre.style.cssText = "font-size:12px;white-space:pre-wrap;word-break:break-all;margin-top:6px;";
        pre.textContent = JSON.stringify(result.attempts, null, 2);
        at.appendChild(pre);
        status.appendChild(at);
      }

      if (result.payload) {
        const pl = document.createElement("details");
        pl.style.marginTop = "8px";
        const sum = document.createElement("summary");
        sum.textContent = "요청 body 보기";
        sum.style.cursor = "pointer";
        pl.appendChild(sum);
        const pre = document.createElement("pre");
        pre.style.cssText = "font-size:12px;white-space:pre-wrap;word-break:break-all;margin-top:6px;";
        pre.textContent = JSON.stringify(result.payload, null, 2);
        pl.appendChild(pre);
        status.appendChild(pl);
      }

      btn.textContent = "↻ 재시도";
      btn.disabled = false;
    }
  } catch (e) {
    setStatus(status, "error", "등록 실패: " + e.message);
    btn.textContent = originalLabel;
    btn.disabled = false;
  }
}
