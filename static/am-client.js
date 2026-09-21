const el = (id) => document.getElementById(id);
let previewId = null;
let dirty = false;
let draftEditors = [];
let pendingSubmissions = 0;
async function api(path, method = 'GET', body) {
  const response = await fetch('/api/am-client/' + path, {
    method, headers: {'Content-Type': 'application/json'},
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '요청 처리에 실패했습니다. 입력과 로그인 상태를 확인해 주세요.');
  return data;
}
function invalidate() {
  previewId = null;

  el('preview-card').hidden = true;
}
for (const id of ['btv', 'testbed']) el(id).addEventListener('input', () => {
  dirty = true; invalidate(); el('settings-status').textContent = '변경 내용을 저장한 후 미리보기를 생성해 주세요.';
});
el('save').onclick = async () => {
  el('save').disabled = true;
  try {
    await api('settings', 'PUT', {BTVVPN: el('btv').value, TESTBED: el('testbed').value});
    dirty = false; invalidate(); el('settings-status').textContent = '기본값을 저장했습니다.';
  } catch (error) { el('settings-status').textContent = error.message; }
  finally { el('save').disabled = false; }
};
el('preview').onclick = async () => {
  if (dirty) { el('status').textContent = '설명 변경 내용을 먼저 저장해 주세요.'; return; }
  el('preview').disabled = true; invalidate();
  try {
    const data = await api('preview', 'POST');
    previewId = data.preview_id;
    el('period').textContent = `${data.start} ~ ${data.end}`;
    el('issues').replaceChildren();
    draftEditors = [];
    for (const issue of data.issues) {
      const title = document.createElement('h3');
      title.textContent = `${issue.project.key} — ${issue.summary}`;
      const components = document.createElement('p');
      components.textContent = '구성 요소: ' + (issue.components?.map(x => x.name).join(', ') || '없음');
      const summaryLabel = document.createElement('label');
      summaryLabel.textContent = '제목';
      const summary = document.createElement('input');
      summary.id = `summary-${issue.project.key}`;
      summaryLabel.htmlFor = summary.id;
      summary.type = 'text'; summary.maxLength = 255; summary.required = true;
      summary.value = issue.summary;
      const descriptionLabel = document.createElement('label');
      descriptionLabel.textContent = '설명 (이번 신청에만 적용 · Jira 표 문법 포함)';
      const description = document.createElement('textarea');
      description.id = `description-${issue.project.key}`;
      descriptionLabel.htmlFor = description.id;
      description.rows = 14; description.maxLength = 32767; description.required = true;
      description.value = issue.description;
      const button = document.createElement('button');
      button.textContent = `${issue.project.key} 등록`;
      const result = document.createElement('div');
      result.setAttribute('role', 'status'); result.setAttribute('aria-live', 'polite');
      const editor = {project: issue.project.key, summary, description, button, result, previewId};
      button.onclick = () => submitDraft(editor);
      draftEditors.push(editor);
      const card = document.createElement('section'); card.className = 'card';
      card.append(title, components, summaryLabel, summary, descriptionLabel, description, button, result);
      el('issues').append(card);
    }
    el('preview-card').hidden = false;
    el('status').textContent = '초안의 제목·설명을 확인하고 수정한 뒤 각 초안의 등록 버튼을 눌러 주세요. 미리보기는 30분간 유효합니다.';
  } catch (error) { el('status').textContent = error.message; }
  finally { el('preview').disabled = false; }
};
async function submitDraft(editor) {
  if (editor.button.disabled || !previewId) return;
  if (!editor.summary.value.trim() || !editor.description.value.trim()) {
    editor.result.textContent = '제목과 설명을 입력해 주세요.';
    return;
  }
  const drafts = {[editor.project]: {summary: editor.summary.value, description: editor.description.value}};
  editor.button.disabled = true;
  editor.summary.disabled = true; editor.description.disabled = true;
  pendingSubmissions++;
  for (const id of ['preview', 'save', 'btv', 'testbed']) el(id).disabled = true;
  editor.result.textContent = 'Jira에 등록 중입니다…';
  try {
    const data = await api('create', 'POST', {preview_id: editor.previewId, drafts});
    const result = data.results[0];
    editor.result.textContent = result.ok ? '등록 완료 — ' : result.error;
    editor.button.textContent = result.ok ? '등록 완료' : '등록 결과 확인 필요';
    if (result.ok) {
      const link = document.createElement('a');
      const url = new URL(result.url);
      if (['https:', 'http:'].includes(url.protocol)) link.href = url.href;
      link.textContent = `${result.key} · Jira에서 확인`;
      link.target = '_blank'; link.rel = 'noopener'; editor.result.append(link);
    }
  } catch (error) {
    editor.result.textContent = error.message + ' 재신청 전 Jira에서 생성 여부를 확인해 주세요.';
    editor.button.textContent = '등록 결과 확인 필요';
  } finally {
    pendingSubmissions--;
    if (!pendingSubmissions) {
      for (const id of ['preview', 'save', 'btv', 'testbed']) el(id).disabled = false;
    }
    el('status').textContent = '각 초안에서 등록 결과와 Jira 링크를 확인하세요. 새 미리보기는 새 신청이므로 이미 등록한 건을 중복 신청하지 않도록 확인해 주세요.';
  }
}

(async () => {
  if (location.hash === '#settings') el('settings').open = true;
  try {
    const data = await api('settings');
    el('btv').value = data.BTVVPN; el('testbed').value = data.TESTBED;
    el('save').disabled = false; el('preview').disabled = false;
    el('status').textContent = '설명 기본값을 확인하거나 바로 미리보기를 생성하세요.';
  } catch (error) { el('status').textContent = error.message; }
})();
