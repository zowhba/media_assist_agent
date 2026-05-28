# Jira Issue Agent

대화 내용(텍스트/이미지)을 붙여넣으면 Claude가 작업 단위로 나눠 Jira 이슈로 등록해 주는 웹 앱입니다.

## Features
- 텍스트 + 이미지 붙여넣기 → 자동으로 N개의 업무로 분해
- 업무별 preview 카드에서 검토/수정 후 카드마다 개별 Jira 등록
- 다중 사용자 + 설정 그룹 (사용자마다 기본 그룹 선택)
- 관리자 계정으로 다른 사용자 생성 / 비밀번호 초기화
- 자기 비밀번호 변경 (현재 + 새 비밀번호)

## Setup

```bash
# 1) Python 3.13 가상환경 (3.14는 일부 의존성 휠이 아직 없음)
/opt/homebrew/bin/python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2) .env 작성 (.env.example 참고)
cp .env.example .env
# .env 에서 JIRA_ACCESS_TOKEN, CLAUDE_API_KEY 채우기

# 3) 실행
./.venv/bin/python app.py
# http://127.0.0.1:8765
```

## First Login
첫 기동 시 `admin / admin` 계정이 자동 생성됩니다. 로그인 후 즉시 비밀번호를 변경하세요.

## Persistent Data
- `users.json` — 사용자/해시된 비밀번호
- `groups/<이름>.json` — 설정 그룹

두 파일 모두 `.gitignore`로 제외됩니다. 운영 시 정기 백업하세요.
