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
PORT="${PORT:-443}"
HOST="${HOST:-0.0.0.0}"
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

VENV_FRESH=""
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
  VENV_FRESH=1
fi

VENV_PY="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"

# ---------- 3) 의존성 설치 ----------
# 해시 도구 자동 선택 (sha256sum=Linux, shasum=macOS)
file_hash() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    # 폴백: 파일 수정시각 기반 (해시 도구가 없으면 거의 항상 재설치)
    "$VENV_PY" -c "import hashlib,sys; print(hashlib.sha256(open('$1','rb').read()).hexdigest())"
  fi
}

REQ_HASH_FILE="$VENV_DIR/.req-hash"
CURRENT_HASH=$(file_hash requirements.txt)
STORED_HASH=$(cat "$REQ_HASH_FILE" 2>/dev/null || true)

# 핵심 패키지가 실제로 import 가능한지 sanity 체크
need_install=""
if [ -n "$VENV_FRESH" ]; then need_install=1; fi
if [ -z "$CURRENT_HASH" ] || [ "$CURRENT_HASH" != "$STORED_HASH" ]; then need_install=1; fi
if ! "$VENV_PY" -c "import uvicorn, fastapi, anthropic, httpx, pydantic, dotenv" 2>/dev/null; then
  need_install=1
fi

if [ -n "$need_install" ]; then
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

# ---------- 5) 1024 미만 포트 권한 처리 ----------
need_priv=""
if [ "$PORT" -lt 1024 ] 2>/dev/null && [ "$(id -u)" != "0" ]; then
  need_priv=1
fi

if [ -n "$need_priv" ]; then
  OS=$(uname -s)
  if [ "$OS" = "Linux" ] && command -v setcap >/dev/null 2>&1; then
    REAL_PY=$(readlink -f "$VENV_PY" 2>/dev/null || "$VENV_PY" -c 'import os,sys; print(os.path.realpath(sys.executable))')
    HAS_CAP=$(getcap "$REAL_PY" 2>/dev/null | grep -c cap_net_bind_service || true)
    if [ "$HAS_CAP" -eq 0 ]; then
      echo -e "${C_INFO}🔐 포트 $PORT 바인딩 권한 부여 (1회, sudo 필요):${C_END}"
      echo "   sudo setcap 'cap_net_bind_service=+ep' $REAL_PY"
      if ! sudo setcap 'cap_net_bind_service=+ep' "$REAL_PY"; then
        echo -e "${C_ERR}❌ setcap 실패. 다음 중 하나로 실행하세요:${C_END}"
        echo "   sudo PORT=$PORT ./run.sh"
        echo "   또는 다른 포트:  PORT=8765 ./run.sh"
        exit 1
      fi
      echo -e "${C_OK}✓${C_END} 권한 부여 완료"
    fi
  else
    echo -e "${C_ERR}❌ 포트 $PORT은(는) 1024 미만이라 root 권한이 필요합니다.${C_END}"
    echo "   sudo PORT=$PORT ./run.sh   (또는)   PORT=8765 ./run.sh"
    exit 1
  fi
fi

# ---------- 6) 서버 기동 ----------
if [ "$PORT" = "443" ]; then
  echo -e "${C_WARN}⚠️  포트 443은 일반적으로 HTTPS용입니다. 이 서버는 평문 HTTP로 동작합니다.${C_END}"
  echo "   브라우저에서 반드시 ${C_INFO}http://${C_END}로 접근하세요 (https:// 아님)."
  echo "   외부 노출 시 nginx 등 리버스 프록시로 TLS를 종단하는 것을 권장합니다."
  echo
fi

DISPLAY_HOST="$HOST"
if [ "$HOST" = "0.0.0.0" ]; then DISPLAY_HOST="<this-server-IP>"; fi
echo -e "${C_OK}🚀 서버 시작:${C_END} http://${DISPLAY_HOST}:$PORT  (binding ${HOST}:${PORT})"
echo "   첫 로그인: admin / admin (로그인 직후 비밀번호 변경 권장)"
echo "   중지: Ctrl+C"
if [ -n "$RELOAD_FLAG" ]; then
  echo -e "${C_INFO}   (개발 모드: 코드 변경 시 자동 재시작)${C_END}"
fi
echo

exec "$VENV_PY" -m uvicorn app:app --host "$HOST" --port "$PORT" $RELOAD_FLAG
