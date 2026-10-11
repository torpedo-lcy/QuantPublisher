"""사업보고서 본문 XML에서 '사업의 개요'와 '연혁'을 뽑는다 (Task 019).

네트워크와 DB에 접근하지 않는 순수 함수만 둔다. 사업보고서 형식은 회사마다
달라서 파서는 보수적으로 동작한다. 읽지 못하면 빈 값(None 또는 빈 목록)을
돌려주고, 추측해서 채우지 않는다. 호출자는 빈 값이면 해당 섹션을 생략한다.

본문 XML 구조 (DART dart4.xsd):
    <SECTION-1><TITLE>II. 사업의 내용</TITLE>
      <SECTION-2><TITLE>1. 사업의 개요</TITLE> <P>...</P> ...
    <SECTION-1><TITLE>I. 회사의 개요</TITLE>
      <SECTION-2><TITLE>2. 회사의 연혁</TITLE> ... <TABLE>...
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

# 사업 요약 길이 상한(글자). 문장 끝에서 자르므로 실제는 이보다 짧을 수 있다.
SUMMARY_MAX_CHARS = 700
# 연혁 한 항목의 글자 상한과 보관할 최대 항목 수.
HISTORY_EVENT_MAX_CHARS = 120
HISTORY_MAX_ITEMS = 40
# 한 해에 보관할 최대 사건 수 (원문 순서대로 앞에서부터).
HISTORY_MAX_PER_YEAR = 5

_SECTION2_TEMPLATE = r"<SECTION-2[^>]*>\s*<TITLE[^>]*>\s*{title}\s*</TITLE>"
_NEXT_SECTION = re.compile(r"<SECTION-[123][ >]")
_YEAR_ONLY = re.compile(r"^((?:19|20)\d{2})(?:\s*년)?\.?$")
# "2019.03", "2019. 3.", "2019년 3월", "2019-03-01" 처럼 연도 뒤에 월/일이 붙은 줄머리.
_YEAR_PREFIX = re.compile(
    r"^[\-·•ㆍ○▶\s]*((?:19|20)\d{2})\s*(?:년|[.\-/])\s*(?:\d{1,2}\s*(?:월|[.\-/])?\s*(?:\d{1,2}\s*일?)?)?\s*[:\-]?\s*(.*)$"
)
# 연혁 사건이 시작되는 소제목: "사. 그 밖에 경영활동과 관련된 중요한 사항의 발생내용"(현행 서식)
# 또는 "가. 당해 기업의 연혁"/"가. 주요 연혁"(이전 서식).
_EVENT_HEADING = re.compile(
    r"그\s*밖에.*중요한\s*사항|^[가-하]\.\s*(?:당해\s*기업의\s*|회사의\s*)?(?:주요\s*)?연혁"
)
_SUB_HEADING = re.compile(r"^[가-하]\.\s")
# "☞ ... 참고하시기 바랍니다." 같은 참조 안내. 문장 끝에 이어 붙어 줄 중간에 올 수도 있다.
# 안내가 "바랍니다/하십시오"로 끝나면 거기까지, 아니면 줄 끝까지 지운다.
_REFERENCE_NOTE = re.compile(r"[☞※][^\n]*?(?:바랍니다|하십시오)\.?|[☞※][^\n]*")
# 연혁 목록이 끝나고 다른 설명이 시작되는 표지: "(2) 조직의 변경" 같은 번호 소제목, "[2021년 12월]" 표.
_END_MARKER = re.compile(r"^\(\d+\)\s|^\[\s*(?:19|20)\d{2}")


@dataclass(frozen=True, slots=True)
class HistoryItem:
    """연혁 한 항목."""

    year: int
    text: str


def extract_business_summary(xml: str, max_chars: int = SUMMARY_MAX_CHARS) -> str | None:
    """'사업의 개요' 섹션의 앞부분을 요약으로 돌려준다. 찾지 못하면 None.

    '☞ ... 참고하시기 바랍니다' 같은 참조 안내 줄은 뺀다. 문장 끝(다. 로 끝나는
    곳)에서 max_chars 이내로 자른다.
    """
    body = _section2_body(xml, r"1\.\s*사업의\s*개요")
    if body is None:
        return None
    cleaned = (_REFERENCE_NOTE.sub("", line).strip() for line in _to_lines(body))
    text = " ".join(line for line in cleaned if line).strip()
    if not text:
        return None
    return _cut_at_sentence(text, max_chars)


def extract_history(xml: str) -> list[HistoryItem]:
    """'회사의 연혁'에서 연도별 주요 사건을 최신순으로 돌려준다. 읽지 못하면 빈 목록.

    '그 밖에 경영활동과 관련된 중요한 사항의 발생내용'(또는 이전 서식의 '당해 기업의
    연혁') 항목만 대상으로 한다 (임원 변동표, 최대주주 변동 등은 연혁이 아니다).
    줄 단위로 읽으며 두 형식을 지원한다.
      * 표/목록: 연도만 있는 줄 다음에 사건 줄들이 이어지는 형식
      * 문장: "2019.03 ○○ 설립"처럼 줄머리에 연도가 붙은 형식
    """
    body = _section2_body(xml, r"\d*\.?\s*회사의\s*연혁")
    if body is None:
        return []
    lines = _to_lines(body)
    start = next((i for i, line in enumerate(lines) if _EVENT_HEADING.search(line)), None)
    if start is None:
        return []
    items: list[HistoryItem] = []
    current_year: int | None = None
    for line in lines[start + 1 :]:
        if _SUB_HEADING.match(line) and not _YEAR_PREFIX.match(line):
            break  # 다음 하위 항목으로 넘어갔다
        if items and _END_MARKER.match(line):
            break  # 연혁 목록 뒤에 붙은 다른 설명(조직 변경 등)
        year_only = _YEAR_ONLY.match(line)
        if year_only:
            current_year = int(year_only.group(1))
            continue
        prefixed = _YEAR_PREFIX.match(line)
        if prefixed:
            current_year = int(prefixed.group(1))
            event = prefixed.group(2).strip()
        else:
            event = line.strip(" -·•ㆍ○▶|")
        if current_year is None or not _is_event_text(event):
            continue
        items.append(HistoryItem(current_year, _truncate(event, HISTORY_EVENT_MAX_CHARS)))
    items.sort(key=lambda item: item.year, reverse=True)  # 안정 정렬이라 같은 해는 원문 순서 유지
    return _limit_per_year(items)[:HISTORY_MAX_ITEMS]


def _limit_per_year(items: list[HistoryItem]) -> list[HistoryItem]:
    """한 해에 HISTORY_MAX_PER_YEAR개까지만 남긴다 (순서 유지)."""
    counts: dict[int, int] = {}
    kept: list[HistoryItem] = []
    for item in items:
        counts[item.year] = counts.get(item.year, 0) + 1
        if counts[item.year] <= HISTORY_MAX_PER_YEAR:
            kept.append(item)
    return kept


def _section2_body(xml: str, title_pattern: str) -> str | None:
    """제목이 title_pattern과 일치하는 SECTION-2의 본문 조각을 돌려준다."""
    start = re.search(_SECTION2_TEMPLATE.format(title=title_pattern), xml)
    if start is None:
        return None
    rest = xml[start.end() :]
    end = _NEXT_SECTION.search(rest)
    return rest[: end.start()] if end else rest


def _to_lines(fragment: str) -> list[str]:
    """XML 조각을 태그를 제거한 줄 목록으로 바꾼다 (표의 칸도 한 줄씩)."""
    fragment = re.sub(r"</(P|TR|TITLE|TD|TH|TE|TU)>", "\n", fragment)
    text = html.unescape(re.sub(r"<[^>]+>", "", fragment))
    lines = (re.sub(r"\s+", " ", line).strip() for line in text.splitlines())
    return [line for line in lines if line and line != "|"]


def _is_event_text(text: str) -> bool:
    """연혁 사건으로 볼 만한 텍스트인지 판단한다 (표 머리글/기호 줄 제외)."""
    if len(text) < 4:
        return False
    return text not in {"구분", "내용", "주요내용", "주요 내용", "연도", "일자", "해당사항 없음"}


def _cut_at_sentence(text: str, max_chars: int) -> str:
    """max_chars 이내에서 마지막으로 끝난 문장까지 자른다. 문장 끝이 없으면 그냥 자른다."""
    if len(text) <= max_chars:
        return text
    window = text[:max_chars]
    cut = max(window.rfind("다."), window.rfind("다. "))
    if cut >= max_chars // 3:
        return window[: cut + 2].strip()
    return _truncate(window, max_chars)


def _truncate(text: str, max_chars: int) -> str:
    return text if len(text) <= max_chars else text[: max_chars - 1].rstrip() + "…"
