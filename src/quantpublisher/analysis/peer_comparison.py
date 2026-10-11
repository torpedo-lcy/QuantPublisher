"""종목을 같은 업종, 같은 시장의 다른 종목과 비교한다 (Task 020).

DB나 외부 API를 읽지 않는 순수 함수만 둔다. 전 종목의 지표를 한 번에 받아
종목별 비교 결과(값, 그룹 중앙값, 그룹 내 순위)를 만든다.

비교 규칙:
    * 비교 지표: PER, PBR, ROE, 영업이익률.
    * 같은 기준 시점의 종목끼리만 비교한다. PER, PBR은 밸류에이션 기준 월,
      ROE, 영업이익률은 재무제표 기준 연도가 같아야 한다.
    * PER, PBR이 0 이하(적자 등)인 값은 의미가 없으므로 중앙값과 순위에서 뺀다.
    * 지표별 비교 표본이 MIN_SAMPLE개 미만이면 중앙값과 순위를 만들지 않는다.
    * 순위는 값이 큰 순서(1위가 가장 큼)이다. 좋고 나쁨을 판단하지 않는다.

업종 그룹:
    KSIC 업종코드의 앞 3자리(소분류)가 같은 종목들이다. 종목이 MIN_SAMPLE개 미만인
    소분류는 앞 2자리(중분류)로 넓히고, 그래도 부족하면 업종 비교를 하지 않는다.
    업종코드는 3~5자리가 섞여 있으나 KSIC가 계층 구조이므로 앞자리 비교가 성립한다.
시장 그룹:
    같은 시장(KOSPI, KOSDAQ, KONEX)의 종목들이다.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from statistics import median
from typing import Mapping, Sequence

# 지표별 비교 표본의 최소 크기, 업종 그룹의 최소 종목 수.
MIN_SAMPLE = 10

METRIC_KEYS: tuple[str, ...] = ("per", "pbr", "roe", "operating_margin")
# 값이 0 이하이면 의미가 없는 지표.
_POSITIVE_ONLY = frozenset({"per", "pbr"})


@dataclass(frozen=True, slots=True)
class PeerInput:
    """한 종목의 비교 입력.

    Attributes:
        stock_code: 종목코드.
        market: 시장 구분 (KOSPI, KOSDAQ, KONEX).
        industry_code: KSIC 업종코드. 모르면 None.
        values: 지표 키 -> 값. 계산하지 못했으면 None이거나 키가 없다.
        bases: 지표 키 -> 기준 시점 문자열(예: "2026-07", "2025"). 같은 값끼리만 비교한다.
    """

    stock_code: str
    market: str
    industry_code: str | None
    values: Mapping[str, float | None]
    bases: Mapping[str, str | None]


@dataclass(frozen=True, slots=True)
class MetricComparison:
    """한 지표의 그룹 내 비교.

    Attributes:
        key: 지표 키.
        value: 이 종목의 값 (비교 대상이 아니어도 값이 있으면 채운다).
        median: 그룹 중앙값. 표본이 부족하면 None.
        rank: 값이 큰 순서의 순위(1이 최대). 이 종목이 비교 대상이 아니거나 표본이 부족하면 None.
        sample: 비교에 쓰인 값의 개수.
    """

    key: str
    value: float | None
    median: float | None
    rank: int | None
    sample: int


@dataclass(frozen=True, slots=True)
class GroupComparison:
    """한 그룹(업종 또는 시장)과의 비교.

    Attributes:
        key: 그룹 식별자. 업종이면 KSIC 앞자리(2~3자리), 시장이면 시장명.
        size: 그룹에 속한 종목 수 (지표 값 유무와 무관).
        metrics: METRIC_KEYS 순서의 지표별 비교.
    """

    key: str
    size: int
    metrics: tuple[MetricComparison, ...]


@dataclass(frozen=True, slots=True)
class PeerComparison:
    """한 종목의 비교 결과. 업종 그룹을 만들 수 없으면 industry는 None."""

    industry: GroupComparison | None
    market: GroupComparison | None


def compute_peer_comparisons(inputs: Sequence[PeerInput]) -> dict[str, PeerComparison]:
    """전 종목의 비교 결과를 종목코드별로 만든다."""
    industry_members = _index_industry_members(inputs)
    market_members: dict[str, list[PeerInput]] = defaultdict(list)
    for item in inputs:
        market_members[item.market].append(item)

    # (그룹 종류, 그룹 키) -> (지표, 기준 시점) -> 오름차순 정렬된 값
    cache: dict[tuple[str, str], dict[tuple[str, str], list[float]]] = {}

    def samples(kind: str, key: str, members: list[PeerInput]) -> dict[tuple[str, str], list[float]]:
        if (kind, key) not in cache:
            cache[(kind, key)] = _sorted_samples(members)
        return cache[(kind, key)]

    results: dict[str, PeerComparison] = {}
    for item in inputs:
        industry_key = _industry_group_key(item.industry_code, industry_members)
        industry = None
        if industry_key is not None:
            members = industry_members[industry_key]
            industry = _compare(item, industry_key, members, samples("industry", industry_key, members))
        market = None
        members = market_members[item.market]
        if members:
            market = _compare(item, item.market, members, samples("market", item.market, members))
        results[item.stock_code] = PeerComparison(industry=industry, market=market)
    return results


def _index_industry_members(inputs: Sequence[PeerInput]) -> dict[str, list[PeerInput]]:
    """업종코드 앞 2자리, 3자리 접두어별 종목 목록."""
    members: dict[str, list[PeerInput]] = defaultdict(list)
    for item in inputs:
        code = _clean_code(item.industry_code)
        if code is None:
            continue
        members[code[:2]].append(item)
        if len(code) >= 3:
            members[code[:3]].append(item)
    return members


def _industry_group_key(industry_code: str | None, members: Mapping[str, list[PeerInput]]) -> str | None:
    """종목이 속할 업종 그룹의 접두어. 3자리가 작으면 2자리, 그래도 작으면 None."""
    code = _clean_code(industry_code)
    if code is None:
        return None
    for length in (3, 2):
        prefix = code[:length]
        if len(prefix) == length and len(members.get(prefix, [])) >= MIN_SAMPLE:
            return prefix
    return None


def _clean_code(industry_code: str | None) -> str | None:
    if industry_code is None:
        return None
    code = industry_code.strip()
    return code if len(code) >= 2 and code.isdigit() else None


def _meaningful(key: str, value: float | None) -> bool:
    if value is None or not math.isfinite(value):
        return False
    return value > 0 if key in _POSITIVE_ONLY else True


def _sorted_samples(members: Sequence[PeerInput]) -> dict[tuple[str, str], list[float]]:
    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    for member in members:
        for key in METRIC_KEYS:
            value = member.values.get(key)
            basis = member.bases.get(key)
            if basis is not None and _meaningful(key, value):
                grouped[(key, basis)].append(float(value))  # type: ignore[arg-type]
    for values in grouped.values():
        values.sort()
    return grouped


def _compare(
    item: PeerInput,
    group_key: str,
    members: Sequence[PeerInput],
    sorted_values: Mapping[tuple[str, str], list[float]],
) -> GroupComparison:
    rows = []
    for key in METRIC_KEYS:
        value = item.values.get(key)
        basis = item.bases.get(key)
        pool = sorted_values.get((key, basis), []) if basis is not None else []
        enough = len(pool) >= MIN_SAMPLE
        group_median = median(pool) if enough else None
        rank = None
        if enough and _meaningful(key, value):
            rank = len(pool) - bisect_right(pool, float(value)) + 1  # type: ignore[arg-type]
        rows.append(
            MetricComparison(
                key=key,
                value=value,
                median=group_median,
                rank=rank,
                sample=len(pool),
            )
        )
    return GroupComparison(key=group_key, size=len(members), metrics=tuple(rows))
