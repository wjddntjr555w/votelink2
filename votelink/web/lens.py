"""렌즈 — 공용 데이터를 이 캠프의 관점으로 번역한다.

제안서: `docs/proposals/P-001-camp-data-isolation.md` §5.

공용 데이터는 **진영 단위로 중립 계산**된다. `voter_profile` 이 내는 `camp_share` 는
어느 캠프가 돌려도 같은 값이다. 캠프가 선언하는 것은 한 줄 — "우리는 progressive" —
이고, 그 한 줄이 기존 숫자를 **우세 / 열세**로 읽히게 한다.

데이터 복제도 재수집도 새 분석기도 없다. `party_lineage.yaml` 이 후보를 진영으로
환원해 둔 덕이다(멀티테넌시와 무관한 이유로 그렇게 설계됐는데, 그 결과로 모든 분석이
이미 캠프 중립이 되어 있었다).

**렌즈는 주석이지 접근통제가 아니다.** 관할 밖을 막는 것은 인증이 붙는 P-002 의 일이다.
렌즈가 없으면(`None`) 화면은 지금까지와 똑같이 진영 중립으로 그린다.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from votelink.contract.enums import Camp

# 진영 한글 이름은 viewmodel 이 이미 들고 있다. 여기서 다시 만들지 않는다.


class Lens(BaseModel):
    """어느 캠프의 눈으로 보는가."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    camp_id: str
    cycle_id: str
    candidate_name: str
    lineage: Camp
    """우리 진영. `party_lineage.yaml` 의 4축과 같은 값이다."""

    party: str | None = None
    territory: frozenset[str] = frozenset()
    """관할 행정동 코드. 화면이 "이 동은 우리 관할인가"를 표시하는 데 쓴다.

    **막는 데 쓰지 않는다.** 캠프 A 세션으로 캠프 B 관할을 요청하면 거부하는 것은
    세션이 있어야 가능하고, 그건 P-002 다.
    """

    opponents: tuple[str, ...] = ()
    """상대 후보 이름. 로스터가 비어 있으면(후보 확정 전) 빈 튜플이다."""

    def is_ours(self, camp: Camp) -> bool:
        return camp is self.lineage

    def covers(self, geo_code: str | None) -> bool:
        """이 동이 캠프 관할인가. 관할이 비어 있으면 판단하지 않고 True."""
        return not self.territory or (geo_code is not None and geo_code in self.territory)

    @property
    def label(self) -> str:
        who = self.candidate_name
        return f"{who} ({self.party})" if self.party else who


def load_lens(camp_id: str, cycle_id: str | None, root=None, districts_path=None) -> Lens:
    """캠프 설정에서 렌즈를 만든다.

    `votelink.camp` 를 여기서 import 한다 — L3 가 캠프 계층을 아는 유일한 자리다.
    그 대신 `votelink/camp/` 는 웹을 전혀 모른다(의존이 한 방향이다).

    **`districts_path` 를 반드시 넘긴다.** 관할 검증이 쓰는 선거구 정의와 화면이 쓰는
    것이 달라지면, 렌즈는 통과했는데 화면은 그 선거구를 모르는 상태가 된다. 실제로
    그랬다 — `load_districts` 의 캐시가 경로를 무시하므로 먼저 읽은 쪽이 이긴다.
    """
    from votelink import camp as camp_mod

    if cycle_id is None:
        # **선거일 기준으로 고른다.** 아직 안 지난 선거 중 가장 가까운 것 —
        # 캠프는 늘 "다음 선거"를 준비한다. 예전의 `list_cycles()[-1]`(사전순 마지막)은
        # `미정-…` 주기가 언제나 이기게 만들었다 (`camp/loader.py:current_cycle_id`).
        cycle_id = camp_mod.current_cycle_id(camp_id, root, districts_path=districts_path)
        if cycle_id is None:
            raise camp_mod.CycleNotFound(
                f"캠프 '{camp_id}' 에 선거 주기가 없다. "
                "`uv run votelink camp new` 로 만들거나 --cycle 을 지정하라"
            )

    info = camp_mod.load_camp(camp_id, root)
    cycle = camp_mod.load_cycle(camp_id, cycle_id, root, districts_path=districts_path)
    try:
        roster = camp_mod.load_roster(camp_id, cycle_id, root)
    except FileNotFoundError:
        roster = None

    return Lens(
        camp_id=info.camp_id,
        cycle_id=cycle_id,
        candidate_name=info.candidate_name,
        lineage=cycle.lineage,
        party=roster.ours.party if roster else None,
        territory=frozenset(cycle.territory.emd_codes),
        opponents=tuple(o.name for o in roster.opponents) if roster else (),
    )
