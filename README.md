# MAP — Media Automation Portal

미디어 업무에 필요한 반복 작업을 자동화하는 도구 포털입니다.
로그인 후 포털 홈(`/`)에서 도구를 선택해 사용합니다.

## Tools
- **🪄 Jira 이슈 자동 등록** (`/tools/jira`) — 대화/메모(텍스트·이미지)를 붙여넣으면 Claude가 업무 단위로 나눠 Jira 이슈로 등록
- 🗒️ 회의록 요약 *(준비 중)*
- 📊 주간 업무 보고 *(준비 중)*

> 새 도구는 `static/portal.js`의 `TOOLS` 배열에 항목 하나만 추가하면 포털에 노출됩니다.

## Common Features
- 다중 사용자 + 세션 로그인 (계정 체계는 전 도구 공통)
- 설정 그룹 (사용자마다 기본 그룹 선택, 새 그룹은 템플릿 값으로 자동 채움)
- 관리자 계정으로 다른 사용자 생성 / 비밀번호 초기화
- 자기 비밀번호 변경 (현재 + 새 비밀번호)

## Quick Start (한 줄 실행)

```bash
./run.sh
```

`run.sh`이 알아서 처리합니다:
- 호환 Python(3.9~3.13) 자동 탐색
- `.venv` 가상환경 생성 & 의존성 설치 (이미 최신이면 스킵)
- `.env` 없으면 `.env.example`을 복사하고 토큰 입력을 안내
- uvicorn으로 서버 기동 → **포트 443**, 호스트 `0.0.0.0`

옵션:
```bash
PORT=8765 ./run.sh                   # 다른 포트 (1024 이상은 권한 불필요)
HOST=127.0.0.1 PORT=8765 ./run.sh    # 로컬에서만 접근
./run.sh --reload                    # 개발 모드 (코드 변경 자동 반영)
```

### 포트 443 관련 안내
- **권한**: Linux에서 1024 미만 포트는 root 권한이 필요합니다. 스크립트가 `setcap`을 자동 적용 (sudo 1회 필요)
- **HTTPS 아님**: 현재 코드는 평문 HTTP. 브라우저에서 `http://`로 접근해야 합니다 (`https://` X)
- **권장 구성**: 외부 노출 시 nginx 등으로 TLS 종단 후 8765 같은 내부 포트로 프록시

## 수동 Setup (필요한 경우만)

```bash
/opt/homebrew/bin/python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # 토큰 채우기
./.venv/bin/python app.py
```

## First Login
첫 기동 시 `admin / admin` 계정이 자동 생성됩니다. 로그인 후 즉시 비밀번호를 변경하세요.

## Persistent Data (PostgreSQL)
모든 영속 데이터는 `.env`의 `APP_DB_URL`이 가리키는 PostgreSQL에 저장됩니다.
- `users` 테이블 — 사용자/해시된 비밀번호/권한/기본 그룹
- `settings_groups` 테이블 — 설정 그룹(JSONB)
- `app_config` 테이블 — 새 그룹 템플릿 등

첫 기동 시, 기존 로컬 파일(`users.json`, `groups/*.json`, `group_template.json`)이
DB에 비어 있을 경우 **자동으로 1회 이관**됩니다. 이후 DB가 단일 진실 공급원입니다.

> 세션(로그인 상태)은 메모리에 보관되어 재시작 시 재로그인이 필요합니다(단일 프로세스 기준).
> 데이터 자체는 DB에 있으므로 재시작/재배포에도 보존됩니다.
