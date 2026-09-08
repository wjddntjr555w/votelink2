"""캠프 공간을 디스크에 만든다 — `votelink camp new` 의 알맹이.

**`yaml.safe_dump` 를 쓰지 않는다.** 이 저장소의 설정 파일은 판단 근거를 주석으로
안고 있는 것이 관례다(`party_lineage.yaml` 1032줄의 대부분이 주석이다). 덤프는
주석을 만들지 못하므로, 사람이 이어서 손으로 고칠 파일은 템플릿으로 쓴다.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from votelink.camp.loader import camp_dir, cycle_dir
from votelink.camp.models import CampInfo, Cycle
from votelink.reference.districts import load_districts

CAMP_YAML = """\
# 캠프 신원 — **영속**. 선거가 끝나도 남는 것만 둔다.
# 관할·진영·선거일처럼 다음 선거에 바뀔 수 있는 값은 cycles/<주기>/election.yaml 에 있다
# (docs/proposals/P-001-camp-data-isolation.md §7).

camp_id: {camp_id}
candidate_name: {candidate_name}
created_at: {created_at}
"""

ELECTION_YAML = """\
# 이 선거 주기의 설정 — **주기별**.
# 구청장에 나갔다가 다음엔 시의원에 나갈 수 있고 당적도 바뀐다. 그래서 관할도
# 진영도 캠프가 아니라 여기 있다 (P-001 §7).

election:
  type: {etype}
  office: {office}
  # 선거일. **모르면 null 로 둔다.** 임의 날짜로 채우지 않는다 —
  # 여론조사 공표 금지기간(§108)처럼 기간에 의존하는 판정은 이 값 없이 계산할 수
  # 없고, 그런 항목은 전부 unreviewed 로 떨어진다.
  date: {edate}

# 렌즈 — 우리 진영. party_lineage.yaml 의 4축과 같은 값이어야 한다.
# 이 한 줄이면 기존 동별 camp_share 가 그 즉시 우세/열세로 읽힌다 (P-001 §5).
lineage: {lineage}

# 관할. **참조가 아니라 실체다** — 아래 emd_codes 가 진실이고 preset 은 그것을
# 무엇으로 채웠는지의 기록일 뿐이다. 이 한 수로 캠프 관할이 국회의원 선거구
# 모델에서 분리된다 (P-001 §6).
#
# **여기가 틀리면 모든 분석이 조용히 틀린다.** 에러가 나지 않고 그냥 다른 답이
# 나온다. 고칠 때는 `uv run votelink district list --emd` 로 대조하라.
territory:
  preset: {preset}
  emd_codes:
{emd_lines}
{reviewer_block}"""

CANDIDATES_YAML = """\
# 후보 로스터 — 우리 1명 + 상대 N명.
#
# **공개 출처 필드만 적는다.** 선관위 후보자정보·언론 보도로 확인 가능한 것에 한한다.
# 사적 정보·미확인 소문은 어떤 경우에도 넣지 않는다
# (docs/new_process.md — 상대 후보 뒷조사 금지).
#
# 절대규칙 3 은 **유권자** 개인을 겨냥한다. 후보는 공인이고, 공개된 공적 기록에
# 한해 별개 축으로 허용된다 (P-001 §14).

ours:
  name: {name}
  party: {party}
  lineage: {lineage}
  incumbent: {incumbent}

# 상대 후보. 후보 확정 전이면 비어 있어도 된다.
#
# 무소속·신당은 진영이 자명하지 않다. **근거를 note 에 적고 손으로 정한다.**
# 미기입을 other 로 자동 강등하지 않는다 — party_lineage.yaml 이 "매핑에 없는
# 후보는 격리된다"고 못박은 것과 같은 이유로, 조용히 other 로 떨어뜨리면
# '분류 누락'과 '실제 군소후보'를 구분할 수 없게 된다.
#
# 예시:
# opponents:
#   - name: 김철수
#     party: 국민의힘
#     lineage: conservative
#     incumbent: true
#   - name: 이영희
#     party: 무소속
#     lineage: centrist
#     incumbent: false
#     note: 국민의힘 경선 불복 탈당. 계보는 보수이나 중도 표방으로 완주 중.
opponents: []
"""


REVIEW_YAML = """\
# 이 캠프·이 선거 주기의 **법률 검토 기록**.
#
# 무엇이 위험한가(위험도·배포범위·기간제한)는 모두에게 같아서 공용에 있다:
#   data/shared/reference/compliance.policy.yaml
# **검토했는가는 캠프마다 다르다.** 그래서 여기 있다 (P-001 §13).
#
# 검토를 마쳤다면 그 kind 를 아래에 추가하고 status 를 cleared 로, reviewed_by 와
# reviewed_at 을 채운다. **reviewed_by 가 비어 있으면 cleared 로 인정되지 않는다** —
# 서명 없는 서명란은 서명이 아니다.
#
# **여기 없는 kind 는 미검토로 떨어진다**(fail-closed). 새 분석기가 새 산출물을 내도
# 아무도 모르게 검증이 비켜가지 않는다는 뜻이며, 그게 절대 규칙 5다.
#
# 시스템은 적법성을 판정하지 않는다. 검토가 있었는지만 기록하고, 없으면 웹앱이
# 경고를 띄운다. 최종 판단자는 캠프의 법률 검토다.
#
# 예시:
# outputs:
#   - kind: segment_profile
#     status: cleared
#     reviewed_by: 김변호사 (○○법률사무소)
#     reviewed_at: '2026-09-10'
#     note: 공표된 집계의 재표현이고 최소 단위가 행정동이라 개인정보가 없음을 확인.

