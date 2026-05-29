import os
import json
import time
import base64
import asyncio
import logging
import sys
import secrets
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request, Depends
from fastapi.responses import FileResponse, JSONResponse, Response, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
import httpx
import anthropic

import db

# --- logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
for noisy in ("httpx", "httpcore", "httpcore.http11", "httpcore.connection",
              "anthropic", "urllib3", "asyncio"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
log = logging.getLogger("jira_agent")
log.setLevel(logging.DEBUG)


def _mask_token(tok: str) -> str:
    if not tok:
        return "(empty)"
    if len(tok) <= 8:
        return "***"
    return f"{tok[:4]}...{tok[-4:]} (len={len(tok)})"


def _pretty_json(obj) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        return str(obj)


BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

JIRA_TOKEN = os.getenv("JIRA_ACCESS_TOKEN", "")
CLAUDE_KEY = os.getenv("CLAUDE_API_KEY", "")

# Legacy file paths — only used to import existing data into the DB once.
USERS_PATH = BASE_DIR / "users.json"
GROUPS_DIR = BASE_DIR / "groups"
LEGACY_SETTINGS = BASE_DIR / "settings.json"

# In-memory session store: {token: {"username": str, "expires_at": datetime}}
SESSIONS: dict = {}
SESSION_TTL = timedelta(days=7)
COOKIE_NAME = "session"


# ---------- password / users ----------

def hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    if salt is None:
        salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), 200_000
    )
    return h.hex(), salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    h, _ = hash_password(password, salt)
    return secrets.compare_digest(h, password_hash)


# Storage is backed by PostgreSQL (db.py). These names are re-exported so the
# rest of the app keeps calling them unchanged.
load_users = db.load_users
save_users = db.save_users
list_groups = db.list_groups
load_group = db.load_group
save_group = db.save_group
delete_group = db.delete_group
load_group_template = db.load_group_template
save_group_template = db.save_group_template

GROUP_TEMPLATE_PATH = BASE_DIR / "group_template.json"


