function setStatus(elId, kind, msg) {
  const el = document.getElementById(elId);
  el.className = "status " + kind;
  el.textContent = msg;
}

async function fetchGroups() {
  const r = await fetch("/api/settings-groups");
  if (!r.ok) return [];
  return (await r.json()).groups || [];
}

async function fetchUsers() {
  const r = await fetch("/api/users");
  if (!r.ok) throw new Error(await r.text());
  return (await r.json()).users || [];
}

function renderUsers(users) {
  const wrap = document.getElementById("user_list");
  wrap.innerHTML = "";

  const table = document.createElement("table");
  table.style.cssText = "width:100%; border-collapse:collapse; font-size:14px;";
  table.innerHTML = `
    <thead>
      <tr style="border-bottom:1px solid #d0d7de; text-align:left;">
        <th style="padding:8px 6px;">사용자명</th>
        <th style="padding:8px 6px;">권한</th>
        <th style="padding:8px 6px;">기본 그룹</th>
        <th style="padding:8px 6px; text-align:right;">동작</th>
      </tr>
    </thead>
  `;
  const tbody = document.createElement("tbody");

  for (const u of users) {
    const tr = document.createElement("tr");
    tr.style.borderBottom = "1px solid #eaeef2";
    tr.innerHTML = `
      <td style="padding:8px 6px;"><b>${u.username}</b></td>
      <td style="padding:8px 6px;">${u.is_admin ? '<span class="badge" style="background:#fff8c5;color:#7d4e00;">admin</span>' : '<span class="badge">user</span>'}</td>
      <td style="padding:8px 6px;">${u.default_group}</td>
    `;
    const td = document.createElement("td");
    td.style.cssText = "padding:8px 6px; text-align:right;";

    const resetBtn = document.createElement("button");
    resetBtn.className = "secondary";
    resetBtn.textContent = "비밀번호 초기화";
    resetBtn.style.cssText = "padding:5px 10px; font-size:12px; margin-right:6px;";
    resetBtn.addEventListener("click", () => resetPassword(u.username));

    const delBtn = document.createElement("button");
    delBtn.className = "danger";
    delBtn.textContent = "삭제";
    delBtn.style.cssText = "padding:5px 10px; font-size:12px;";
    delBtn.disabled = (window.__me && window.__me.username === u.username);
    delBtn.addEventListener("click", () => deleteUser(u.username));

    td.appendChild(resetBtn);
    td.appendChild(delBtn);
    tr.appendChild(td);
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  wrap.appendChild(table);
}

async function refresh() {
  const [groups, users] = await Promise.all([fetchGroups(), fetchUsers()]);
  const sel = document.getElementById("new_group");
  sel.innerHTML = "";
  for (const g of groups) {
    const o = document.createElement("option");
    o.value = g;
    o.textContent = g;
    sel.appendChild(o);
  }
  renderUsers(users);
}

async function createUser() {
  const username = document.getElementById("new_username").value.trim();
  const password = document.getElementById("new_password").value;
  const group = document.getElementById("new_group").value;
  const is_admin = document.getElementById("new_is_admin").value === "true";

  if (!username || !password) {
    setStatus("createStatus", "error", "사용자명과 비밀번호를 입력하세요.");
    return;
  }
  setStatus("createStatus", "info", "생성 중...");
  try {
    const r = await fetch("/api/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password, is_admin, default_group: group }),
    });
    if (!r.ok) throw new Error(await r.text());
    setStatus("createStatus", "success", `✓ "${username}" 생성됨.`);
    document.getElementById("new_username").value = "";
    document.getElementById("new_password").value = "";
    await refresh();
  } catch (e) {
    setStatus("createStatus", "error", "생성 실패: " + e.message);
  }
}

async function deleteUser(username) {
  if (!confirm(`정말 "${username}"을(를) 삭제하시겠습니까?`)) return;
  try {
    const r = await fetch(`/api/users/${encodeURIComponent(username)}`, { method: "DELETE" });
    if (!r.ok) throw new Error(await r.text());
    await refresh();
  } catch (e) {
    alert("삭제 실패: " + e.message);
  }
}

async function resetPassword(username) {
  const pw = prompt(`"${username}"의 새 비밀번호를 입력하세요 (4자 이상)`);
  if (!pw) return;
  try {
    const r = await fetch(`/api/users/${encodeURIComponent(username)}/reset-password`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ new_password: pw }),
    });
    if (!r.ok) throw new Error(await r.text());
    alert(`✓ "${username}"의 비밀번호가 변경되었습니다.`);
  } catch (e) {
    alert("초기화 실패: " + e.message);
  }
}

document.getElementById("create_btn").addEventListener("click", createUser);

(async function init() {
  for (let i = 0; i < 50 && !window.__me; i++) {
    await new Promise(r => setTimeout(r, 50));
  }
  await refresh();
})();