version: "{version}"
outputs: []
"""


class ScaffoldError(RuntimeError):
    """이미 있는 것을 덮어쓰려 했거나 관할을 만들 수 없다."""


def resolve_territory(
    preset: str | None,
    sigungu: str | None,
    emd_codes: list[str],
    districts_path: Path | None = None,
) -> tuple[str | None, list[str]]:
    """(preset 기록, 확정된 행정동 코드 목록).

    셋 다 합칠 수 있다 — 프리셋으로 채운 뒤 `--emd` 로 몇 개 더 붙이는 식이다.
    기초의원 선거구처럼 프리셋이 없는 경우는 `--emd` 만으로 만든다 (P-001 §6).
    """
    districts = load_districts(districts_path)
    codes: list[str] = []
    label = preset or (f"sigungu:{sigungu}" if sigungu else None)

    if preset:
        if preset not in districts:
            known = ", ".join(sorted(districts)) or "(없음)"
            raise ScaffoldError(f"프리셋 선거구 '{preset}' 를 찾을 수 없다. 있는 것: {known}")
        codes += districts[preset].emd_codes

    if sigungu:
        matched = [d for d in districts.values() if d.sigungu == sigungu]
        if not matched:
            known = ", ".join(sorted({d.sigungu for d in districts.values()}))
            raise ScaffoldError(f"자치구 '{sigungu}' 에 해당하는 선거구가 없다. 있는 것: {known}")
        # 구청장은 국회의원 선거구 여럿을 아우른다 — 그 합집합이 관할이다 (P-001 §6).
        for d in matched:
            codes += d.emd_codes

    codes += emd_codes
    if not codes:
        raise ScaffoldError(
            "관할이 비었다. --preset(선거구) · --sigungu(자치구) · --emd(직접) 중 "
            "하나 이상을 줘야 한다"
        )

    seen: dict[str, None] = {}
    for c in codes:
        seen.setdefault(c, None)
    return label, list(seen)


def write_camp(info: CampInfo, root: Path | None = None) -> Path:
    target = camp_dir(info.camp_id, root)
    path = target / "camp.yaml"
    if path.exists():
        raise ScaffoldError(f"캠프가 이미 있다: {path}")
    target.mkdir(parents=True, exist_ok=True)
    path.write_text(
        CAMP_YAML.format(
            camp_id=info.camp_id,
            candidate_name=info.candidate_name,
            created_at=info.created_at.isoformat(),
        ),
        encoding="utf-8",
    )
    return path


def write_cycle(
    camp_id: str,
    cycle_id: str,
    cycle: Cycle,
    ours_name: str,
    ours_party: str,
    ours_incumbent: bool,
    root: Path | None = None,
) -> Path:
    target = cycle_dir(camp_id, cycle_id, root)
    if (target / "election.yaml").exists():
        raise ScaffoldError(f"선거 주기가 이미 있다: {target}")
    target.mkdir(parents=True, exist_ok=True)

    reviewer = cycle.legal_reviewer
    reviewer_block = (
        f"\n# 법률 검토 서명 주체. **시스템은 이 서명을 보증하지 않는다** —\n"
        f"# 캠프당 계정이 하나라 그 이름이 그 사람인지 확인할 수 없다. 사람이 적는 값이다.\n"
        f"legal_reviewer: {reviewer}\n"
        if reviewer
        else "\n# 법률 검토자가 정해지면 여기 적는다. compliance 검토 서명의 주체가 된다.\n"
        "legal_reviewer: null\n"
    )

    (target / "election.yaml").write_text(
        ELECTION_YAML.format(
            etype=cycle.election.type.value,
            office=cycle.election.office.value,
            edate=cycle.election.date.isoformat() if cycle.election.date else "null",
            lineage=cycle.lineage.value,
            preset=cycle.territory.preset or "null",
            emd_lines="\n".join(f'    - "{c}"' for c in cycle.territory.emd_codes),
            reviewer_block=reviewer_block,
        ),
        encoding="utf-8",
    )

    (target / "candidates.yaml").write_text(
        CANDIDATES_YAML.format(
            name=ours_name,
            party=ours_party,
            lineage=cycle.lineage.value,
            incumbent="true" if ours_incumbent else "false",
        ),
        encoding="utf-8",
    )

    (target / "compliance.review.yaml").write_text(
        REVIEW_YAML.format(version=cycle_id), encoding="utf-8"
    )

    # shared/ 와 같은 모양이라 store.py 가 루트만 바꿔 재사용된다 (P-001 §9).
    for sub in ("records", "rejected", "incoming"):
        (target / sub).mkdir(exist_ok=True)
    return target


def default_cycle_id(cycle: Cycle, fallback: str | None = None) -> str:
    if cycle.election.date is not None:
        return f"{cycle.election.date.isoformat()}-{cycle.election.type.value}"
    if fallback:
        return fallback
    raise ScaffoldError(
        "선거일을 모르면 주기 이름을 유도할 수 없다. --cycle 로 직접 정하라 "
        "(예: --cycle 2028-미정-national_assembly)"
    )


def today() -> date:
    """생성일. 테스트가 갈아끼울 수 있게 함수로 둔다."""
    return date.today()
