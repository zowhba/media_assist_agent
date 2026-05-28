// Shared header: shows current user, default group, links, logout.
// Pages opt in by including <div id="userbar"></div> in the header and
// loading this script. If /api/me returns 401, redirects to /login.

async function loadUserBar() {
  let me;
  try {
    const r = await fetch("/api/me", { cache: "no-store" });
    if (r.status === 401) {
      window.location.href = "/login";
      return null;
    }
    if (!r.ok) throw new Error(await r.text());
    me = await r.json();
  } catch (e) {
    console.error("auth load failed:", e);
    return null;
  }

  window.__me = me;
  const bar = document.getElementById("userbar");
  if (!bar) return me;

  bar.style.cssText =
    "display:flex; align-items:center; gap:14px; font-size:13px;";
  bar.innerHTML = "";

  const userInfo = document.createElement("span");
  userInfo.innerHTML = `<b>${me.username}</b>${me.is_admin ? ' <span style="background:#fff8c5;color:#7d4e00;padding:1px 6px;border-radius:8px;font-size:11px;">admin</span>' : ""}`;
  bar.appendChild(userInfo);

  const groupBadge = document.createElement("span");
  groupBadge.textContent = `그룹: ${me.default_group}`;
  groupBadge.style.cssText = "opacity:0.85;";
  bar.appendChild(groupBadge);

  const sep = (h) => {
    const a = document.createElement("a");
    a.href = h;
    a.style.color = "#fff";
    a.style.opacity = "0.9";
    return a;
  };

  const homeA = sep("/");
  homeA.textContent = "메인";
  const settA = sep("/settings");
  settA.textContent = "설정";
  const accA = sep("/account");
  accA.textContent = "비밀번호";
  bar.appendChild(homeA);
  bar.appendChild(settA);
  bar.appendChild(accA);

  if (me.is_admin) {
    const usersA = sep("/users");
    usersA.textContent = "사용자관리";
    bar.appendChild(usersA);
  }

  const out = document.createElement("a");
  out.href = "#";
  out.textContent = "로그아웃";
  out.style.cssText = "color:#fff; opacity:0.9; cursor:pointer;";
  out.addEventListener("click", async (e) => {
    e.preventDefault();
    await fetch("/api/logout", { method: "POST" });
    window.location.href = "/login";
  });
  bar.appendChild(out);

  return me;
}

window.loadUserBar = loadUserBar;
