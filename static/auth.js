// Shared portal shell renderer.
//
// Every page includes <div id="app-shell"></div> at the top of <body> and
// calls renderShell(opts). It builds a persistent two-row header:
//   1) Top bar (always): 🎬 MAP brand + account nav (password / users / logout)
//   2) Sub bar (only when opts.context given): the current tool's title and
//      its tool-specific actions (settings link, group badge, ...).
//
// If /api/me returns 401, redirects to /login.
//
// opts = {
//   context: {
//     icon: "🪄",
//     title: "Jira 이슈 자동 등록",
//     showGroup: true,                       // show "그룹: XXX" badge
//     actions: [{ label: "⚙️ 설정", href: "/settings" }],
//   }
// }

async function renderShell(opts = {}) {
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

  const shell = document.getElementById("app-shell");
  if (!shell) return me;
  shell.innerHTML = "";

  // ---------- top bar (persistent) ----------
  const top = document.createElement("header");
  top.className = "topbar";

  const brand = document.createElement("a");
  brand.className = "brand";
  brand.href = "/";
  brand.innerHTML = '🎬 MAP <span class="brand-sub">Media Automation Portal</span>';
  top.appendChild(brand);

  const account = document.createElement("div");
  account.className = "account";

  const userSpan = document.createElement("span");
  userSpan.className = "acct-user";
  userSpan.innerHTML =
    `${me.username}` +
    (me.is_admin ? ' <span class="acct-admin">admin</span>' : "");
  account.appendChild(userSpan);

  const mkLink = (label, href, onclick) => {
    const a = document.createElement("a");
    a.textContent = label;
    a.href = href || "#";
    if (onclick) a.addEventListener("click", onclick);
    return a;
  };

  account.appendChild(mkLink("비밀번호", "/account"));
  if (me.is_admin) account.appendChild(mkLink("사용자관리", "/users"));
  account.appendChild(
    mkLink("로그아웃", null, async (e) => {
      e.preventDefault();
      await fetch("/api/logout", { method: "POST" });
      window.location.href = "/login";
    })
  );
  top.appendChild(account);
  shell.appendChild(top);

  // ---------- sub bar (per-tool, optional) ----------
  const ctx = opts.context;
  if (ctx) {
    const sub = document.createElement("div");
    sub.className = "subbar";

    const back = document.createElement("a");
    back.className = "ctx-back";
    back.href = "/";
    back.textContent = "←";
    back.title = "포털 홈";
    sub.appendChild(back);

    const title = document.createElement("div");
    title.className = "ctx-title";
    title.innerHTML = `${ctx.icon ? ctx.icon + " " : ""}${ctx.title || ""}`;
    sub.appendChild(title);

    const actions = document.createElement("div");
    actions.className = "ctx-actions";

    if (ctx.showGroup) {
      const g = document.createElement("span");
      g.className = "ctx-group";
      g.textContent = `그룹: ${me.default_group}`;
      g.title = "이 도구가 사용하는 설정 그룹";
      actions.appendChild(g);
    }
    for (const act of ctx.actions || []) {
      const a = document.createElement("a");
      a.href = act.href;
      a.textContent = act.label;
      actions.appendChild(a);
    }
    sub.appendChild(actions);
    shell.appendChild(sub);
  }

  return me;
}

window.renderShell = renderShell;
// backward compatibility (older inline calls)
window.loadUserBar = () => renderShell();
