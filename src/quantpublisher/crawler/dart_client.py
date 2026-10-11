"""OpenDART API 클라이언트 (Task 019).

네트워크 호출만 담당한다. 응답 해석(사업보고서 본문 파싱)과 저장은 다른 모듈의 일이다.

사용하는 API:
    company.json  : 기업개황 (업종코드, 설립일, 대표자 등)
    list.json     : 공시 목록 (최신 사업보고서 접수번호 찾기)
    document.xml  : 공시서류 원본 (zip 안의 본문 XML)

보안:
    API 키는 요청 URL의 쿼리에 들어가므로, URL을 로그나 예외 메시지에 넣지 않는다.
    이 모듈이 발생시키는 예외는 키를 포함하지 않는다.

한도:
    OpenDART는 일 20,000건, 분당 1,000건을 넘으면 차단한다. 요청 사이에
    최소 간격(min_interval)을 두고, 한도 초과(status 020)는 DartRateLimitError로
    전달해 호출자가 즉시 중단할 수 있게 한다.
"""

from __future__ import annotations

import io
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

logger = logging.getLogger(__name__)

_BASE_URL = "https://opendart.fss.or.kr/api/"
_TIMEOUT_SECONDS = 60
_DEFAULT_MIN_INTERVAL = 0.15  # 초당 약 6~7건. 분당 한도(1,000건)의 절반 이하.
# 압축을 푼 본문 XML의 최대 크기. 삼성전자 같은 대형 보고서가 약 8MB라 여유를 둔다.
_MAX_XML_BYTES = 64 * 1024 * 1024

_STATUS_OK = "000"
_STATUS_NO_DATA = "013"
_STATUS_RATE_LIMIT = "020"


class DartError(Exception):
    """DART 호출 중 발생한 오류. 메시지에 API 키나 URL을 넣지 않는다."""


class DartRateLimitError(DartError):
    """요청 한도 초과 (status 020). 더 호출하지 말고 중단해야 한다."""


class DartApiError(DartError):
    """DART가 오류 status를 돌려준 경우 (키 오류 등)."""

    def __init__(self, status: str, message: str) -> None:
        super().__init__(f"DART 오류 status={status} message={message}")
        self.status = status


@dataclass(frozen=True, slots=True)
class AnnualReportRef:
    """공시 목록에서 찾은 사업보고서 한 건.

    Attributes:
        rcept_no: 접수번호 (document.xml 조회 키).
        report_name: 보고서명 (예: "사업보고서 (2025.12)").
        receipt_date: 접수일 (YYYYMMDD).
        fiscal_year: 보고서명에서 읽은 사업연도. 읽지 못하면 None.
    """

    rcept_no: str
    report_name: str
    receipt_date: str
    fiscal_year: int | None


