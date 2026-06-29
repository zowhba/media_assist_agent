"""
월간 운영보고 이슈 정리 — Jira export 파싱 / 변환 / 통계 / .xls 생성

입력: Jira에서 export 한 파일
  - .xls  → 실제로는 HTML 테이블 (Jira 기본 export)
  - .csv  → 표준 CSV

출력:
  - 가공 행 목록(미리보기/다운로드용): 이슈, 비고, 상태, M/D, 담당자
  - 운영보고 PPT용 통계(시스템 x 업무유형, 완료/진행)
  - 원본과 동일한 HTML형 .xls 문자열
"""

from __future__ import annotations

import csv
import io
import re
import html as html_mod
from typing import List, Dict, Any, Optional

# 레이블에서 '업무 유형'으로 취급할 값 (이 외의 레이블은 서비스/시스템명으로 간주)
WORK_TYPES = ["운영지원", "운영개발", "상용작업"]
WORK_TYPE_DISPLAY = {
    "운영지원": "운영 지원",
    "운영개발": "운영 개발",
    "상용작업": "상용 작업",
}

# 통계에서 '완료'로 집계할 상태값 (대소문자 무시)
COMPLETED_STATES = {
    "종료", "완료", "해결됨", "닫힘", "닫음",
    "done", "closed", "resolved", "complete", "completed",
}

# 하루 근무시간(초) — M/D = 작업한시간(초) / 60 / 60 / 8
SECONDS_PER_MD = 60 * 60 * 8
# M/M(맨먼스) 환산 기본 일수 (1 M/M = 20 M/D)
DEFAULT_MD_PER_MM = 20


# ----------------------------------------------------------------------------
# 파싱
# ----------------------------------------------------------------------------

