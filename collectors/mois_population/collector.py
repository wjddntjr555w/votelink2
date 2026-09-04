"""행정안전부 주민등록 인구 수집기 (성별·연령별, 행정동 단위).

fetch: 공공데이터포털 API를 페이지 단위로 호출해 응답을 그대로 저장한다
parse: 순수 함수. 행을 행정동으로 접고, 대상 지역구의 동 이름으로 걸러 공통 레코드로 만든다

전략: 동별 코드를 미리 알 필요가 없다. 시군구 코드 하나(lv=3)로 조회하면
산하 행정동이 이미 동 단위로 집계된 채로, 각 동 고유의 admmCd 와 함께 온다.
그 응답을 지역구의 동 '이름' 목록으로 걸러내면 끝난다 — districts.yaml 의
emd[].code 가 비어 있어도(미확인이어도) 수집이 된다.

응답 형식을 코드에 박지 않는다. 요청 파라미터 이름, 목록 경로, 필드명은 전부
meta.yaml 의 config 와 aggregate.py 상단 상수로 뺐다 — 형식이 다르면 파이썬이 아니라
설정을 고친다.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import datetime
from typing import Any
from urllib.parse import unquote

import httpx

from votelink.collect import BaseCollector, ParseResult, RawBatch, polite_client
from votelink.collect.http import FetchError
from votelink.contract.models import KST, Record
from votelink.reference import resolve_district

from .aggregate import EmdAggregate, aggregate_rows
from .response import ApiError, ResponseShapeError, extract_rows

SERVICE_KEY_ENV = "DATA_GO_KR_SERVICE_KEY"


def emd_admm_codes(raw: RawBatch) -> Iterator[tuple[str, str, str]]:
    """raw 응답에서 (시군구명, 행정동명, admmCd) 를 그대로 펼친다.

    이름 필터도, 계약 변환도 하지 않는다 — `districts.yaml` 백필(`district
    backfill-codes`)이 그 자치구의 **모든** 행정동을 보고 싶을 때 쓴다. 봉투 열기·
    통반 집계는 이 수집기의 `extract_rows`/`aggregate_rows` 를 그대로 재사용해
    응답 형식 지식이 이 패키지 밖으로 새지 않게 한다.
    """
    rows = extract_rows(raw.body, "")
    for agg in aggregate_rows(rows):
        if agg.admm_code:
            yield agg.sigungu, agg.emd, agg.admm_code


def normalize_service_key(raw: str) -> str:
    """포털은 인증키를 Encoding/Decoding 두 형태로 준다.

    Encoding 키(%2F, %2B, %3D 포함)를 그대로 파라미터에 넣으면 클라이언트가 다시
    인코딩해(%252F) 인증이 실패한다. 그래서 항상 디코딩된 형태로 되돌린다.
    """
    key = raw.strip()
    return unquote(key) if "%" in key else key


class Collector(BaseCollector):
    id = "mois_population"

    # --- fetch ---------------------------------------------------------------

    def fetch(self, since: datetime | None) -> Iterator[RawBatch]:
        """월 스냅샷이라 since 는 무시한다 (meta.incremental=false)."""
        service_key = normalize_service_key(os.environ.get(SERVICE_KEY_ENV, ""))
        if not service_key:
            raise FetchError(
                f"환경변수 {SERVICE_KEY_ENV} 가 없다. "
                "공공데이터포털 마이페이지 > 오픈API > 인증키를 넣어라"
            )

        endpoint = self.cfg("endpoint", "")
        if not endpoint or "REPLACE-ME" in endpoint:
            raise FetchError("meta.yaml 의 config.endpoint 가 비어 있다")

        paging = self.cfg("paging", {}) or {}
        page_param = paging.get("page_param", "pageNo")
        size_param = paging.get("size_param", "numOfRows")
        size = int(paging.get("size", 1000))
        max_pages = int(paging.get("max_pages", 100))

        base_params: dict[str, Any] = {
            "serviceKey": service_key,
            **(self.cfg("params", {}) or {}),
            **self.month_params(),
        }

        code_param = self.cfg("admm_code_param", "")
        codes = self.query_codes()
        targets: list[dict[str, Any]] = (
            [{code_param: code} for code in codes] if (code_param and codes) else [{}]
        )

        with polite_client(self.meta) as client:
            for target in targets:
                label = "-".join(str(v) for v in target.values()) or "all"
                for page in range(1, max_pages + 1):
                    resp = client.get(
                        endpoint,
                        params={**base_params, **target, page_param: page, size_param: size},
                    )
                    body = self._decode(resp)
                    yield RawBatch(
                        collector_id=self.id,
                        body=body,
                        batch_key=f"{self.reference_month}-{label}-p{page:03d}",
                        source_url=self.meta.source_url,
                    )
                    try:
                        rows = extract_rows(body, self.cfg("data_path", ""))
                    except ApiError as exc:
                        raise FetchError(f"포털이 오류를 돌려줬다: {exc}") from exc
                    except ResponseShapeError:
                        # 형식 문제는 parse 단계에서 격리로 정식 보고된다.
                        # 여기서는 더 넘길 페이지가 없다고 보고 멈춘다.
                        break
                    if len(rows) < size:
                        break

    @staticmethod
    def _decode(resp: httpx.Response) -> Any:
        """JSON이 아니면(XML 등) 무엇이 왔는지 보여준다. 조용히 실패하지 않는다."""
        try:
            return resp.json()
        except ValueError as exc:
            head = resp.text[:300].replace("\n", " ")
            raise FetchError(
                f"응답이 JSON이 아니다 (content-type={resp.headers.get('content-type')}). "
                f"config.params 에 type/resultType 을 JSON으로 넣어야 할 수 있다. 앞부분: {head}"
            ) from exc

    # --- parse ---------------------------------------------------------------

    def parse(self, raw: RawBatch) -> Iterator[ParseResult]:
        rows = extract_rows(raw.body, self.cfg("data_path", ""))
        aggs = aggregate_rows(rows)

        target = self._target_names()
        if target:
            aggs, missing = self._filter_to_target(aggs, target)
            if missing:
                # 페이지 하나에 시군구 전체가 다 들어온다는 전제(§ query_codes)가
                # 깨지면(대상이 아주 큰 시군구라 여러 페이지로 나뉘면) 오탐할 수 있다.
                # 지금 규모(9개 동, 응답 27건)에서는 안전하다.
                raise ValueError(
                    f"응답에서 다음 행정동을 찾지 못했다: {', '.join(sorted(missing))}. "
                    "동 이름이 바뀌었거나 여러 페이지에 걸쳐 나뉘어 왔을 수 있다"
                )

        yield from self.map_items(aggs, self._to_record)

    @staticmethod
    def _filter_to_target(
        aggs: list[EmdAggregate], target: set[str]
    ) -> tuple[list[EmdAggregate], set[str]]:
        found = {a.emd for a in aggs}
        return [a for a in aggs if a.emd in target], target - found

    def _to_record(self, agg: EmdAggregate) -> Record:
        agg.check_total()  # 연령별 합 != 총인구수 이면 이 레코드만 격리된다
        month = self.reference_month
        return Record(
            kind="population",
            collector_id=self.id,
            source_name=self.meta.source_name,
            source_url=self.meta.source_url,
            source_license=self.meta.source_license,
            observed_at=datetime.strptime(f"{month}-01", "%Y-%m-%d").replace(tzinfo=KST),
            observed_precision="month",
            geo_level="emd",
            geo_code=self._geo_code(agg),
            geo_name=agg.emd,
            confidence=1.0,
            derived_from=[],
            natural_key=f"{month}|{agg.admm_code or agg.full_name}",
            payload={
                "reference_month": month,
                "breakdown": agg.breakdown(),
                "total": agg.breakdown_total,
                "households": None,  # 세대수는 다른 데이터셋에 있다
            },
        )

    @staticmethod
    def _geo_code(agg: EmdAggregate) -> str:
        """이 API는 항상 admmCd 를 준다. 없으면 응답 형식이 바뀐 것이므로 즉시 알린다.

        출처가 코드를 주는데 이름으로 되돌려 찾는 것은 사고를 부른다 —
        조용한 대체 경로를 두지 않는다.
        """
        if not agg.admm_code:
            raise ValueError(
                f"{agg.full_name}: 응답에 admmCd 가 없다. 응답 형식이 바뀌었을 수 있다"
            )
        return agg.admm_code

    # --- 설정 -----------------------------------------------------------------
    # `cfg()` 는 BaseCollector 가 준다 — 선거구로 해석된 config 를 읽는다.

    def month_params(self) -> dict[str, str]:
        """기준월 하나에서 조회 기간 파라미터를 만든다 (2026-07 -> 202607).

        기준월을 바꿀 때 고칠 곳이 한 군데뿐이어야 한다.
        """
        names = self.cfg("month_params", {}) or {}
        compact = self.reference_month.replace("-", "")
        return {name: compact for key in ("from", "to") if (name := names.get(key))}

    def query_codes(self) -> list[str]:
        """요청에 쓸 admmCd 목록.

        우선순위: 명시적 admm_codes > 시군구 코드(sigungu_admm_code) > 없음(필터 없이 전체 조회).
        명시적 admm_codes 를 쓰면 이름 필터링을 하지 않는다 — 사용자가 범위를
        직접 통제하겠다는 뜻으로 본다.
        """
        explicit = [str(c) for c in (self.cfg("admm_codes") or [])]
        if explicit:
            return explicit
        sigungu_code = self.cfg("sigungu_admm_code")
        if sigungu_code:
            return [str(sigungu_code)]
        return []

    def _target_names(self) -> set[str]:
        """응답을 걸러낼 행정동 이름 집합.

        explicit admm_codes 를 쓰는 경우엔 필터링하지 않는다 (호출자가 이미
        범위를 좁혔다고 본다). district 로 조회하는 기본 경로에서만 걸러낸다.
        """
        if self.cfg("admm_codes"):
            return set()
        district_key = self.cfg("district")
        if not district_key:
            return set()
        return {e.name for e in resolve_district(district_key).emd}

    @property
    def reference_month(self) -> str:
        month = self.cfg("reference_month")
        if not month:
            raise FetchError("meta.yaml 의 config.reference_month 가 비어 있다")
        return str(month)
