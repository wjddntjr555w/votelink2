"""행정안전부 주민등록 인구 수집기.

공공데이터포털 자동변환 오픈API(odcloud)에서 통·반 단위 성/연령별 인구를 받아
행정동 × 10년 연령대 × 성별로 접어 공통 레코드로 만든다.

fetch: 페이지 단위로 원본을 그대로 가져온다 (파싱하지 않는다)
parse: 순수 함수. 재집계와 계약 변환만 한다
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import datetime

from votelink.collect import BaseCollector, ParseResult, RawBatch, polite_client, to_emd_code
from votelink.collect.http import FetchError
from votelink.contract.models import KST, Record

from .aggregate import EmdAggregate, aggregate_rows

SERVICE_KEY_ENV = "DATA_GO_KR_SERVICE_KEY"
DATA_FIELD = "data"  # odcloud 응답의 목록 키


class Collector(BaseCollector):
    id = "mois_population"

    # --- fetch ---------------------------------------------------------------

    def fetch(self, since: datetime | None) -> Iterator[RawBatch]:
        """월 스냅샷이라 since 는 무시한다 (meta.incremental=false)."""
        service_key = os.environ.get(SERVICE_KEY_ENV)
        if not service_key:
            raise FetchError(
                f"환경변수 {SERVICE_KEY_ENV} 가 없다. "
                "공공데이터포털에서 활용신청 후 발급받은 일반 인증키(Decoding)를 넣어라"
            )

        endpoint = self.meta.config.get("endpoint", "")
        if "REPLACE-ME" in endpoint or not endpoint:
            raise FetchError(
                "meta.yaml 의 config.endpoint 가 아직 채워지지 않았다. "
                "공공데이터포털 데이터셋 페이지의 요청 URL(uddi 포함)을 붙여넣어라"
            )

        per_page = int(self.meta.config.get("per_page", 1000))
        max_pages = int(self.meta.config.get("max_pages", 200))

        with polite_client(self.meta) as client:
            for page in range(1, max_pages + 1):
                resp = client.get(
                    endpoint,
                    params={
                        "serviceKey": service_key,
                        "page": page,
                        "perPage": per_page,
                        "returnType": "JSON",
                    },
                )
                body = resp.json()
                yield RawBatch(
                    collector_id=self.id,
                    body=body,
                    batch_key=f"{self._reference_month}-p{page:04d}",
                    source_url=self.meta.source_url,
                )
                if len(body.get(DATA_FIELD) or []) < per_page:
                    break

    # --- parse ---------------------------------------------------------------

    def parse(self, raw: RawBatch) -> Iterator[ParseResult]:
        rows = (raw.body or {}).get(DATA_FIELD) or []
        yield from self.map_items(aggregate_rows(rows), self._to_record)

    def _to_record(self, agg: EmdAggregate) -> Record:
        agg.check_total()  # 연령별 합 != 총인구수 이면 여기서 격리된다
        month = self._reference_month
        return Record(
            kind="population",
            collector_id=self.id,
            source_name=self.meta.source_name,
            source_url=self.meta.source_url,
            source_license=self.meta.source_license,
            observed_at=datetime.strptime(f"{month}-01", "%Y-%m-%d").replace(tzinfo=KST),
            observed_precision="month",
            geo_level="emd",
            # 출처에 행정구역 코드가 없어 '시도 시군구 행정동' 전체 표기로 조회한다.
            # 동명이 겹쳐도 상위 행정구역이 붙어 있어 유일하게 결정된다.
            geo_code=to_emd_code(agg.full_name, system="mois"),
            geo_name=agg.emd,
            confidence=1.0,
            derived_from=[],
            natural_key=f"{month}|{agg.full_name}",
            payload={
                "reference_month": month,
                "breakdown": agg.breakdown(),
                "total": agg.breakdown_total,
                "households": None,  # 세대수는 다른 데이터셋에 있다
            },
        )

    @property
    def _reference_month(self) -> str:
        month = self.meta.config.get("reference_month")
        if not month:
            raise FetchError("meta.yaml 의 config.reference_month 가 비어 있다")
        return str(month)