def _read_json_file(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("파일 읽기 실패 %s: %s", path, e)
        return None


def bootstrap_data():
    """DB 스키마 생성 + 최초 1회 파일 데이터 이관 + admin 계정 보장."""
    db.init_schema()

    # 1) 설정 그룹: DB가 비어 있으면 groups/*.json 이관
    if not db.list_groups():
        imported = 0
        if GROUPS_DIR.exists():
            for p in sorted(GROUPS_DIR.glob("*.json")):
                data = _read_json_file(p)
                if data is not None:
                    db.save_group(p.stem, data)
                    imported += 1
        # 레거시 settings.json도 default로 흡수
        if LEGACY_SETTINGS.exists() and not db.group_exists("default"):
            data = _read_json_file(LEGACY_SETTINGS)
            if data is not None:
                db.save_group("default", data)
        if not db.group_exists("default"):
            db.save_group("default", {})
        if imported:
            log.info("Imported %d settings group(s) from files into DB.", imported)

    # 2) 그룹 템플릿: DB에 없으면 파일에서, 그것도 없으면 default 그룹 값으로 시드
    if not db.load_group_template():
        tpl = None
        if GROUP_TEMPLATE_PATH.exists():
            tpl = _read_json_file(GROUP_TEMPLATE_PATH)
        if not tpl:
            default_data = db.load_group("default")
            if default_data:
                tpl = default_data
        if tpl:
            db.save_group_template(tpl)
            log.info("Seeded group template into DB.")

    # 3) 사용자: DB가 비어 있으면 users.json 이관, 없으면 admin/admin 생성
    if not db.load_users()["users"]:
        data = _read_json_file(USERS_PATH) if USERS_PATH.exists() else None
        if data and data.get("users"):
            db.save_users(data)
            log.info("Imported %d user(s) from users.json into DB.", len(data["users"]))
        else:
            pw_hash, salt = hash_password("admin")
            db.save_users({
                "users": {
                    "admin": {
                        "password_hash": pw_hash,
                        "salt": salt,
                        "is_admin": True,
                        "default_group": "default",
                    }
                }
            })
            log.warning("Bootstrap admin user created: admin / admin -- 비밀번호를 즉시 변경하세요.")


# ---------- sessions ----------

def get_current_user(request: Request) -> Optional[dict]:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    s = SESSIONS.get(token)
    if not s:
        return None
    if datetime.now() > s["expires_at"]:
        SESSIONS.pop(token, None)
        return None
    users = load_users()
    info = users["users"].get(s["username"])
    if not info:
        return None
    return {"username": s["username"], **info}


def require_user(request: Request) -> dict:
    user = get_current_user(request)
    if not user:
        raise HTTPException(401, "로그인이 필요합니다.")
    return user


def require_admin(request: Request) -> dict:
    user = require_user(request)
    if not user.get("is_admin"):
        raise HTTPException(403, "관리자 권한이 필요합니다.")
    return user


# ---------- app ----------

app = FastAPI(title="MAP — Media Automation Portal")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.middleware("http")
async def no_cache_middleware(request: Request, call_next):
    response: Response = await call_next(request)
    p = request.url.path
    if (
        p.startswith(("/static", "/api/", "/tools"))
        or p in ("/", "/settings", "/login", "/account", "/users")
    ):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.on_event("startup")
async def _startup():
    bootstrap_data()


@app.on_event("shutdown")
async def _shutdown():
    if db._pool is not None:
        db._pool.close()


claude = anthropic.Anthropic(api_key=CLAUDE_KEY) if CLAUDE_KEY else None


# ---------- page routes ----------

def _serve(name: str) -> FileResponse:
    return FileResponse(BASE_DIR / "static" / name)


@app.get("/login")
async def login_page():
    return _serve("login.html")


@app.get("/")
async def portal_page(request: Request):
    if not get_current_user(request):
        return RedirectResponse("/login")
    return _serve("portal.html")


@app.get("/tools/jira")
async def jira_tool_page(request: Request):
    if not get_current_user(request):
        return RedirectResponse("/login")
    return _serve("index.html")


@app.get("/settings")
async def settings_page(request: Request):
    if not get_current_user(request):
        return RedirectResponse("/login")
    return _serve("settings.html")


@app.get("/account")
async def account_page(request: Request):
    if not get_current_user(request):
        return RedirectResponse("/login")
    return _serve("account.html")


@app.get("/users")
async def users_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login")
    if not user.get("is_admin"):
        return RedirectResponse("/")
    return _serve("users.html")


# ---------- auth API ----------

class LoginIn(BaseModel):
    username: str
    password: str


@app.post("/api/login")
async def api_login(body: LoginIn, response: Response):
    users = load_users()
    u = users["users"].get(body.username)
    if not u or not verify_password(body.password, u["password_hash"], u["salt"]):
        raise HTTPException(401, "사용자명 또는 비밀번호가 올바르지 않습니다.")
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = {
        "username": body.username,
        "expires_at": datetime.now() + SESSION_TTL,
    }
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        max_age=int(SESSION_TTL.total_seconds()),
        path="/",
    )
    log.info("[/api/login] user=%s logged in", body.username)
    return {"ok": True, "username": body.username, "is_admin": u.get("is_admin", False)}


@app.post("/api/logout")
async def api_logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        SESSIONS.pop(token, None)
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@app.get("/api/me")
async def api_me(request: Request):
    user = require_user(request)
    return {
        "username": user["username"],
        "is_admin": user.get("is_admin", False),
        "default_group": user.get("default_group", "default"),
        "groups": list_groups(),
    }


class PasswordIn(BaseModel):
    current: str
    new: str
    new2: str


@app.post("/api/me/password")
async def api_change_password(body: PasswordIn, request: Request):
    user = require_user(request)
    if not body.new or body.new != body.new2:
        raise HTTPException(400, "새 비밀번호가 일치하지 않습니다.")
    if len(body.new) < 4:
        raise HTTPException(400, "새 비밀번호는 4자 이상이어야 합니다.")
    if not verify_password(body.current, user["password_hash"], user["salt"]):
        raise HTTPException(401, "현재 비밀번호가 올바르지 않습니다.")
    users = load_users()
    pw_hash, salt = hash_password(body.new)
    users["users"][user["username"]]["password_hash"] = pw_hash
    users["users"][user["username"]]["salt"] = salt
    save_users(users)
    log.info("[/api/me/password] user=%s changed password", user["username"])
    return {"ok": True}


