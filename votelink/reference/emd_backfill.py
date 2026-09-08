"""districts.yaml 의 emd[].code 를 mois_population raw 응답의 admmCd 로 채운다.

D-001 (`docs/proposals/D-001-seoul-emd-backfill.md`).

입력은 **`data/raw/mois_population/` 의 원본 응답**이지 `data/records/mois_population.jsonl`
이 아니다 — raw 는 `lv=3` 조회라 그 자치구의 모든 행정동이 각자의 admmCd 와 함께 들어
있어 이름 불일치까지 진단할 수 있다(parse 가 실패해도 raw 는 fetch 시점에 이미 저장돼
있다). jsonl 은 이름이 이미 맞은 동만 들어 있어 그럴 수 없다.

정확 일치만 자동으로 채운다. 표기가 다른 동(`창신제1동` vs `창신1동` 같은)은 채우지
않고 리포트로만 드러낸다 — 근사 매칭이 옆 동 코드를 붙이면 조용히 틀린 전략이 나온다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from collectors.mois_population.collector import emd_admm_codes
from votelink.collect.storage import iter_raw
from votelink.contract.models import GEO_CODE_DIGITS
from votelink.reference.districts import DISTRICTS_PATH, DistrictNotFound, load_districts
from votelink.store import DataSpace


@dataclass
class BackfillReport:
    filled: list[tuple[str, str, str]] = field(default_factory=list)
    unmatched_yaml: list[tuple[str, str]] = field(default_factory=list)
    unmatched_response: list[tuple[str, str, str]] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    missing_raw_sigungu: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """채울 게 있었는데 충돌뿐이었으면 실패로 본다. 불일치는 정상적인 중간 상태다."""
        return not self.conflicts

    def summary(self) -> str:
        lines: list[str] = []
        if self.filled:
            lines.append(f"채움 {len(self.filled)}건:")
            lines += [f"  {did:<26} {name:<10} -> {code}" for did, name, code in self.filled]
        if self.conflicts:
            lines.append(f"충돌 {len(self.conflicts)}건 (건너뜀):")
            lines += [f"  {c}" for c in self.conflicts]
        if self.unmatched_yaml:
            lines.append(
                f"이름 불일치(yaml 에는 있으나 응답에서 못 찾음) {len(self.unmatched_yaml)}건:"
            )
            lines += [f"  {did:<26} {name}" for did, name in self.unmatched_yaml]
        if self.unmatched_response:
            lines.append("응답에만 있는 동 (위 불일치의 정답 후보):")
            lines += [
                f"  {sigungu:<10} {name:<10} {code}"
                for sigungu, name, code in self.unmatched_response
            ]
        if self.missing_raw_sigungu:
            lines.append("raw 없음 (그 자치구로 아직 collect 를 안 돌렸다):")
            lines += [f"  {s}" for s in self.missing_raw_sigungu]
        if not lines:
            lines.append("변화 없음 (채울 pending 이 없거나 raw 가 없다).")
        return "\n".join(lines)


def _build_admm_index(space: DataSpace) -> tuple[dict[tuple[str, str], str], list[str]]:
    """raw 전체에서 (시군구명, 행정동명) -> admmCd. 배치 하나의 문제로 전체를 죽이지 않는다."""
    index: dict[tuple[str, str], str] = {}
    conflicts: list[str] = []
    for batch in iter_raw("mois_population", space):
        try:
            triples = list(emd_admm_codes(batch))
        except Exception as exc:  # noqa: BLE001 - 배치 하나가 깨져도 나머지는 계속 읽는다
            conflicts.append(f"{batch.batch_key}: raw 를 읽지 못했다 ({type(exc).__name__}: {exc})")
            continue
        for sigungu, name, code in triples:
            key = (sigungu, name)
            existing = index.get(key)
            if existing is not None and existing != code:
                conflicts.append(
                    f"{sigungu} {name}: admmCd 가 배치마다 다르다 ({existing} vs {code})"
                )
                continue
            index[key] = code
    return index, conflicts


def backfill(
    *,
    district_id: str | None = None,
    districts_path: Path | None = None,
    space: DataSpace | None = None,
    dry_run: bool = False,
) -> BackfillReport:
    """districts.yaml 의 emd[].code 를 raw 응답의 admmCd 로 채운다. 재실행해도 안전하다."""
    path = districts_path or DISTRICTS_PATH
    index, conflicts = _build_admm_index(space or DataSpace.default())
    districts = load_districts(path, force=True)

    if district_id:
        if district_id not in districts:
            known = ", ".join(sorted(districts)) or "(없음)"
            raise DistrictNotFound(f"선거구 '{district_id}' 를 찾을 수 없다. 정의된 것: {known}")
        targets = [districts[district_id]]
    else:
        targets = list(districts.values())

    report = BackfillReport(conflicts=conflicts)
    seen_sigungu = {sigungu for sigungu, _ in index}
    fills: list[tuple[str, str, str]] = []

    for d in targets:
        has_raw = d.sigungu in seen_sigungu
        if not has_raw and any(e.code is None for e in d.emd):
            report.missing_raw_sigungu.append(f"{d.id} ({d.sigungu})")
        used_codes = {e.code for e in d.emd if e.code}
        for e in d.emd:
            if e.code is not None:
                continue
            code = index.get((d.sigungu, e.name))
            if code is None:
                # raw 자체가 없으면 missing_raw_sigungu 가 이미 설명한다 — 이름 불일치로
                # 착각하게 만들지 않는다.
                if has_raw:
                    report.unmatched_yaml.append((d.id, e.name))
                continue
            if not (code.isdigit() and len(code) == GEO_CODE_DIGITS):
                report.conflicts.append(f"{d.id} {e.name}: admmCd 형식이 이상하다 ({code!r})")
                continue
            if code in used_codes:
                report.conflicts.append(f"{d.id} {e.name}: admmCd {code} 가 이미 다른 동에 쓰였다")
                continue
            used_codes.add(code)
            report.filled.append((d.id, e.name, code))
            fills.append((d.id, e.name, code))

    yaml_names_by_sigungu: dict[str, set[str]] = {}
    for d in districts.values():
        yaml_names_by_sigungu.setdefault(d.sigungu, set()).update(e.name for e in d.emd)
    for (sigungu, name), code in sorted(index.items()):
        if name not in yaml_names_by_sigungu.get(sigungu, set()):
            report.unmatched_response.append((sigungu, name, code))

    if fills and not dry_run:
        _write_codes(path, fills)

    return report


_NAME_RE_CACHE: dict[str, re.Pattern[str]] = {}


def _emd_null_pattern(name: str) -> re.Pattern[str]:
    cached = _NAME_RE_CACHE.get(name)
    if cached is None:
        cached = re.compile(rf'(- \{{ name: "{re.escape(name)}", code: )null(?= \}})')
        _NAME_RE_CACHE[name] = cached
    return cached


def _write_codes(path: Path, fills: list[tuple[str, str, str]]) -> None:
    """districts.yaml 을 줄 단위로 고쳐 쓴다.

    `yaml.safe_dump` 은 주석과 `{ name: "x", code: null }` 흐름 스타일을 날린다. 파일이
    `- id: <id>` 블록 안에 `- { name: "<동>", code: null }` 로 매우 규칙적이므로 그
    `code: null` 한 조각만 정규식으로 바꾼다 — 그 외 문자는 손대지 않는다.
    """
    by_district: dict[str, dict[str, str]] = {}
    for did, name, code in fills:
        by_district.setdefault(did, {})[name] = code

    original = path.read_text(encoding="utf-8")
    id_re = re.compile(r"^\s*-\s+id:\s*(\S+)\s*$")

    current_id: str | None = None
    out: list[str] = []
    for line in original.splitlines(keepends=True):
        m = id_re.match(line)
        if m:
            current_id = m.group(1)
        pending = by_district.get(current_id) if current_id else None
        if pending:
            for name, code in pending.items():
                new_line = _emd_null_pattern(name).sub(rf'\g<1>"{code}"', line)
                if new_line != line:
                    line = new_line
                    break
        out.append(line)

    path.write_text("".join(out), encoding="utf-8")
    try:
        load_districts(path, force=True)  # 되쓴 파일이 계약을 통과하는지 즉시 검증
    except Exception:
        path.write_text(original, encoding="utf-8")  # 실패하면 원복
        load_districts(path, force=True)
        raise
