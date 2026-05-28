# Jira Issue Agent

대화 내용(텍스트/이미지)을 붙여넣으면 Claude가 작업 단위로 나눠 Jira 이슈로 등록해 주는 웹 앱입니다.

## Features
- 텍스트 + 이미지 붙여넣기 → 자동으로 N개의 업무로 분해
- 업무별 preview 카드에서 검토/수정 후 카드마다 개별 Jira 등록
- 다중 사용자 + 설정 그룹 (사용자마다 기본 그룹 선택)
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

## Persistent Data
- `users.json` — 사용자/해시된 비밀번호
- `groups/<이름>.json` — 설정 그룹

두 파일 모두 `.gitignore`로 제외됩니다. 운영 시 정기 백업하세요.
