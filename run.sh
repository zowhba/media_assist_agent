#!/usr/bin/env bash
# Jira Issue Agent — 한 번에 실행 스크립트
#
# 동작:
#   1) 호환 Python(3.11~3.13) 자동 탐색
#   2) .venv 없으면 생성, 있으면 버전 검증 후 재사용
#   3) requirements.txt가 바뀌었거나 처음 실행이면 의존성 설치
#   4) .env 없으면 .env.example에서 복사하고 토큰 입력을 안내
#   5) uvicorn으로 서버 기동 (Ctrl+C로 중지)
#
# 사용:
#   ./run.sh                # 기본 포트 8765
#   PORT=9000 ./run.sh      # 다른 포트
#   ./run.sh --reload       # 개발 모드(코드 변경 자동 반영)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR=".venv"
PORT="${PORT:-8765}"
RELOAD_FLAG=""
if [ "${1:-}" = "--reload" ]; then
  RELOAD_FLAG="--reload"
fi

C_OK="\033[32m"; C_WARN="\033[33m"; C_ERR="\033[31m"; C_INFO="\033[36m"; C_END="\033[0m"

# ---------- 1) Python 찾기 (3.9 ~ 3.13 지원, 3.14는 pydantic 휠 미지원) ----------
MIN_MAJOR=3; MIN_MINOR=9
MAX_MAJOR=3; MAX_MINOR=13

check_py() {
  "$1" -c "
import sys
v = sys.version_info[:2]
lo = (${MIN_MAJOR}, ${MIN_MINOR}); hi = (${MAX_MAJOR}, ${MAX_MINOR})
sys.exit(0 if lo <= v <= hi else 1)
" 2>/dev/null
}

PYTHON_BIN=""
CANDIDATES=""
# 1) 명시적 버전부터 우선 검색
for ver in 3.13 3.12 3.11 3.10 3.9; do
  for prefix in /opt/homebrew/bin /usr/local/bin /usr/bin /usr/local/python/bin; do
    CANDIDATES="$CANDIDATES $prefix/python$ver"
  done
  CANDIDATES="$CANDIDATES python$ver"
done
# 2) 마지막으로 일반명
CANDIDATES="$CANDIDATES python3 python"

# 발견된 모든 후보 출력 (디버깅에 유용)
FOUND_ANY=""
for c in $CANDIDATES; do
  if command -v "$c" >/dev/null 2>&1; then
    real=$(command -v "$c")
    ver=$("$c" --version 2>&1 || echo "unknown")
    FOUND_ANY="$FOUND_ANY\n  $real  →  $ver"
    if [ -z "$PYTHON_BIN" ] && check_py "$c"; then
      PYTHON_BIN="$c"
    fi
  fi
done

if [ -z "$PYTHON_BIN" ]; then
  echo -e "${C_ERR}❌ Python 3.9 ~ 3.13이 필요합니다.${C_END}"
  if [ -n "$FOUND_ANY" ]; then
    echo -e "${C_INFO}시스템에서 발견된 Python:${C_END}$FOUND_ANY"
  else
    echo "   시스템에서 Python을 찾지 못했습니다."
  fi
  echo
  echo "설치 방법:"
  echo "  • Amazon Linux 2023:  sudo dnf install -y python3.11 python3.11-pip"
  echo "  • Amazon Linux 2:     sudo amazon-linux-extras install python3.11"
  echo "  • Ubuntu/Debian:      sudo apt install -y python3.11 python3.11-venv"
  echo "  • macOS:              brew install python@3.13"
  echo "  • RHEL/CentOS:        sudo dnf install -y python3.11"
  exit 1
fi
echo -e "${C_OK}✓${C_END} Python: $("$PYTHON_BIN" --version) ($(command -v "$PYTHON_BIN"))"

