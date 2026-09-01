"""행정안전부 주민등록 인구 수집기 (성별·연령별, 행정동 단위).

fetch: 공공데이터포털 API를 페이지 단위로 호출해 응답을 그대로 저장한다
parse: 순수 함수. 통·반 행을 행정동으로 접고 공통 레코드로 만든다

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

from votelink.collect import BaseCollector, ParseResult, RawBatch, polite_client, to_emd_code
from votelink.collect.http import FetchError
from votelink.contract.models import KST, Record
from votelink.reference import resolve_district

from .aggregate import EmdAggregate, aggregate_rows
from .response import ApiError, ResponseShapeError, extract_rows

SERVICE_KEY_ENV = "DATA_GO_KR_SERVICE_KEY"


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
        codes = self.target_codes()
        self._require_resolved_codes(codes)
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
        yield from self.map_items(aggregate_rows(rows), self._to_record)

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
        """응답에 행정기관코드가 있으면 그대로 쓴다.

        출처가 코드를 주는데 이름으로 되돌려 찾는 것은 사고를 부른다.
        코드가 없을 때만 '시도 시군구 행정동' 표기로 매핑표를 조회한다.
        """
        if agg.admm_code:
            return agg.admm_code
        return to_emd_code(agg.full_name, system="mois")

    # --- 설정 -----------------------------------------------------------------

    def cfg(self, key: str, default: Any = None) -> Any:
        return self.meta.config.get(key, default)

    def month_params(self) -> dict[str, str]:
        """기준월 하나에서 조회 기간 파라미터를 만든다 (2026-07 -> 202607).

        기준월을 바꿀 때 고칠 곳이 한 군데뿐이어야 한다.
        """
        names = self.cfg("month_params", {}) or {}
        compact = self.reference_month.replace("-", "")
        return {name: compact for key in ("from", "to") if (name := names.get(key))}

    def _require_resolved_codes(self, codes: list[str]) -> None:
        """미확인 행정동을 조용히 건너뛰지 않는다.

        9개 중 3개만 수집되면 그 3개만으로 그럴듯한 전략이 나온다.
        """
        if codes:
            return
        key = self.cfg("district")
        if not key:
            return
        district = resolve_district(key)
        if district.pending:
            missing = ", ".join(e.name for e in district.pending)
            raise FetchError(
                f"{district.name} 의 행정동코드 {len(district.pending)}개가 아직 미확인이다: "
                f"{missing}\n  → data/reference/districts.yaml 의 code 를 채워라 "
                "(확인: uv run votelink district list --emd)"
            )

    def target_codes(self) -> list[str]:
        """조회할 행정동 기관코드. config.admm_codes 가 비면 선거구 정의를 따른다."""
        explicit = [str(c) for c in (self.cfg("admm_codes") or [])]
        if explicit:
            return explicit
        district_key = self.cfg("district")
        return resolve_district(district_key).emd_codes if district_key else []

    @property
    def reference_month(self) -> str:
        month = self.cfg("reference_month")
        if not month:
            raise FetchError("meta.yaml 의 config.reference_month 가 비어 있다")
        return str(month)
