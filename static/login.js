const $u = document.getElementById("username");
const $p = document.getElementById("password");
const $btn = document.getElementById("login");
const $status = document.getElementById("status");

function setStatus(kind, msg) {
  $status.className = "status " + kind;
  $status.textContent = msg;
}

async function doLogin() {
  const u = $u.value.trim();
  const p = $p.value;
  if (!u || !p) { setStatus("error", "사용자명과 비밀번호를 입력하세요."); return; }
  $btn.disabled = true;
  setStatus("info", "로그인 중...");
  try {
    const r = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: u, password: p }),
    });
    if (!r.ok) {
      const txt = await r.text();
      throw new Error(txt);
    }
    setStatus("success", "✓ 로그인 성공. 이동합니다...");
    window.location.href = "/";
  } catch (e) {
    setStatus("error", "로그인 실패: " + e.message);
    $btn.disabled = false;
  }
}

$btn.addEventListener("click", doLogin);
for (const el of [$u, $p]) {
  el.addEventListener("keydown", (e) => {
    if (e.key === "Enter") doLogin();
  });
}