# ---------- 2) venv 점검/생성 ----------
if [ -d "$VENV_DIR" ]; then
  if ! "$VENV_DIR/bin/python" -c 'import sys; sys.exit(0 if (3,11) <= sys.version_info[:2] <= (3,13) else 1)' 2>/dev/null; then
    echo -e "${C_WARN}⚠️  기존 .venv가 호환되지 않는 Python으로 만들어져 재생성합니다.${C_END}"
    rm -rf "$VENV_DIR"
  fi
fi

if [ ! -d "$VENV_DIR" ]; then
  # 일부 Linux 배포는 venv가 분리 패키지
  if ! "$PYTHON_BIN" -c "import venv" 2>/dev/null; then
    PYVER=$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    echo -e "${C_ERR}❌ Python의 venv 모듈이 없습니다.${C_END}"
    echo "   • Ubuntu/Debian:   sudo apt install -y python${PYVER}-venv"
    echo "   • Amazon Linux:    sudo dnf install -y python${PYVER//./}-libs"
    echo "   • RHEL/CentOS:     sudo dnf install -y python${PYVER//./}-libs"
    exit 1
  fi
  echo -e "${C_INFO}📦 가상환경 생성: $VENV_DIR${C_END}"
  if ! "$PYTHON_BIN" -m venv "$VENV_DIR" 2>/tmp/venv_err; then
    echo -e "${C_ERR}❌ 가상환경 생성 실패:${C_END}"
    cat /tmp/venv_err
    echo
    echo "   ensurepip 누락 시:"
    echo "   • Ubuntu/Debian:   sudo apt install -y python3-venv python3-pip"
    exit 1
  fi
fi

VENV_PY="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"

# ---------- 3) 의존성 설치 (requirements.txt 변경 시에만) ----------
REQ_HASH_FILE="$VENV_DIR/.req-hash"
CURRENT_HASH=$(shasum requirements.txt | awk '{print $1}')
STORED_HASH=$(cat "$REQ_HASH_FILE" 2>/dev/null || true)

if [ "$CURRENT_HASH" != "$STORED_HASH" ]; then
  echo -e "${C_INFO}📦 의존성 설치/업데이트 중...${C_END}"
  "$VENV_PIP" install --quiet --upgrade pip
  "$VENV_PIP" install --quiet -r requirements.txt
  echo "$CURRENT_HASH" > "$REQ_HASH_FILE"
  echo -e "${C_OK}✓${C_END} 의존성 설치 완료"
else
  echo -e "${C_OK}✓${C_END} 의존성 최신 (재설치 스킵)"
fi

# ---------- 4) .env 확인 ----------
if [ ! -f ".env" ]; then
  if [ -f ".env.example" ]; then
    cp .env.example .env
    echo -e "${C_WARN}⚠️  .env 파일이 없어 .env.example을 복사했습니다.${C_END}"
    echo "   .env 파일을 열어 다음 값을 채운 뒤 다시 실행하세요:"
    echo "     - JIRA_ACCESS_TOKEN"
    echo "     - CLAUDE_API_KEY"
    exit 1
  else
    echo -e "${C_ERR}❌ .env 파일이 없고 .env.example도 없습니다.${C_END}"
    exit 1
  fi
fi

# placeholder 그대로면 경고
if grep -qE '(your-jira-pat-here|sk-ant-api03-\.\.\.)' .env; then
  echo -e "${C_WARN}⚠️  .env의 토큰이 예시값 그대로입니다. 실제 값으로 바꾼 뒤 다시 실행하세요.${C_END}"
  exit 1
fi

# ---------- 5) 서버 기동 ----------
echo
echo -e "${C_OK}🚀 서버 시작:${C_END} http://127.0.0.1:$PORT"
echo "   첫 로그인: admin / admin (로그인 직후 비밀번호 변경 권장)"
echo "   중지: Ctrl+C"
if [ -n "$RELOAD_FLAG" ]; then
  echo -e "${C_INFO}   (개발 모드: 코드 변경 시 자동 재시작)${C_END}"
fi
echo

exec "$VENV_PY" -m uvicorn app:app --host 127.0.0.1 --port "$PORT" $RELOAD_FLAG