class DefaultGroupIn(BaseModel):
    group: str


@app.post("/api/me/default-group")
async def api_set_default_group(body: DefaultGroupIn, request: Request):
    user = require_user(request)
    if body.group not in list_groups():
        raise HTTPException(400, f"존재하지 않는 그룹: {body.group}")
    users = load_users()
    users["users"][user["username"]]["default_group"] = body.group
    save_users(users)
    return {"ok": True, "default_group": body.group}


# ---------- settings groups API ----------

@app.get("/api/group-template")
async def api_group_template(request: Request):
    require_user(request)
    return load_group_template()


@app.get("/api/settings-groups")
async def api_list_groups(request: Request):
    require_user(request)
    return {"groups": list_groups()}


@app.get("/api/settings-groups/{name}")
async def api_get_group(name: str, request: Request):
    require_user(request)
    if name not in list_groups():
        raise HTTPException(404, f"그룹 없음: {name}")
    return load_group(name)


@app.post("/api/settings-groups/{name}")
async def api_save_group(name: str, data: dict, request: Request):
    require_user(request)
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(400, "유효하지 않은 그룹 이름")
    current = load_group(name)
    current.update(data)
    save_group(name, current)
    log.info("[/api/settings-groups/%s] saved keys=%s", name, sorted(data.keys()))
    return {"ok": True, "saved": current, "group": name}


@app.delete("/api/settings-groups/{name}")
async def api_delete_group(name: str, request: Request):
    require_admin(request)
    if name == "default":
        raise HTTPException(400, "'default' 그룹은 삭제할 수 없습니다.")
    if name not in list_groups():
        raise HTTPException(404, f"그룹 없음: {name}")
    delete_group(name)
    # users referencing this group fall back to default
    users = load_users()
    for u_info in users["users"].values():
        if u_info.get("default_group") == name:
            u_info["default_group"] = "default"
    save_users(users)
    return {"ok": True}


# Backward-compatible /api/settings — operates on the current user's default group.

@app.get("/api/settings")
async def api_get_my_settings(request: Request):
    user = require_user(request)
    group = user.get("default_group", "default")
    return load_group(group)


@app.post("/api/settings")
async def api_save_my_settings(data: dict, request: Request):
    user = require_user(request)
    group = user.get("default_group", "default")
    current = load_group(group)
    current.update(data)
    save_group(group, current)
    log.info("[/api/settings] user=%s group=%s saved keys=%s",
             user["username"], group, sorted(data.keys()))
    return {"ok": True, "saved": current, "group": group}


# ---------- admin: user management ----------

@app.get("/api/users")
async def api_list_users(request: Request):
    require_admin(request)
    users = load_users()
    return {
        "users": [
            {
                "username": name,
                "is_admin": info.get("is_admin", False),
                "default_group": info.get("default_group", "default"),
            }
            for name, info in users["users"].items()
        ]
    }


class CreateUserIn(BaseModel):
    username: str
    password: str
    is_admin: bool = False
    default_group: str = "default"


@app.post("/api/users")
async def api_create_user(body: CreateUserIn, request: Request):
    require_admin(request)
    username = body.username.strip()
    if not username or not body.password:
        raise HTTPException(400, "사용자명과 비밀번호가 필요합니다.")
    if len(body.password) < 4:
        raise HTTPException(400, "비밀번호는 4자 이상이어야 합니다.")
    users = load_users()
    if username in users["users"]:
        raise HTTPException(400, "이미 존재하는 사용자명입니다.")
    pw_hash, salt = hash_password(body.password)
    users["users"][username] = {
        "password_hash": pw_hash,
        "salt": salt,
        "is_admin": bool(body.is_admin),
        "default_group": body.default_group if body.default_group in list_groups() else "default",
    }
    save_users(users)
    log.info("[/api/users] created user=%s admin=%s", username, body.is_admin)
    return {"ok": True}