class DartClient:
    """OpenDART 최소 클라이언트."""

    def __init__(self, api_key: str, min_interval: float = _DEFAULT_MIN_INTERVAL) -> None:
        if not api_key.strip():
            raise ValueError("DART API 키가 비어 있습니다.")
        self._api_key = api_key.strip()
        self._min_interval = min_interval
        self._last_request_at = 0.0

    def get_company(self, corp_code: str) -> dict[str, Any] | None:
        """기업개황을 조회한다. 해당 회사 정보가 없으면 None."""
        return self._get_json("company.json", {"corp_code": corp_code})

    def find_latest_annual_report(
        self, corp_code: str, today: date | None = None
    ) -> AnnualReportRef | None:
        """최근 2년 안에 접수된 가장 최근 사업보고서를 찾는다. 없으면 None.

        정정 공시([기재정정] 등)도 전체 본문을 담고 있으므로 후보에 포함하고,
        접수일이 가장 늦은 것을 고른다.
        """
        end = today or date.today()
        begin = end - timedelta(days=730)
        payload = self._get_json(
            "list.json",
            {
                "corp_code": corp_code,
                "bgn_de": begin.strftime("%Y%m%d"),
                "end_de": end.strftime("%Y%m%d"),
                "pblntf_detail_ty": "A001",  # 사업보고서
                "page_count": "20",
            },
        )
        if payload is None:
            return None
        return pick_latest_annual_report(payload.get("list", []))

    def fetch_report_xml(self, rcept_no: str) -> str:
        """공시서류 원본 zip에서 본문 XML(접수번호.xml)을 문자열로 반환한다.

        Raises:
            DartError: 네트워크 오류, 오류 응답, 본문 누락, 비정상적으로 큰 파일.
        """
        raw = self._request("document.xml", {"rcept_no": rcept_no})
        if not zipfile.is_zipfile(io.BytesIO(raw)):
            # 오류는 zip이 아니라 XML/JSON 본문으로 온다.
            raise _error_from_body(raw)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            name = f"{rcept_no}.xml"
            if name not in archive.namelist():
                raise DartError("공시서류 zip에 본문 XML이 없습니다.")
            if archive.getinfo(name).file_size > _MAX_XML_BYTES:
                raise DartError("공시서류 본문이 허용 크기를 넘습니다.")
            return archive.read(name).decode("utf-8", errors="replace")

    def _get_json(self, path: str, params: dict[str, str]) -> dict[str, Any] | None:
        raw = self._request(path, params)
        try:
            payload = json.loads(raw)
        except ValueError as exc:
            raise DartError("DART 응답이 JSON이 아닙니다.") from exc
        status = str(payload.get("status", ""))
        if status == _STATUS_OK:
            return payload
        if status == _STATUS_NO_DATA:
            return None
        if status == _STATUS_RATE_LIMIT:
            raise DartRateLimitError("DART 요청 한도를 초과했습니다 (status 020).")
        raise DartApiError(status, str(payload.get("message", "")))

    def _request(self, path: str, params: dict[str, str]) -> bytes:
        self._throttle()
        query = urllib.parse.urlencode({"crtfc_key": self._api_key, **params})
        try:
            with urllib.request.urlopen(f"{_BASE_URL}{path}?{query}", timeout=_TIMEOUT_SECONDS) as r:
                return r.read()
        except urllib.error.HTTPError as exc:
            raise DartError(f"DART HTTP 오류 {exc.code} ({path})") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # URLError 메시지에는 URL이 들어가지 않지만, 원인 체인도 끊어 키 노출을 막는다.
            raise DartError(f"DART 네트워크 오류 ({path}): {type(exc).__name__}") from None

    def _throttle(self) -> None:
        wait = self._min_interval - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()


def pick_latest_annual_report(items: list[dict[str, Any]]) -> AnnualReportRef | None:
    """공시 목록 항목들에서 접수일이 가장 늦은 사업보고서를 고른다 (순수 함수).

    본문 없이 첨부 서류만 고치는 `[첨부정정]`, `[첨부추가]` 공시는 document.xml에
    본문 XML이 없으므로 제외한다 (그 앞의 정상 보고서를 쓴다).
    """
    candidates = [
        item
        for item in items
        if "사업보고서" in str(item.get("report_nm", ""))
        and "첨부" not in str(item.get("report_nm", ""))
        and item.get("rcept_no")
    ]
    if not candidates:
        return None
    latest = max(candidates, key=lambda item: (str(item.get("rcept_dt", "")), str(item["rcept_no"])))
    name = str(latest["report_nm"])
    return AnnualReportRef(
        rcept_no=str(latest["rcept_no"]),
        report_name=name,
        receipt_date=str(latest.get("rcept_dt", "")),
        fiscal_year=_fiscal_year_from_name(name),
    )


def _fiscal_year_from_name(report_name: str) -> int | None:
    """"사업보고서 (2025.12)" 같은 보고서명에서 사업연도를 읽는다."""
    match = re.search(r"\((\d{4})\.\d{2}\)", report_name)
    return int(match.group(1)) if match else None


def _error_from_body(raw: bytes) -> DartError:
    """document.xml이 zip 대신 돌려준 오류 본문에서 status를 읽어 예외를 만든다."""
    text = raw.decode("utf-8", errors="replace")
    status = re.search(r"<status>(\d+)</status>", text)
    message = re.search(r"<message>([^<]*)</message>", text)
    if status and status.group(1) == _STATUS_RATE_LIMIT:
        return DartRateLimitError("DART 요청 한도를 초과했습니다 (status 020).")
    if status:
        return DartApiError(status.group(1), message.group(1) if message else "")
    return DartError("DART가 zip이 아닌 응답을 돌려줬습니다.")
