const fields = [
  "jira_base_url", "project_key", "issue_type",
  "summary_prefix",
  "reporter", "assignee",
  "company_field_id", "company_parent_id", "company_child_id",
  "category_field_id", "category_parent", "category_child",
  "fix_version",
  "claude_model",
];
const csvFields = ["priority_options", "fixed_labels", "dynamic_label_pool"];

const DEFAULTS = {
  company_field_id: "customfield_11102",
  company_parent_id: "11327",
  company_child_id: "11332",
  claude_model: "claude-sonnet-4-6",
};

let currentGroup = null;       // the group we are currently EDITING
let myDefaultGroup = null;     // the user's default group (from /api/me)
let isAdmin = false;

function toCsv(arr) { return Array.isArray(arr) ? arr.join(", ") : (arr || ""); }
function fromCsv(s) {
  return (s || "")
    .split(",")
    .map(x => x.trim())
    .filter(Boolean);
}

function setStatus(el, kind, msg) {
  el.className = "status " + kind;
  el.textContent = msg;
}

function populateForm(data) {
  for (const k of fields) {
    const el = document.getElementById(k);
    if (!el) continue;
    const saved = data[k];
    if (saved !== undefined && saved !== null && saved !== "") {
      el.value = saved;
    } else if (DEFAULTS[k] !== undefined) {
      el.value = DEFAULTS[k];
    } else {
      el.value = "";
    }
  }
  for (const k of csvFields) {
    const el = document.getElementById(k);
    if (!el) continue;
    el.value = toCsv(data[k]);
  }
  if (!data.priority_options) {
    document.getElementById("priority_options").value =
      "Highest, High, Medium, Low, Lowest";
  }
}

function refreshDeleteButton() {
  const btn = document.getElementById("delete_group");
  btn.style.display = (isAdmin && currentGroup !== "default") ? "" : "none";
}

async function loadGroupList() {
  const r = await fetch("/api/settings-groups", { cache: "no-store" });
  if (!r.ok) throw new Error(await r.text());
  const { groups } = await r.json();

  const sel = document.getElementById("group_select");
  sel.innerHTML = "";
  for (const g of groups) {
    const opt = document.createElement("option");
    opt.value = g;
    opt.textContent = g === myDefaultGroup ? `${g} ★ (내 기본)` : g;
    sel.appendChild(opt);
  }
  if (!currentGroup || !groups.includes(currentGroup)) {
    currentGroup = myDefaultGroup && groups.includes(myDefaultGroup) ? myDefaultGroup : groups[0];
  }
  sel.value = currentGroup;
  refreshDeleteButton();
}

async function loadGroupData(name) {
  const r = await fetch(`/api/settings-groups/${encodeURIComponent(name)}`, { cache: "no-store" });
  if (!r.ok) throw new Error(await r.text());
  const data = await r.json();
  populateForm(data);
}

async function save() {
  const status = document.getElementById("saveStatus");
  const payload = {};
  for (const k of fields) {
    const el = document.getElementById(k);
    if (!el) continue;
    payload[k] = (el.value || "").trim();
  }
  for (const k of csvFields) {
    payload[k] = fromCsv(document.getElementById(k).value);
  }
  setStatus(status, "info", `저장 중 (그룹: ${currentGroup})...`);
  try {
    const r = await fetch(`/api/settings-groups/${encodeURIComponent(currentGroup)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!r.ok) throw new Error(await r.text());
    const result = await r.json();
    const childId = result.saved?.company_child_id;
    const childMap = { "11331": "NCMS", "11332": "ACS", "13401": "EDMP", "13402": "EUXP" };
    const childLabel = childMap[childId] || childId || "(none)";
    setStatus(status, "success", `✓ 저장 완료 — 그룹: ${currentGroup}, 시스템: ${childLabel}`);
  } catch (e) {
    setStatus(status, "error", "저장 실패: " + e.message);
  }
}

async function setAsDefault() {
  const status = document.getElementById("groupStatus");
  setStatus(status, "info", `"${currentGroup}"을(를) 내 기본 그룹으로 지정 중...`);
  try {
    const r = await fetch("/api/me/default-group", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ group: currentGroup }),
    });
    if (!r.ok) throw new Error(await r.text());
    myDefaultGroup = currentGroup;
    await loadGroupList();
    setStatus(status, "success", `✓ "${currentGroup}"이(가) 내 기본 그룹으로 지정되었습니다.`);
  } catch (e) {
    setStatus(status, "error", "지정 실패: " + e.message);
  }
}

async function createNewGroup() {
  const name = (prompt("새 그룹 이름 (영문/숫자/한글)") || "").trim();
  if (!name) return;
  if (/[/\\]/.test(name) || name.startsWith(".")) {
    alert("이름에 '/', '\\\\', 시작에 '.'은 사용할 수 없습니다."); return;
  }
  const status = document.getElementById("groupStatus");
  setStatus(status, "info", `"${name}" 그룹 생성 중...`);
  try {
    const r = await fetch(`/api/settings-groups/${encodeURIComponent(name)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    if (!r.ok) throw new Error(await r.text());
    currentGroup = name;
    await loadGroupList();
    document.getElementById("group_select").value = name;
    await loadGroupData(name);
    setStatus(status, "success", `✓ 새 그룹 "${name}" 생성됨. 값 입력 후 저장하세요.`);
  } catch (e) {
    setStatus(status, "error", "생성 실패: " + e.message);
  }
}

async function deleteCurrentGroup() {
  if (currentGroup === "default") {
    alert("'default' 그룹은 삭제할 수 없습니다."); return;
  }
  if (!confirm(`정말 "${currentGroup}" 그룹을 삭제하시겠습니까?\n이 그룹을 사용 중인 사용자는 default로 되돌아갑니다.`)) return;
  const status = document.getElementById("groupStatus");
  try {
    const r = await fetch(`/api/settings-groups/${encodeURIComponent(currentGroup)}`, {
      method: "DELETE",
    });
    if (!r.ok) throw new Error(await r.text());
    setStatus(status, "success", `✓ "${currentGroup}" 삭제됨.`);
    currentGroup = null;
    await loadGroupList();
    await loadGroupData(currentGroup);
  } catch (e) {
    setStatus(status, "error", "삭제 실패: " + e.message);
  }
}

document.getElementById("save").addEventListener("click", save);
document.getElementById("set_default").addEventListener("click", setAsDefault);
document.getElementById("new_group").addEventListener("click", createNewGroup);
document.getElementById("delete_group").addEventListener("click", deleteCurrentGroup);
document.getElementById("group_select").addEventListener("change", async (e) => {
  currentGroup = e.target.value;
  refreshDeleteButton();
  await loadGroupData(currentGroup);
});

(async function init() {
  // wait briefly for auth.js to populate window.__me
  for (let i = 0; i < 50 && !window.__me; i++) {
    await new Promise(r => setTimeout(r, 50));
  }
  if (!window.__me) return; // auth.js will redirect
  myDefaultGroup = window.__me.default_group || "default";
  isAdmin = !!window.__me.is_admin;
  currentGroup = myDefaultGroup;

  await loadGroupList();
  await loadGroupData(currentGroup);
})();