@app.delete("/api/users/{username}")
async def api_delete_user(username: str, request: Request):
    me = require_admin(request)
    if username == me["username"]:
        raise HTTPException(400, "자기 자신은 삭제할 수 없습니다.")
    users = load_users()
    if username not in users["users"]:
        raise HTTPException(404, "사용자가 없습니다.")
    users["users"].pop(username)
    save_users(users)
    return {"ok": True}


class ResetPasswordIn(BaseModel):
    new_password: str


@app.post("/api/users/{username}/reset-password")
async def api_reset_password(username: str, body: ResetPasswordIn, request: Request):
    require_admin(request)
    if len(body.new_password) < 4:
        raise HTTPException(400, "비밀번호는 4자 이상이어야 합니다.")
    users = load_users()
    if username not in users["users"]:
        raise HTTPException(404, "사용자가 없습니다.")
    pw_hash, salt = hash_password(body.new_password)
    users["users"][username]["password_hash"] = pw_hash
    users["users"][username]["salt"] = salt
    save_users(users)
    return {"ok": True}


# ---------- analyze + create ----------

def _strip_code_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        first_nl = t.find("\n")
        if first_nl != -1:
            t = t[first_nl + 1:]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


def _user_group_settings(request: Request) -> tuple[dict, dict]:
    user = require_user(request)
    group = user.get("default_group", "default")
    return user, load_group(group)


@app.post("/api/analyze")
async def analyze(
    request: Request,
    text: str = Form(""),
    images: List[UploadFile] = File(default=[]),
):
    if claude is None:
        raise HTTPException(500, "CLAUDE_API_KEY가 .env에 설정되어 있지 않습니다.")
    user, settings = _user_group_settings(request)

    fixed_labels = settings.get("fixed_labels", [])
    dynamic_label_pool = settings.get("dynamic_label_pool", [])
    priority_options = settings.get(
        "priority_options", ["Highest", "High", "Medium", "Low", "Lowest"]
    )

    system_prompt = f"""당신은 Jira 이슈 추출 도우미입니다. 사용자가 붙여넣은 대화/이미지를 읽고, 하나 이상의 Jira 이슈로 정리해 주세요.

반드시 아래 형식의 **JSON 배열만** 출력하세요 (마크다운 코드 펜스나 다른 텍스트 금지):
[
  {{
    "summary": "이슈 제목 (한글, 50자 이내, 날짜/접두어는 절대 포함하지 말 것 — 시스템이 자동으로 붙입니다)",
    "description": "일반 텍스트 본문. 마크업이나 마크다운 절대 금지. 아래 'description 작성 규칙' 참고.",
    "priority": "다음 중 하나: {', '.join(priority_options)}",
    "dynamic_labels": ["아래 풀에서 0~N개 선택: {', '.join(dynamic_label_pool) if dynamic_label_pool else '(풀 비어있음)'}"]
  }}
]

description 작성 규칙 (매우 중요):
- **Jira 위키 마크업, 마크다운, HTML 모두 금지**. h1/h2/h3, *bold*, **bold**, {{code}}, ``` 같은 기호 절대 쓰지 마세요. 사용하면 사용자 화면에 그 기호가 그대로 노출됩니다.
- 섹션 제목은 다음 형식으로: 대괄호로 감싸고 줄 끝에 콜론 없이 그대로 둡니다.
    [배경]
    [요청내용]
    [처리내용]
    [특이사항]
- 각 섹션 아래 항목은 가운뎃점("· ") 또는 하이픈("- ") 으로 시작하는 한 줄짜리 불릿으로 작성합니다.
- 섹션과 섹션 사이에는 빈 줄 1개를 넣으세요.
- 내용이 없는 섹션은 아예 출력하지 마세요.

기타 규칙:
- 대화에 서로 다른 작업 요청이 여러 건이면, 배열에 여러 객체로 분리하세요.
- 한 건이면 길이 1짜리 배열을 반환하세요.
- priority는 긴급도/영향도를 보고 결정합니다. (예: 장애·긴급=Highest, 일반 요청=Medium, 단순 문의/개선=Low)
- dynamic_labels는 주어진 풀에서만 고르고, 새로 만들지 마세요. 풀이 비어 있으면 빈 배열로 두세요.
- summary와 description은 한국어로 작성하세요.
- 이미지가 있으면 이미지 내용도 분석해 반영하세요.
"""

    content_blocks = []
    if text and text.strip():
        content_blocks.append({"type": "text", "text": text})

    for img in images:
        if not img.filename:
            continue
        img_bytes = await img.read()
        if not img_bytes:
            continue
        b64 = base64.b64encode(img_bytes).decode()
        media_type = img.content_type or "image/png"
        content_blocks.append({
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": b64},
        })

    if not content_blocks:
        raise HTTPException(400, "대화 텍스트나 이미지를 입력해 주세요.")

    try:
        msg = claude.messages.create(
            model=settings.get("claude_model", "claude-sonnet-4-6"),
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": content_blocks}],
        )
    except Exception as e:
        raise HTTPException(500, f"Claude API 호출 실패: {e}")

    raw = "".join(
        block.text for block in msg.content if getattr(block, "type", "") == "text"
    )
    cleaned = _strip_code_fence(raw)

    try:
        issues = json.loads(cleaned)
        if not isinstance(issues, list):
            issues = [issues]
    except json.JSONDecodeError:
        raise HTTPException(
            500,
            f"Claude 응답을 JSON으로 파싱하지 못했습니다.\n--- raw ---\n{raw}",
        )

    today = datetime.now()
    date_str = f"{today.month}/{today.day}"
    prefix = (settings.get("summary_prefix") or "").strip()

    for issue in issues:
        ai_summary = (issue.get("summary") or "").strip()
        parts = []
        if prefix:
            parts.append(prefix)
        parts.append(f"({date_str})")
        if ai_summary:
            parts.append(ai_summary)
        issue["summary"] = " ".join(parts)
        dyn = issue.get("dynamic_labels", []) or []
        if dynamic_label_pool:
            dyn = [l for l in dyn if l in dynamic_label_pool]
        issue["labels"] = list(dict.fromkeys(list(fixed_labels) + list(dyn)))
        issue.pop("dynamic_labels", None)
        if issue.get("priority") not in priority_options:
            issue["priority"] = "Medium"
        issue.setdefault("original_estimate", "1w")

    return {"issues": issues}