def _clean_text(s: str) -> str:
    if s is None:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)          # 태그 제거
    s = html_mod.unescape(s)                # HTML 엔티티 복원
    s = s.replace("\xa0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _looks_like_html(raw: str) -> bool:
    head = raw[:1000].lower()
    return "<html" in head or "<table" in head or "issuerow" in raw[:5000].lower()


def parse_jira_export(raw_bytes: bytes, filename: str = "") -> List[Dict[str, Any]]:
    """Jira export(HTML형 .xls 또는 .csv)를 표준 이슈 dict 목록으로 변환."""
    text = _decode(raw_bytes)
    name = (filename or "").lower()
    if name.endswith(".csv") and not _looks_like_html(text):
        return _parse_csv(text)
    if _looks_like_html(text):
        return _parse_html(text)
    # 확장자 불명 + HTML 아님 → CSV 시도
    return _parse_csv(text)


def _decode(raw_bytes: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr", "latin-1"):
        try:
            return raw_bytes.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw_bytes.decode("utf-8", errors="replace")


def _parse_html(html: str) -> List[Dict[str, Any]]:
    """Jira HTML export 파싱. td의 class 속성으로 컬럼을 식별(컬럼 순서 무관)."""
    rows: List[Dict[str, Any]] = []
    # 데이터 행: <tr ... class="issuerow"> ... </tr>
    row_iter = re.finditer(
        r'<tr[^>]*\bclass="[^"]*issuerow[^"]*"[^>]*>(.*?)</tr>',
        html, re.S | re.I,
    )
    for rm in row_iter:
        row_html = rm.group(1)
        cells: Dict[str, str] = {}
        for cm in re.finditer(
            r'<td[^>]*\bclass="([^"]+)"[^>]*>(.*?)</td>', row_html, re.S | re.I
        ):
            # class 의 첫 토큰을 키로 사용 (예: "summary", "issuekey")
            cls = cm.group(1).split()[0].strip()
            cells.setdefault(cls, cm.group(2))

        key = _clean_text(cells.get("issuekey", ""))
        summary = _clean_text(cells.get("summary", ""))
        if not key and not summary:
            continue
        rows.append({
            "key": key,
            "summary": summary,
            "status": _extract_status(cells.get("status", "")),
            "assignee": _clean_text(cells.get("assignee", "")),
            "timespent": _to_seconds(_clean_text(cells.get("timespent", ""))),
            "labels": _split_labels(_clean_text(cells.get("labels", ""))),
        })
    return rows


def _extract_status(cell_html: str) -> str:
    """상태 셀에서 표시 텍스트만 추출 (lozenge span 내부 텍스트)."""
    txt = _clean_text(cell_html)
    return txt


def _split_labels(value: str) -> List[str]:
    if not value:
        return []
    parts = re.split(r"[,、;/|]+|\s{2,}", value)
    return [p.strip() for p in parts if p.strip()]


def _to_seconds(value: Any) -> int:
    if value is None or value == "":
        return 0
    s = str(value).strip().replace(",", "")
    try:
        return int(float(s))
    except ValueError:
        return 0


# CSV 헤더 별칭
_CSV_ALIASES = {
    "key": ["키", "issue key", "issuekey", "key"],
    "summary": ["요약", "summary"],
    "status": ["상태", "status"],
    "assignee": ["담당자", "assignee"],
    "timespent": ["작업한 시간", "작업한시간", "time spent", "σ time spent",
                  "time spent (s)", "시간 사용"],
    "labels": ["레이블", "라벨", "labels", "label"],
}


def _parse_csv(text: str) -> List[Dict[str, Any]]:
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return []
    norm = [h.strip().lower() for h in header]

    def find_idx(aliases: List[str], multi: bool = False) -> List[int]:
        idxs = []
        for i, h in enumerate(norm):
            if any(h == a for a in aliases):
                idxs.append(i)
        return idxs

    idx = {k: find_idx(v) for k, v in _CSV_ALIASES.items()}

    def first(row, k):
        for i in idx.get(k, []):
            if i < len(row) and str(row[i]).strip():
                return str(row[i]).strip()
        return ""

    rows: List[Dict[str, Any]] = []
    for row in reader:
        if not any(str(c).strip() for c in row):
            continue
        key = first(row, "key")
        summary = first(row, "summary")
        if not key and not summary:
            continue
        # 레이블은 CSV에서 여러 컬럼으로 나뉘어 올 수 있음
        labels: List[str] = []
        for i in idx.get("labels", []):
            if i < len(row):
                labels.extend(_split_labels(str(row[i]).strip()))
        rows.append({
            "key": key,
            "summary": summary,
            "status": first(row, "status"),
            "assignee": first(row, "assignee"),
            "timespent": _to_seconds(first(row, "timespent")),
            "labels": [l for l in labels if l],
        })
    return rows


# ----------------------------------------------------------------------------
# 변환 / 분류
# ----------------------------------------------------------------------------

def classify_labels(labels: List[str]) -> tuple[str, str]:
    """레이블 목록에서 (서비스/시스템명, 업무유형) 추출."""
    work_type = ""
    service = ""
    for lb in labels:
        norm = lb.replace(" ", "")
        if norm in WORK_TYPES and not work_type:
            work_type = norm
        elif not service and norm not in WORK_TYPES:
            service = lb.strip()
    return service, work_type


def md_value(seconds: int) -> float:
    if not seconds:
        return 0.0
    return round(seconds / SECONDS_PER_MD, 2)


def fmt_md(md: float) -> str:
    if md == int(md):
        return str(int(md))
    return f"{md:g}"


def is_completed(status: str) -> bool:
    return (status or "").strip().lower() in COMPLETED_STATES


def build_rows(
    issues: List[Dict[str, Any]],
    all_closed: bool = False,
    default_assignee: str = "",
) -> List[Dict[str, Any]]:
    """다운로드/미리보기용 가공 행 생성."""
    out = []
    for it in issues:
        service, work_type = classify_labels(it.get("labels", []))
        key = it.get("key", "").strip()
        summary = it.get("summary", "").strip()
        issue_text = (key + " " + summary).strip() if key else summary

        status = "종료" if all_closed else (it.get("status", "") or "")
        assignee = default_assignee.strip() if default_assignee.strip() else (it.get("assignee", "") or "")
        md = md_value(it.get("timespent", 0))

        out.append({
            "issue": issue_text,
            "note": WORK_TYPE_DISPLAY.get(work_type, work_type),
            "status": status,
            "md": md,
            "md_text": fmt_md(md),
            "assignee": assignee,
            # 통계용 메타
            "_service": service or "(미지정)",
            "_work_type": work_type or "",
            "_completed": True if all_closed else is_completed(it.get("status", "")),
        })
    return out


# ----------------------------------------------------------------------------
# 통계 (운영보고 PPT용)
# ----------------------------------------------------------------------------

def build_stats(rows: List[Dict[str, Any]], md_per_mm: int = DEFAULT_MD_PER_MM) -> Dict[str, Any]:
    """시스템 x 업무유형 건수(완료/진행) 및 합계."""
    systems: Dict[str, Dict[str, Dict[str, int]]] = {}
    total_md = 0.0
    total_count = 0

    def blank():
        return {wt: {"done": 0, "prog": 0} for wt in WORK_TYPES}

    for r in rows:
        svc = r["_service"]
        wt = r["_work_type"] or "운영지원"  # 업무유형 미지정 시 운영지원으로 귀속
        if wt not in WORK_TYPES:
            wt = "운영지원"
        systems.setdefault(svc, blank())
        if r["_completed"]:
            systems[svc][wt]["done"] += 1
        else:
            systems[svc][wt]["prog"] += 1
        total_md += r["md"]
        total_count += 1

    # 시스템별/유형별 합계 구조화
    table = []
    col_totals = {wt: {"done": 0, "prog": 0} for wt in WORK_TYPES}
    grand = {"done": 0, "prog": 0}
    for svc, wtmap in systems.items():
        row = {"system": svc, "work": {}, "total": {"done": 0, "prog": 0}}
        for wt in WORK_TYPES:
            d = wtmap[wt]["done"]
            p = wtmap[wt]["prog"]
            row["work"][wt] = {"done": d, "prog": p, "count": d + p}
            row["total"]["done"] += d
            row["total"]["prog"] += p
            col_totals[wt]["done"] += d
            col_totals[wt]["prog"] += p
        row["total"]["count"] = row["total"]["done"] + row["total"]["prog"]
        grand["done"] += row["total"]["done"]
        grand["prog"] += row["total"]["prog"]
        table.append(row)

    # 건수 많은 순 정렬
    table.sort(key=lambda r: r["total"]["count"], reverse=True)

    grand["count"] = grand["done"] + grand["prog"]
    mm = round(total_md / md_per_mm, 2) if md_per_mm else 0.0

    return {
        "table": table,
        "col_totals": col_totals,
        "grand": grand,
        "total_md": round(total_md, 2),
        "mm": mm,
        "systems": [r["system"] for r in table],
    }


# ----------------------------------------------------------------------------
# 출력물 생성
# ----------------------------------------------------------------------------

def _esc(s: Any) -> str:
    return html_mod.escape(str(s if s is not None else ""))


def render_xls(rows: List[Dict[str, Any]], title: str = "월간 운영보고") -> str:
    """원본과 동일한 HTML형 .xls (Excel에서 바로 열림) 문자열 생성."""
    head = """<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:x="urn:schemas-microsoft-com:office:excel" xmlns="http://www.w3.org/TR/REC-html40">
<head><meta http-equiv="Content-Type" content="application/vnd.ms-excel; charset=UTF-8"/>
<style>
table { border-collapse: collapse; font-family: 'Malgun Gothic', Arial, sans-serif; font-size: 12px; }
th, td { border: 1px solid #4472c4; padding: 4px 8px; vertical-align: middle; }
th { background: #4472c4; color: #fff; font-weight: bold; text-align: center; }
td.center { text-align: center; mso-number-format:"\\@"; }
td.num { text-align: center; }
</style></head><body>
<table border="1">
<tr>
  <th>이슈</th><th>비고</th><th>상태</th><th>M/D</th><th>담당자</th>
</tr>
"""
    body = []
    total_md = 0.0
    for r in rows:
        total_md += r["md"]
        body.append(
            "<tr>"
            f'<td>{_esc(r["issue"])}</td>'
            f'<td class="center">{_esc(r["note"])}</td>'
            f'<td class="center">{_esc(r["status"])}</td>'
            f'<td class="num">{_esc(r["md_text"])}</td>'
            f'<td class="center">{_esc(r["assignee"])}</td>'
            "</tr>"
        )
    # 합계 행
    body.append(
        '<tr><td class="center" colspan="3"><b>합계</b></td>'
        f'<td class="num"><b>{_esc(fmt_md(round(total_md, 2)))}</b></td><td></td></tr>'
    )
    return head + "\n".join(body) + "\n</table></body></html>"


def render_stats_html(stats: Dict[str, Any]) -> str:
    """화면 표시용 통계표(첨부 이미지 형태)."""
    ths = "".join(f"<th>{WORK_TYPE_DISPLAY[wt]}</th>" for wt in WORK_TYPES)
    out = [f'<table class="stat-table"><tr><th>구 분</th>{ths}<th>합계</th></tr>']

    def cell(d, p):
        return f'{d + p}건<br><span class="sub">(완료 {d}건 / 진행 {p}건)</span>'

    for row in stats["table"]:
        tds = ""
        for wt in WORK_TYPES:
            w = row["work"][wt]
            tds += f'<td>{cell(w["done"], w["prog"])}</td>'
        tot = row["total"]
        out.append(
            f'<tr><th class="rowhead">{_esc(row["system"])}</th>{tds}'
            f'<td class="tot">{cell(tot["done"], tot["prog"])}</td></tr>'
        )
    # 합계 행
    ct = stats["col_totals"]
    tds = "".join(f'<td class="tot">{cell(ct[wt]["done"], ct[wt]["prog"])}</td>' for wt in WORK_TYPES)
    g = stats["grand"]
    out.append(
        f'<tr class="grand"><th class="rowhead">합계</th>{tds}'
        f'<td class="tot">{g["count"]}건<br><span class="sub">{stats["mm"]} (M/M)</span></td></tr>'
    )
    out.append("</table>")
    return "".join(out)
