// 포털에 노출할 도구 목록.
// 새 도구를 추가하려면 여기에 항목 하나만 추가하세요.
//   status: "active" → 클릭 가능, "soon" → 준비 중(비활성)
const TOOLS = [
  {
    id: "jira",
    icon: "🪄",
    title: "Jira 이슈 자동 등록",
    desc: "대화 내용이나 메모를 붙여넣으면 AI가 업무별로 나눠 Jira 이슈로 등록합니다. (텍스트·이미지 지원)",
    href: "/tools/jira",
    status: "active",
    settingsHref: "/settings",
  },
  {
    id: "meeting",
    icon: "🗒️",
    title: "회의록 요약",
    desc: "회의 내용을 핵심 결정사항과 액션 아이템으로 정리합니다.",
    status: "soon",
  },
  {
    id: "report",
    icon: "📊",
    title: "주간 업무 보고",
    desc: "한 주간 처리한 이슈를 모아 주간 보고서 초안을 생성합니다.",
    status: "soon",
  },
];

function renderTools() {
  const grid = document.getElementById("toolGrid");
  grid.innerHTML = "";

  for (const t of TOOLS) {
    const card = document.createElement(t.status === "active" ? "a" : "div");
    card.className = "tool-card" + (t.status === "soon" ? " soon" : "");
    if (t.status === "active") {
      card.href = t.href;
    }

    const icon = document.createElement("div");
    icon.className = "tool-icon";
    icon.textContent = t.icon;
    card.appendChild(icon);

    const title = document.createElement("div");
    title.className = "tool-title";
    title.textContent = t.title;
    if (t.status === "soon") {
      const badge = document.createElement("span");
      badge.className = "tool-badge";
      badge.textContent = "준비 중";
      title.appendChild(badge);
    }
    card.appendChild(title);

    const desc = document.createElement("div");
    desc.className = "tool-desc";
    desc.textContent = t.desc;
    card.appendChild(desc);

    // active 도구에 설정 링크가 있으면 작은 링크 추가
    if (t.status === "active" && t.settingsHref) {
      const foot = document.createElement("div");
      foot.className = "tool-foot";
      const sett = document.createElement("a");
      sett.href = t.settingsHref;
      sett.textContent = "⚙️ 설정";
      sett.addEventListener("click", (e) => e.stopPropagation());
      foot.appendChild(sett);
      card.appendChild(foot);
    }

    grid.appendChild(card);
  }
}

(async function init() {
  for (let i = 0; i < 50 && !window.__me; i++) {
    await new Promise((r) => setTimeout(r, 50));
  }
  if (window.__me) {
    document.getElementById("greeting").textContent =
      `${window.__me.username}님, 안녕하세요 👋`;
  }
  renderTools();
})();