class IssueIn(BaseModel):
    summary: str
    description: str
    priority: str = "Medium"
    labels: List[str] = []
    original_estimate: str = "1w"


class CreateRequest(BaseModel):
    issues: List[IssueIn]


@app.post("/api/create")
async def create_issues(req: CreateRequest, request: Request):
    if not JIRA_TOKEN:
        raise HTTPException(500, "JIRA_ACCESS_TOKEN이 .env에 설정되어 있지 않습니다.")
    user, s = _user_group_settings(request)

    base_url = (s.get("jira_base_url") or "").rstrip("/")
    if not base_url:
        raise HTTPException(400, "설정에서 Jira Base URL을 먼저 입력해 주세요.")
    if not s.get("project_key"):
        raise HTTPException(400, "설정에서 프로젝트 키를 입력해 주세요.")
    if not s.get("issue_type"):
        raise HTTPException(400, "설정에서 이슈 유형을 입력해 주세요.")

    log.info("=" * 80)
    log.info(
        "[/api/create] user=%s group=%s issues=%d  base_url=%s  token=%s",
        user["username"], user.get("default_group", "default"),
        len(req.issues), base_url, _mask_token(JIRA_TOKEN),
    )

    headers = {
        "Authorization": f"Bearer {JIRA_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    headers_for_log = {**headers, "Authorization": f"Bearer {_mask_token(JIRA_TOKEN)}"}

    results = []
    async with httpx.AsyncClient(timeout=30) as client:
        for issue_idx, issue in enumerate(req.issues):
            fields: dict = {
                "project": {"key": s["project_key"]},
                "issuetype": {"name": s["issue_type"]},
                "summary": issue.summary,
                "description": issue.description,
                "labels": issue.labels,
                "priority": {"name": issue.priority},
            }
            fix_version = (s.get("fix_version") or "").strip()
            if not fix_version:
                now = datetime.now()
                fix_version = f"{now.year % 100:02d}.{now.month:02d}"
            fields["fixVersions"] = [{"name": fix_version}]

            if s.get("reporter"):
                fields["reporter"] = {"name": s["reporter"]}
            if s.get("assignee"):
                fields["assignee"] = {"name": s["assignee"]}

            cat_field = s.get("category_field_id")
            cat_parent = s.get("category_parent")
            cat_child = s.get("category_child")
            if cat_field and cat_parent:
                node: dict = {"value": cat_parent}
                if cat_child:
                    node["child"] = {"value": cat_child}
                fields[cat_field] = node

            company_field = (s.get("company_field_id") or "").strip() or "customfield_11102"
            company_parent_id = (s.get("company_parent_id") or "").strip() or "11327"
            company_child_id = (s.get("company_child_id") or "").strip() or "11332"
            company_node: dict = {"id": company_parent_id}
            if company_child_id:
                company_node["child"] = {"id": company_child_id}
            fields[company_field] = company_node

            original_estimate = (issue.original_estimate or "").strip()
            if original_estimate:
                fields["timetracking"] = {"originalEstimate": original_estimate}

            payload = {"fields": fields}
            url = f"{base_url}/rest/api/2/issue"

            log.info("-" * 80)
            log.info("[issue %d/%d] POST %s", issue_idx + 1, len(req.issues), url)
            log.info("[issue %d] summary=%r", issue_idx + 1, issue.summary)
            log.debug("[issue %d] request headers:\n%s", issue_idx + 1,
                      _pretty_json(headers_for_log))
            log.debug("[issue %d] request body:\n%s", issue_idx + 1, _pretty_json(payload))

            attempts_log: List[dict] = []
            t0 = time.monotonic()
            r = None
            last_error: Optional[str] = None
            try:
                r = await client.post(url, json=payload, headers=headers)
            except httpx.RequestError as e:
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                last_error = f"네트워크 오류: {e}"
                log.warning("[issue %d] %s (%dms)", issue_idx + 1, last_error, elapsed_ms)
                attempts_log.append({"attempt": 1, "elapsed_ms": elapsed_ms, "network_error": str(e)})

            if r is None:
                results.append({
                    "ok": False, "error": last_error or "요청 실패",
                    "attempts": attempts_log, "payload": payload,
                })
                continue

            elapsed_ms = int((time.monotonic() - t0) * 1000)
            resp_headers = dict(r.headers)
            body_text = r.text
            rl_headers = {
                k: v for k, v in resp_headers.items()
                if k.lower() in (
                    "retry-after", "x-ratelimit-remaining", "x-ratelimit-limit",
                    "x-ratelimit-reset", "x-arequestid", "atl-traceid", "x-aaccountid",
                )
            }
            log_lvl = log.info if 200 <= r.status_code < 300 else log.warning
            log_lvl("[issue %d] <- HTTP %d (%dms)  rate-limit headers: %s",
                    issue_idx + 1, r.status_code, elapsed_ms,
                    _pretty_json(rl_headers) if rl_headers else "(none)")
            log.debug("[issue %d] response headers:\n%s", issue_idx + 1, _pretty_json(resp_headers))
            log.debug("[issue %d] response body:\n%s", issue_idx + 1, body_text)

            attempts_log.append({
                "attempt": 1, "elapsed_ms": elapsed_ms,
                "status": r.status_code, "rate_limit_headers": rl_headers,
                "body_excerpt": body_text[:500],
            })

            if 200 <= r.status_code < 300:
                data = r.json()
                key = data.get("key")
                log.info("[issue %d] ✓ created key=%s", issue_idx + 1, key)
                results.append({
                    "ok": True, "key": key,
                    "url": f"{base_url}/browse/{key}", "attempts": attempts_log,
                })
            else:
                log.error("[issue %d] ✗ failed status=%d body=%s",
                          issue_idx + 1, r.status_code, r.text[:500])
                blocked = (
                    r.status_code == 429
                    and r.headers.get("X-RateLimit-Limit", "").strip() == "0"
                )
                results.append({
                    "ok": False, "status": r.status_code, "error": r.text,
                    "blocked": blocked, "response_headers": resp_headers,
                    "attempts": attempts_log, "payload": payload,
                })

    return {"results": results}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8765, reload=True)
