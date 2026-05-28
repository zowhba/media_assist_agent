function setStatus(kind, msg) {
  const el = document.getElementById("status");
  el.className = "status " + kind;
  el.textContent = msg;
}

async function save() {
  const current = document.getElementById("current").value;
  const new1 = document.getElementById("new1").value;
  const new2 = document.getElementById("new2").value;
  if (!current || !new1 || !new2) {
    setStatus("error", "모든 필드를 입력하세요.");
    return;
  }
  if (new1 !== new2) {
    setStatus("error", "새 비밀번호가 일치하지 않습니다.");
    return;
  }
  setStatus("info", "변경 중...");
  try {
    const r = await fetch("/api/me/password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current, new: new1, new2 }),
    });
    if (!r.ok) throw new Error(await r.text());
    setStatus("success", "✓ 비밀번호가 변경되었습니다.");
    document.getElementById("current").value = "";
    document.getElementById("new1").value = "";
    document.getElementById("new2").value = "";
  } catch (e) {
    setStatus("error", "변경 실패: " + e.message);
  }
}

document.getElementById("save").addEventListener("click", save);
