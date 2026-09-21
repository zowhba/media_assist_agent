"""AM Client requests: fixed recipients, editable per-user descriptions."""
import secrets
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb

import db

PROJECTS = ("BTVVPN", "TESTBED")
DEFAULTS = {
    "BTVVPN": "안녕하세요. [SK C&C] 오지웅 입니다.\n금주 AM Client 사용신청서 제출합니다.\n\n{table}",
    "TESTBED": "1. 본인 계정만 신청 가능\n\n2. 접속지 IP 는 일별 2개로 제한, 최대 7일 신청 가능\n - https://ipaddress.co.kr (공인 IP 확인)\n3. Jira 댓글에 처리 결과 표시, 실패된 경우 N-IAM 웹에서 재 신청\n\n{table}",
}


def today():
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def build_issues(templates, start):
    if start.weekday() > 4:
        raise HTTPException(400, "주말에는 같은 주 금요일이 이미 지났습니다. 월요일~금요일에 신청해 주세요.")
    end = start + timedelta(days=4 - start.weekday())
    issues = []
    for project in PROJECTS:
        people = [("ojw", "오지웅")]
        if project == "BTVVPN":
            people += [("2200146", "이지영"), ("runa0477", "이윤주")]
        table = "||구분||N-IAM 계정명||사용자 이름||접속지 IP 정보||사용 시작일||사용 종료일||접속지 설명||신청 사유||\n"
        reason = "운영 모니터링" if project == "BTVVPN" else "운영 업무"
        for n, (account, name) in enumerate(people, 1):
            table += f"|{n}|{account}|{name}|58.234.3.132|{start:%Y-%m-%d}|{end:%Y-%m-%d}|사무실 업무 PC|{reason}|\n"
        template = templates[project]
        if template.count("{table}") != 1:
            raise HTTPException(400, f"{project} 설명에 {{table}}을 정확히 한 번 포함해 주세요.")
        description = template.replace("{table}", table).replace("{start_date}", start.isoformat()).replace("{end_date}", end.isoformat())
        fields = {
            "project": {"key": project}, "issuetype": {"name": "AM Client사용 신청서"},
            "priority": {"name": "Low"}, "assignee": {"name": "-1"},
            "summary": f"[EDMP] {start.month}/{start.day} AM Client 사용 신청",
            "description": description,
        }
        if project == "BTVVPN":
            fields["components"] = [{"name": name} for name in ("SOS", "SWU", "EDMP", "DSM", "SDS")]
        issues.append(fields)
    return issues


class Settings(BaseModel):
    BTVVPN: str = Field(min_length=1, max_length=20000)
    TESTBED: str = Field(min_length=1, max_length=20000)


class Draft(BaseModel):
    summary: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=32767)


class Submit(BaseModel):
    preview_id: str
    drafts: dict[str, Draft] = Field(default_factory=dict)


def load_settings(username):
    with db.get_conn() as conn:
        row = conn.execute("SELECT value FROM app_config WHERE key = %s", ("am_client:" + username,)).fetchone()
    return {**DEFAULTS, **(row[0] if row else {})}


def install(app, require_user, group_settings, serve, token):
    previews = {}

    @app.get("/tools/am-client")
    async def page(request: Request):
        try:
            require_user(request)
        except HTTPException:
            return RedirectResponse("/login")
        return serve("am-client.html")

    @app.get("/api/am-client/settings")
    async def settings(request: Request):
        return load_settings(require_user(request)["username"])

    @app.put("/api/am-client/settings")
    async def save(body: Settings, request: Request):
        user = require_user(request)
        data = body.model_dump()
        for project, value in data.items():
            if value.count("{table}") != 1:
                raise HTTPException(400, f"{project} 설명에 {{table}}을 정확히 한 번 포함해 주세요.")
        with db.get_conn() as conn:
            conn.execute("INSERT INTO app_config (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", ("am_client:" + user["username"], Jsonb(data)))
        return {"ok": True}

    @app.post("/api/am-client/preview")
    async def preview(request: Request):
        user, settings = group_settings(request)
        start = today()
        issues = build_issues(load_settings(user["username"]), start)
        for key in list(previews):
            if previews[key]["expires"] < time.monotonic():
                del previews[key]
        key = secrets.token_urlsafe(24)
        previews[key] = dict(user=user["username"], date=start, issues=issues, base_url=(settings.get("jira_base_url") or "").rstrip("/"), expires=time.monotonic()+1800, used=set())
        return {"preview_id": key, "start": start.isoformat(), "end": (start+timedelta(days=4-start.weekday())).isoformat(), "issues": issues}

    @app.post("/api/am-client/create")
    async def create(body: Submit, request: Request):
        user = require_user(request)
        item = previews.get(body.preview_id)
        if not item or item["user"] != user["username"] or item["expires"] < time.monotonic() or item["date"] != today():
            raise HTTPException(400, "미리보기가 만료되었습니다. 다시 생성해 주세요.")
        if not token or not item["base_url"]:
            raise HTTPException(400, "기존 Jira 설정의 Base URL과 서버 JIRA_ACCESS_TOKEN을 확인해 주세요.")
        if len(body.drafts) != 1 or not set(body.drafts).issubset(PROJECTS):
            raise HTTPException(400, "등록할 프로젝트의 초안 한 건만 전달해 주세요.")
        project = next(iter(body.drafts))
        if project in item["used"]:
            raise HTTPException(409, "이미 제출한 요청입니다. 결과와 Jira를 확인해 주세요.")
        if any(not draft.summary.strip() or not draft.description.strip() for draft in body.drafts.values()):
            raise HTTPException(400, "초안의 제목과 설명을 입력해 주세요.")
        item["used"].add(project)  # No await before this guard: prevent duplicate submissions.
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        results = []
        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            # Resolve display names rather than assuming a numeric priority ID.
            try:
                priorities = await client.get(item["base_url"] + "/rest/api/2/priority")
                priorities.raise_for_status()
                low = next((p for p in priorities.json() if p["name"] in ("Low", "낮음")), None)
                if not low:
                    raise ValueError("낮음(Low) 우선순위를 찾을 수 없습니다.")
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                item["used"].discard(project)
                raise HTTPException(400, "Jira 우선순위 조회 실패. 접속 설정과 권한을 확인해 주세요.") from exc
            for fields in item["issues"]:
                if fields["project"]["key"] != project:
                    continue
                draft = body.drafts[fields["project"]["key"]]
                fields = {**fields, "summary": draft.summary, "description": draft.description,
                          "priority": {"id": low["id"]}}
                project = fields["project"]["key"]
                try:
                    response = await client.post(item["base_url"] + "/rest/api/2/issue", json={"fields": fields})
                    if response.status_code == 201:
                        key = response.json()["key"]
                        results.append({"project": project, "ok": True, "key": key, "url": item["base_url"] + "/browse/" + key})
                    else:
                        results.append({"project": project, "ok": False, "error": f"Jira 응답 {response.status_code}: {response.text[:2000]}"})
                except (httpx.RequestError, ValueError, KeyError):
                    results.append({"project": project, "ok": False, "error": "응답을 확인하지 못했습니다. 중복 등록을 피하려면 Jira에서 생성 여부를 먼저 확인하세요."})
        return {"results": results}
