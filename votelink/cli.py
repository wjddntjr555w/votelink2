"""votelink 명령줄 도구."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from pydantic import ValidationError

from votelink import camp, store
from votelink.analyze import registry as analyze_registry
from votelink.analyze import runner as analyze_runner
from votelink.analyze.base import AnalyzeError
from votelink.camp import Office, scaffold
from votelink.collect import geo, registry, runner
from votelink.collect.http import FetchError
from votelink.contract.enums import Camp, ElectionType
from votelink.contract.models import GEO_CODE_DIGITS, KST
from votelink.reference import compliance, districts, emd_backfill
from votelink.reference.districts import DistrictNotFound
from votelink.store import DataSpace
from votelink.web import DEFAULT_HOST, DEFAULT_PORT
from votelink.web.loader import AmbiguousDistrict, load_profiles
from votelink.web.settings import WebSettings

# 행안부/통계청 파일마다 헤더 이름이 다르다. 흔한 이름을 먼저 시도한다.
CODE_COL_CANDIDATES = ("행정기관코드", "행정동코드", "adm_cd", "emd_code", "코드")
NAME_COL_CANDIDATES = ("행정기관명", "행정동명", "adm_nm", "emd_name", "명칭", "행정구역명")


def _parse_since(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=KST)


def _district_ids(config: dict) -> list[str]:
    """meta.yaml 의 config.districts 에 등록된 선거구 id 목록. --all-districts 가 이걸 돈다."""
    return list((config.get("districts") or {}).keys())


def _pick_column(header: list[str], explicit: str | None, candidates: tuple[str, ...]) -> str:
    if explicit:
        if explicit not in header:
            raise SystemExit(f"열 '{explicit}' 이 파일에 없다. 있는 열: {', '.join(header)}")
        return explicit
    for candidate in candidates:
        if candidate in header:
            return candidate
    raise SystemExit(
        f"코드/이름 열을 자동으로 찾지 못했다. --code-col / --name-col 로 지정하라. "
        f"있는 열: {', '.join(header)}"
    )


# --- 명령 ----------------------------------------------------------------------


def cmd_collect(args: argparse.Namespace) -> int:
    if args.all_districts:
        return _collect_all_districts(args)

    collector = registry.load(args.collector_id, district_id=args.district)

    try:
        _ = collector.config  # 선거구 설정을 지금 해석해 문제를 빨리 드러낸다
    except KeyError as exc:
        print(f"선거구 설정 오류: {exc}", file=sys.stderr)
        return 1

    if args.capture_fixture:
        return _capture_fixture(collector)

    if not collector.meta.verified:
        print(
            f"[주의] {collector.id} 는 실제 응답으로 검증되지 않았다 (meta.verified=false). "
            "--capture-fixture 로 fixture 를 받고 테스트를 통과시킨 뒤 verified 를 올려라"
        )
    try:
        report = runner.run(
            collector,
            space=DataSpace.default(),
            since=_parse_since(args.since),
            dry_run=args.dry_run,
            reparse=args.reparse,
        )
    except FetchError as exc:
        # 설정 누락·네트워크 실패는 사용자가 고칠 일이다. 트레이스백을 보여줄 이유가 없다.
        print(f"수집 실패: {exc}", file=sys.stderr)
        return 1
    print(report.summary())
    if args.dry_run:
        print("(dry-run: 아무것도 저장하지 않았다)")
    return 1 if report.failed else 0


def _capture_fixture(collector) -> int:
    """첫 배치의 원본을 tests/fixtures/sample_raw.json 에 저장한다.

    손으로 만든 가짜 데이터 대신 실제 응답으로 테스트하기 위한 통로다.
    """
    try:
        batch = next(iter(collector.fetch(None)), None)
    except FetchError as exc:
        print(f"수집 실패: {exc}", file=sys.stderr)
        return 1
    if batch is None:
        print("fetch 가 배치를 하나도 내놓지 않았다", file=sys.stderr)
        return 1

    target = collector.package_dir / "tests" / "fixtures" / "sample_raw.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(batch.body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    size = target.stat().st_size
    print(f"{target} 저장 ({size:,} bytes)")
    print(f"다음: uv run pytest {collector.package_dir}/")
    return 0


def _collect_all_districts(args: argparse.Namespace) -> int:
    """meta.yaml 의 config.districts 에 등록된 모든 선거구를 차례로 수집한다.

    선거구마다 registry.load 로 **새 인스턴스**를 만든다 — BaseCollector 는 첫
    config 해석 결과를 캐시하므로(base.py) 인스턴스를 재사용하면 안 된다. 한
    선거구가 실패해도 나머지는 계속 돌고, 하나라도 실패하면 종료코드 1.
    """
    if args.capture_fixture:
        print("--all-districts 와 --capture-fixture 는 함께 쓸 수 없다", file=sys.stderr)
        return 1

    base = registry.load(args.collector_id)
    ids = _district_ids(base.meta.config)
    if not ids:
        print(
            f"{args.collector_id}: meta.yaml 에 config.districts 가 없다. "
            "--all-districts 는 선거구 블록이 여럿일 때 쓴다",
            file=sys.stderr,
        )
        return 1
    if not base.meta.verified:
        print(f"[주의] {base.id} 는 실제 응답으로 검증되지 않았다 (meta.verified=false).")

    since = _parse_since(args.since)
    reports = []
    failures: list[str] = []
    for did in ids:
        print(f"[{did}]")
        collector = registry.load(args.collector_id, district_id=did)
        try:
            _ = collector.config  # 선거구 설정을 지금 해석해 문제를 빨리 드러낸다
        except KeyError as exc:
            print(f"[{did}] 선거구 설정 오류: {exc}", file=sys.stderr)
            failures.append(did)
            continue
        try:
            report = runner.run(
                collector,
                space=DataSpace.default(),
                since=since,
                dry_run=args.dry_run,
                reparse=args.reparse,
            )
        except FetchError as exc:
            print(f"[{did}] 수집 실패: {exc}", file=sys.stderr)
            failures.append(did)
            continue
        print(report.summary())
        reports.append(report)
        if report.failed:
            failures.append(did)

    print(
        f"[합계] 선거구 {len(reports)}/{len(ids)} · "
        f"유효 {sum(r.accepted for r in reports)} · 저장 {sum(r.written for r in reports)} · "
        f"격리 {sum(r.rejected for r in reports)} · 중복 {sum(r.duplicates for r in reports)}"
        + (f"\n실패 {len(failures)}: {', '.join(failures)}" if failures else "")
    )
    if args.dry_run:
        print("(dry-run: 아무것도 저장하지 않았다)")
    return 1 if failures else 0


def cmd_registry_sync(args: argparse.Namespace) -> int:
    path = registry.sync()
    metas = registry.discover()
    print(f"{path} 갱신 · 수집기 {len(metas)}개")
    return 0


def cmd_registry_list(args: argparse.Namespace) -> int:
    metas = registry.discover()
    if not metas:
        print("등록된 수집기가 없다. 스킬 `new-collector` 로 추가하라")
        return 0
    for meta in metas.values():
        kinds = ",".join(str(k) for k in meta.kinds)
        print(f"{meta.id:<28} {kinds:<20} {meta.source_name}")
    return 0


def cmd_geo_import(args: argparse.Namespace) -> int:
    """행안부/통계청 행정동코드 파일을 내부 매핑표로 가져온다."""
    src = Path(args.source)
    if not src.exists():
        raise SystemExit(f"파일이 없다: {src}")

    with src.open(encoding=args.encoding, newline="") as fh:
        reader = csv.DictReader(fh)
        header = reader.fieldnames or []
        code_col = _pick_column(header, args.code_col, CODE_COL_CANDIDATES)
        name_col = _pick_column(header, args.name_col, NAME_COL_CANDIDATES)
        rows = []
        for r in reader:
            code = (r.get(code_col) or "").strip()
            full_name = (r.get(name_col) or "").strip()
            rows.append(
                {
                    "source_system": args.system,
                    "source_code": code,
                    "source_name": full_name,
                    "emd_code": code[:GEO_CODE_DIGITS],
                    # 공식 파일의 행정기관명은 '서울특별시 송파구 풍납1동' 형태다.
                    # 마지막 토큰이 동명이며, 짧은 이름으로도 조회할 수 있어야 한다.
                    "emd_name": full_name.split()[-1] if full_name else "",
                }
            )

    rows = [r for r in rows if len(r["emd_code"]) == GEO_CODE_DIGITS and r["emd_code"].isdigit()]
    if not rows:
        raise SystemExit(
            f"{GEO_CODE_DIGITS}자리 행정동코드가 한 건도 없다. --code-col 이 맞는지, "
            "시도/시군구 단위 파일을 넣은 건 아닌지 확인하라"
        )

    target = geo.REFERENCE_CSV
    target.parent.mkdir(parents=True, exist_ok=True)
    exists = target.exists() and args.append
    with target.open("a" if exists else "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=geo.CSV_HEADER)
        if not exists:
            writer.writeheader()
        writer.writerows(rows)

    geo.reset_table()
    print(f"{target} 에 {len(rows)}건 {'추가' if exists else '기록'} (system={args.system})")
    return 0


def cmd_geo_lookup(args: argparse.Namespace) -> int:
    try:
        code = geo.to_emd_code(args.value, system=args.system)
    except geo.GeoMappingError as exc:
        print(f"실패: {exc}", file=sys.stderr)
        return 1
    print(f"{args.value} -> {code} ({geo.to_emd_name(args.value, system=args.system)})")
    return 0


def cmd_district_list(args: argparse.Namespace) -> int:
    try:
        found = districts.load_districts()
    except FileNotFoundError as exc:
        print(f"실패: {exc}", file=sys.stderr)
        return 1
    for d in found.values():
        state = "확인 완료" if d.fully_resolved else f"미확인 {len(d.pending)}개"
        print(f"{d.id:<22} {d.name:<16} 행정동 {len(d.emd)}개 · {state}  (출처: {d.source})")
        if args.verbose_emd:
            for e in d.emd:
                code = e.code or "(미확인)"
                org = f"org={e.org_code}" if e.org_code else ""
                print(f"    {code:<12} {e.name:<8} {org}")
    if any(not d.fully_resolved for d in found.values()):
        print("\n미확인 행정동은 수집에서 제외된다. districts.yaml 의 code 를 채워라.")
    return 0


def cmd_district_backfill(args: argparse.Namespace) -> int:
    """mois_population raw 응답의 admmCd 로 districts.yaml 의 emd[].code 를 채운다 (D-001)."""
    try:
        report = emd_backfill.backfill(district_id=args.district, dry_run=args.dry_run)
    except districts.DistrictNotFound as exc:
        print(f"실패: {exc}", file=sys.stderr)
        return 1
    print(report.summary())
    if args.dry_run and (report.filled or report.conflicts):
        print("\n(dry-run: 아무것도 고치지 않았다)")
    return 1 if not report.ok else 0


def cmd_analyze(args: argparse.Namespace) -> int:
    if args.sync:
        path = analyze_registry.sync()
        metas = analyze_registry.discover()
        print(f"{path} 갱신 · 분석기 {len(metas)}개")
        return 0

    if args.all:
        return _analyze_all(args)

    if not args.analyzer_id:
        metas = analyze_registry.discover()
        if not metas:
            print("등록된 분석기가 없다. analyzers/<id>/meta.yaml 을 만들어라")
            return 2
        for meta in metas.values():
            mark = "✓" if meta.verified else " "
            inputs = ", ".join(str(k) for k in meta.inputs)
            print(f"{mark} {meta.id:<20} {meta.name}\n    입력: {inputs}")
        return 0

    if args.all_districts:
        return _analyze_all_districts(args)

    analyzer = analyze_registry.load(args.analyzer_id, district_id=args.district)
    try:
        _ = analyzer.config  # 선거구 설정을 지금 해석해 문제를 빨리 드러낸다
    except KeyError as exc:
        print(f"선거구 설정 오류: {exc}", file=sys.stderr)
        return 1
    if not analyzer.meta.verified:
        print(
            f"[주의] {analyzer.id} 는 실제 입력으로 검증되지 않았다 (meta.verified=false). "
            "산출물을 신뢰하기 전에 테스트를 통과시키고 verified 를 올려라"
        )
    try:
        report = analyze_runner.run(analyzer, space=DataSpace.default(), dry_run=args.dry_run)
    except AnalyzeError as exc:
        # 참조 데이터 결손 같은 것은 사용자가 고칠 일이다. 트레이스백을 보여줄 이유가 없다.
        print(f"분석 실패: {exc}", file=sys.stderr)
        return 1
    print(report.summary())
    if args.dry_run:
        print("(dry-run: 아무것도 저장하지 않았다)")
    return 1 if report.failed else 0


def _analyze_all_districts(args: argparse.Namespace) -> int:
    """meta.yaml 의 config.districts 에 등록된 모든 선거구를 차례로 분석한다.
    _collect_all_districts 와 같은 규칙 — 선거구마다 새 인스턴스, 부분 실패 허용."""
    base = analyze_registry.load(args.analyzer_id)
    ids = _district_ids(base.meta.config)
    if not ids:
        print(
            f"{args.analyzer_id}: meta.yaml 에 config.districts 가 없다. "
            "--all-districts 는 선거구 블록이 여럿일 때 쓴다",
            file=sys.stderr,
        )
        return 1
    if not base.meta.verified:
        print(f"[주의] {base.id} 는 실제 입력으로 검증되지 않았다 (meta.verified=false).")

    reports = []
    failures: list[str] = []
    for did in ids:
        print(f"[{did}]")
        analyzer = analyze_registry.load(args.analyzer_id, district_id=did)
        try:
            _ = analyzer.config
        except KeyError as exc:
            print(f"[{did}] 선거구 설정 오류: {exc}", file=sys.stderr)
            failures.append(did)
            continue
        try:
            report = analyze_runner.run(analyzer, space=DataSpace.default(), dry_run=args.dry_run)
        except AnalyzeError as exc:
            print(f"[{did}] 분석 실패: {exc}", file=sys.stderr)
            failures.append(did)
            continue
        print(report.summary())
        reports.append(report)
        if report.failed:
            failures.append(did)

    print(
        f"[합계] 선거구 {len(reports)}/{len(ids)} · "
        f"산출 {sum(r.computed for r in reports)} · 유효 {sum(r.accepted for r in reports)} · "
        f"격리 {sum(r.rejected for r in reports)} · 교체 {sum(r.replaced for r in reports)} · "
        f"신규 {sum(r.added for r in reports)}"
        + (f"\n실패 {len(failures)}: {', '.join(failures)}" if failures else "")
    )
    if args.dry_run:
        print("(dry-run: 아무것도 저장하지 않았다)")
    return 1 if failures else 0


def _analyze_all(args: argparse.Namespace) -> int:
    """등록된 모든 분석기를, 각 분석기 meta.config.districts 의 모든 선거구로 돌린다.

    입력 레코드는 kind 별로 **한 번만** 읽어 전 실행에 공유한다 — naver_news 는
    수만 줄이라, 분석기·선거구 조합마다 다시 읽으면 수 분이 걸린다. 현재 어떤
    분석기도 다른 분석기의 산출 kind 를 입력으로 먹지 않으므로 (news_article·
    election_result·population 은 전부 L1) 공유 로드가 안전하다.
    """
    metas = analyze_registry.discover()
    if not metas:
        print("등록된 분석기가 없다. analyzers/<id>/meta.yaml 을 만들어라", file=sys.stderr)
        return 2

    wanted_kinds = sorted({k for m in metas.values() for k in m.inputs}, key=str)
    print(f"입력 로드: {', '.join(str(k) for k in wanted_kinds)} …")
    shared = store.load_records(wanted_kinds, space=DataSpace.default())
    by_kind: dict = {}
    for r in shared:
        by_kind.setdefault(r.kind, []).append(r)
    print(f"  {len(shared)}건")

    reports = []
    failures: list[str] = []
    for aid, meta in metas.items():
        ids = _district_ids(meta.config)
        if not ids:
            print(f"[{aid}] config.districts 가 비어 건너뛴다")
            continue
        if not meta.verified:
            print(f"[주의] {aid} 는 실제 입력으로 검증되지 않았다 (meta.verified=false).")
        subset = [r for k in meta.inputs for r in by_kind.get(k, [])]
        for did in ids:
            tag = f"{aid}/{did}"
            print(f"[{tag}]")
            analyzer = analyze_registry.load(aid, district_id=did)
            try:
                _ = analyzer.config
            except KeyError as exc:
                print(f"[{tag}] 선거구 설정 오류: {exc}", file=sys.stderr)
                failures.append(tag)
                continue
            try:
                report = analyze_runner.run(
                    analyzer, space=DataSpace.default(), dry_run=args.dry_run, records=subset
                )
            except AnalyzeError as exc:
                print(f"[{tag}] 분석 실패: {exc}", file=sys.stderr)
                failures.append(tag)
                continue
            print(report.summary())
            reports.append(report)
            if report.failed:
                failures.append(tag)

    print(
        f"\n[합계] 실행 {len(reports)} · 산출 {sum(r.computed for r in reports)} · "
        f"유효 {sum(r.accepted for r in reports)} · 격리 {sum(r.rejected for r in reports)} · "
        f"교체 {sum(r.replaced for r in reports)} · 신규 {sum(r.added for r in reports)}"
        + (f"\n실패 {len(failures)}: {', '.join(failures)}" if failures else "")
    )
    if args.dry_run:
        print("(dry-run: 아무것도 저장하지 않았다)")
    return 1 if failures else 0


def cmd_account_create_operator(args: argparse.Namespace) -> int:
    """첫 운영자를 만드는 유일한 경로. 웹에는 운영자 가입 폼이 없다 (P-002 §6)."""
    from votelink import control

    control.init()
    try:
        account = control.accounts.create(
            args.email,
            args.password,
            role=control.Role.OPERATOR,
            status=control.Status.ACTIVE,
        )
    except control.AccountError as exc:
        print(f"계정을 만들 수 없다: {exc}", file=sys.stderr)
        return 1
    control.audit.log("create_operator", account_id=account.id, target=account.email)
    print(f"운영자 계정 생성: {account.email} (id={account.id})")
    print("다음: uv run votelink serve --auth")
    return 0


def cmd_account_list(args: argparse.Namespace) -> int:
    from votelink import control

    if not control.db.exists():
        print("control.db 가 없다. `uv run votelink account create-operator` 로 시작한다")
        return 0
    rows = control.accounts.listing()
    if not rows:
        print("계정이 없다")
        return 0
    print(f"{'id':>3}  {'이메일':<28} {'역할':<9} {'상태':<10} {'캠프':<20} 세션")
    for a in rows:
        n = control.sessions.active_count(a.id)
        camp = a.camp_id or "—"
        print(
            f"{a.id:>3}  {a.email:<28} {a.role.value:<9} "
            f"{a.status.value:<10} {camp:<20} {n}"
        )
    return 0


def cmd_account_signups(args: argparse.Namespace) -> int:
    """승인 대기 큐. 운영자 콘솔(P-003)이 생기기 전까지 이것이 승인 창구다."""
    from votelink import control

    if not control.db.exists():
        print("control.db 가 없다", file=sys.stderr)
        return 1
    rows = control.signup.pending()
    if not rows:
        print("승인 대기 중인 신청이 없다")
        return 0
    for r in rows:
        print(f"[{r.id}] {r.candidate_name} · {r.contact} · 희망: {r.wanted_election or '—'}")
        print(f"     신청 {r.requested_at}")
    print("\n승인: uv run votelink account approve <신청번호> --operator <운영자id>")
    return 0


def cmd_account_approve(args: argparse.Namespace) -> int:
    from votelink import control

    try:
        camp_id = control.signup.approve(
            args.request_id, args.operator, camp_id=args.camp_id, note=args.note
        )
    except (control.SignupError, control.AccountError) as exc:
        print(f"승인할 수 없다: {exc}", file=sys.stderr)
        return 1
    control.audit.log(
        "approve_signup", account_id=args.operator, camp_id=camp_id, target=str(args.request_id)
    )
    print(f"승인 완료 · 캠프 공간 생성: data/camps/{camp_id}/")
    print("캠프가 로그인해 /onboarding 에서 관할·진영을 채우면 데이터 화면이 열린다")
    return 0


def cmd_account_reject(args: argparse.Namespace) -> int:
    from votelink import control

    try:
        control.signup.reject(args.request_id, args.operator, note=args.note)
    except control.SignupError as exc:
        print(f"거절할 수 없다: {exc}", file=sys.stderr)
        return 1
    control.audit.log("reject_signup", account_id=args.operator, target=str(args.request_id))
    print(f"신청 {args.request_id} 거절")
    return 0


def cmd_account_logout(args: argparse.Namespace) -> int:
    """그 계정의 세션을 전부 끊는다. 비밀번호가 샜을 때의 즉시 대응 (P-002 §14)."""
    from votelink import control

    n = control.sessions.end_all(args.account_id)
    control.audit.log("force_logout", target=str(args.account_id))
    print(f"세션 {n}개 종료")
    return 0


def cmd_account_passwd(args: argparse.Namespace) -> int:
    """운영자가 임시 비밀번호를 발급한다. 자가 재설정은 메일 인프라가 없어 범위 밖이다."""
    from votelink import control

    control.accounts.set_password(args.account_id, args.password)
    n = control.sessions.end_all(args.account_id)
    control.audit.log("set_password", target=str(args.account_id))
    print(f"비밀번호 변경 · 기존 세션 {n}개 종료")
    return 0


def cmd_camp_new(args: argparse.Namespace) -> int:
    """캠프 온보딩. 관할이 실재하는지 여기서 확인하고 못 만들면 아무것도 남기지 않는다."""
    try:
        preset, codes = scaffold.resolve_territory(
            args.preset, args.sigungu, args.emd, districts_path=None
        )
        cycle = camp.Cycle(
            election=camp.Election(type=args.type, office=args.office, date=args.date),
            lineage=args.lineage,
            territory=camp.Territory(preset=preset, emd_codes=codes),
            legal_reviewer=args.reviewer,
        )
        info = camp.CampInfo(
            camp_id=args.camp_id, candidate_name=args.candidate, created_at=scaffold.today()
        )
        cycle_id = args.cycle or scaffold.default_cycle_id(cycle)
    except (scaffold.ScaffoldError, ValidationError, DistrictNotFound) as exc:
        # 설정 오류는 사용자가 고칠 일이다. 트레이스백을 보여줄 이유가 없다.
        print(f"캠프를 만들 수 없다: {exc}", file=sys.stderr)
        return 1

    # 주기 이름이 선거일·계열과 어긋나면 load_cycle 이 나중에 거부한다. 지금 막는다.
    expected = camp.cycle_id_for(cycle)
    if expected is not None and cycle_id != expected:
        print(
            f"주기 이름 '{cycle_id}' 가 선거일·계열에서 나온 '{expected}' 와 다르다. "
            "--cycle 을 빼거나 선거일을 맞춰라",
            file=sys.stderr,
        )
        return 1

    try:
        camp_path = scaffold.write_camp(info)
        cycle_path = scaffold.write_cycle(
            info.camp_id, cycle_id, cycle, args.candidate, args.party, args.incumbent
        )
    except scaffold.ScaffoldError as exc:
        print(f"캠프를 만들 수 없다: {exc}", file=sys.stderr)
        return 1

    print(f"{camp_path}")
    print(f"{cycle_path}/")
    print("  election.yaml · candidates.yaml · compliance.review.yaml")
    print("  records/ · rejected/ · incoming/")
    print(f"관할 행정동 {len(codes)}개" + (f" · 프리셋 {preset}" if preset else ""))
    if cycle.election.date is None:
        print(
            "[주의] 선거일이 비어 있다. "
            "기간에 의존하는 컴플라이언스 판정이 전부 unreviewed 로 떨어진다"
        )
    print(f"다음: uv run votelink camp show {info.camp_id}")
    return 0


def cmd_camp_list(args: argparse.Namespace) -> int:
    camps = camp.list_camps()
    if not camps:
        print("등록된 캠프가 없다. `uv run votelink camp new <id> ...` 로 만든다")
        return 0
    for camp_id in camps:
        try:
            info = camp.load_camp(camp_id)
        except (camp.CampConfigError, ValidationError) as exc:
            print(f"{camp_id:<24} [설정 오류] {exc}", file=sys.stderr)
            continue
        cycles = camp.list_cycles(camp_id)
        print(f"{camp_id:<24} {info.candidate_name:<10} 주기 {len(cycles)}개")
        for cycle_id in cycles:
            print(f"    {cycle_id}")
    return 0


def cmd_camp_show(args: argparse.Namespace) -> int:
    cycle_id = args.cycle_id
    if cycle_id is None:
        cycles = camp.list_cycles(args.camp_id)
        if not cycles:
            print(f"캠프 '{args.camp_id}' 에 선거 주기가 없다", file=sys.stderr)
            return 1
        cycle_id = cycles[-1]

    try:
        info = camp.load_camp(args.camp_id)
        cycle = camp.load_cycle(args.camp_id, cycle_id)
        roster = camp.load_roster(args.camp_id, cycle_id)
    except (
        camp.CampNotFound,
        camp.CycleNotFound,
        camp.CampConfigError,
        FileNotFoundError,
        ValidationError,
    ) as exc:
        print(f"캠프 설정을 읽을 수 없다: {exc}", file=sys.stderr)
        return 1

    e = cycle.election
    print(f"{info.camp_id} · {info.candidate_name} (생성 {info.created_at})")
    print(f"  주기      {cycle_id}")
    print(f"  선거      {e.type.value} / {e.office.value} / {e.date or '미정'}")
    print(f"  진영      {cycle.lineage.value}  ← 렌즈")
    preset = f" (프리셋 {cycle.territory.preset})" if cycle.territory.preset else ""
    print(f"  관할      행정동 {len(cycle.territory.emd_codes)}개{preset}")
    print(f"  법률검토  {cycle.legal_reviewer or '미정'}")
    print(f"  우리      {roster.ours.name} ({roster.ours.party}, {roster.ours.lineage.value})")
    if roster.opponents:
        for o in roster.opponents:
            mark = " · 현역" if o.incumbent else ""
            print(f"  상대      {o.name} ({o.party}, {o.lineage.value}{mark})")
    else:
        print("  상대      아직 없음 — candidates.yaml 의 opponents 를 채운다")
    space = camp.space_for(args.camp_id, cycle_id)
    print(f"  공간      공용 {space.root} + 캠프 {space.camp_root}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """로컬 웹앱(L3)을 띄운다.

    `fastapi`·`uvicorn` 을 **여기서 늦게 import 한다.** 모듈 최상단에서 부르면 웹
    의존성이 없는 환경에서 `collect`·`analyze` 까지 같이 죽는다.
    """
    try:
        import uvicorn

        from votelink.web.app import create_app
        from votelink.web.lens import load_lens
    except ImportError as exc:
        print(f"웹 의존성이 없다 ({exc}). `uv sync` 를 먼저 실행하라", file=sys.stderr)
        return 1

    settings = WebSettings(
        district_id=args.district,
        host=args.host,
        port=args.port,
        camp_id=args.camp,
        cycle_id=args.cycle,
    )

    # 기동 전 점검. 여기서 걸리는 것은 전부 사용자가 고칠 일이라 트레이스백을 보여주지 않는다.
    try:
        compliance.load_policy(settings.policy_path)
        table = districts.load_districts(settings.districts_path)
    except FileNotFoundError as exc:
        print(f"참조 데이터가 없다: {exc}", file=sys.stderr)
        return 1

    # 렌즈를 기동 전에 읽어 본다. 관할이 틀린 채로 화면을 그리면 조용히 다른 답을
    # 보여주므로(P-001 §16), 여기서 걸러 트레이스백 없이 알린다.
    if args.camp:
        try:
            lens = load_lens(args.camp, args.cycle, settings.camps_root, settings.districts_path)
        except (
            camp.CampNotFound,
            camp.CycleNotFound,
            camp.CampConfigError,
            FileNotFoundError,
            ValidationError,
        ) as exc:
            print(f"캠프 설정을 읽을 수 없다: {exc}", file=sys.stderr)
            return 1
        print(
            f"렌즈: {lens.label} · {lens.lineage.value} 진영 · "
            f"관할 {len(lens.territory)}개 동 ({lens.cycle_id})"
        )

    # --district 를 줬으면 그 하나만, 아니면 정의된 선거구를 전부 점검한다. 선거구가
    # 여럿이어도 죽이지 않는다 — 웹앱의 `/` 가 선거구 선택 화면을 띄운다.
    to_check = [args.district] if args.district else list(table)
    try:
        for did in to_check:
            profiles = load_profiles(settings, did)
            diag = profiles.diagnostics
            if profiles.profiles:
                print(f"{profiles.district.name} · 행정동 {diag.loaded}/{diag.expected}")
            else:
                cmd = f"uv run votelink analyze voter_profile --district {profiles.district.id}"
                print(
                    f"[주의] {profiles.district.name}: 표시할 분석 결과가 0건이다. "
                    f"`{cmd}` 를 먼저 돌려라"
                )
    except (AmbiguousDistrict, districts.DistrictNotFound) as exc:
        print(f"선거구를 정할 수 없다: {exc}", file=sys.stderr)
        return 1

    print(f"http://{args.host}:{args.port}")
    uvicorn.run(create_app(settings), host=args.host, port=args.port, log_level="warning")
    return 0


# --- 파서 ----------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="votelink", description="선거 전략 지원 시스템")
    parser.add_argument("-v", "--verbose", action="store_true", help="디버그 로그")
    sub = parser.add_subparsers(dest="command", required=True)

    p_collect = sub.add_parser("collect", help="수집기 실행")
    p_collect.add_argument("collector_id")
    g_collect = p_collect.add_mutually_exclusive_group()
    g_collect.add_argument(
        "--district",
        help="어느 선거구로 수집할지. 생략하면 meta.yaml 의 config.default_district",
    )
    g_collect.add_argument(
        "--all-districts",
        action="store_true",
        help="meta.yaml 의 config.districts 에 등록된 모든 선거구를 차례로 수집한다",
    )
    p_collect.add_argument("--since", help="ISO 8601. 증분 수집 시작 시점")
    p_collect.add_argument("--dry-run", action="store_true", help="저장 없이 계약 검증만")
    p_collect.add_argument(
        "--reparse", action="store_true", help="네트워크 없이 저장된 raw 만 재파싱"
    )
    p_collect.add_argument(
        "--capture-fixture",
        action="store_true",
        help="첫 배치의 실제 응답을 tests/fixtures/sample_raw.json 에 저장하고 끝낸다",
    )
    p_collect.set_defaults(func=cmd_collect)

    p_reg = sub.add_parser("registry", help="수집기 등록부")
    reg_sub = p_reg.add_subparsers(dest="registry_command", required=True)
    reg_sub.add_parser("sync", help="registry.yaml 재생성").set_defaults(func=cmd_registry_sync)
    reg_sub.add_parser("list", help="등록된 수집기 목록").set_defaults(func=cmd_registry_list)

    p_geo = sub.add_parser("geo", help="행정동코드 매핑표")
    geo_sub = p_geo.add_subparsers(dest="geo_command", required=True)
    p_import = geo_sub.add_parser("import", help="공식 행정동코드 파일 가져오기")
    p_import.add_argument("source", help="CSV 경로")
    p_import.add_argument("--system", default="mois", help="출처 체계 이름 (mois/kosis/nec)")
    p_import.add_argument("--code-col")
    p_import.add_argument("--name-col")
    p_import.add_argument("--encoding", default="utf-8-sig")
    p_import.add_argument("--append", action="store_true", help="기존 매핑표에 덧붙인다")
    p_import.set_defaults(func=cmd_geo_import)
    p_lookup = geo_sub.add_parser("lookup", help="변환 시험")
    p_lookup.add_argument("value")
    p_lookup.add_argument("--system")
    p_lookup.set_defaults(func=cmd_geo_lookup)

    p_district = sub.add_parser("district", help="선거구 정의")
    d_sub = p_district.add_subparsers(dest="district_command", required=True)
    p_dlist = d_sub.add_parser("list", help="정의된 선거구와 행정동")
    p_dlist.add_argument("--emd", dest="verbose_emd", action="store_true", help="행정동까지 출력")
    p_dlist.set_defaults(func=cmd_district_list)
    p_dfill = d_sub.add_parser(
        "backfill-codes",
        help="mois_population raw 응답의 admmCd 로 emd[].code 를 채운다 (D-001)",
    )
    p_dfill.add_argument("--district", help="이 선거구만. 생략하면 pending 인 모든 선거구")
    p_dfill.add_argument(
        "--dry-run", action="store_true", help="파일을 고치지 않고 무엇이 채워질지만 출력"
    )
    p_dfill.set_defaults(func=cmd_district_backfill)

    p_analyze = sub.add_parser("analyze", help="분석기 실행 (L2)")
    p_analyze.add_argument("analyzer_id", nargs="?", help="생략하면 등록된 분석기 목록")
    g_analyze = p_analyze.add_mutually_exclusive_group()
    g_analyze.add_argument(
        "--district",
        help="어느 선거구로 분석할지. 생략하면 meta.yaml 의 config.default_district",
    )
    g_analyze.add_argument(
        "--all-districts",
        action="store_true",
        help="meta.yaml 의 config.districts 에 등록된 모든 선거구를 차례로 분석한다",
    )
    g_analyze.add_argument(
        "--all",
        action="store_true",
        help=(
            "등록된 모든 분석기를 각자의 config.districts 전체 선거구로 돌린다. "
            "입력 kind 는 한 번만 읽어 공유한다 (analyzer_id 생략)"
        ),
    )
    p_analyze.add_argument("--dry-run", action="store_true", help="저장 없이 계약 검증만")
    p_analyze.add_argument("--sync", action="store_true", help="analyzers/registry.yaml 재생성")
    p_analyze.set_defaults(func=cmd_analyze)

    p_acct = sub.add_parser("account", help="계정·세션·승인 (P-002 control plane)")
    a_sub = p_acct.add_subparsers(dest="account_command", required=True)

    p_op = a_sub.add_parser("create-operator", help="운영자 계정 생성 (웹에 가입 폼이 없다)")
    p_op.add_argument("email")
    p_op.add_argument("password")
    p_op.set_defaults(func=cmd_account_create_operator)

    a_sub.add_parser("list", help="계정 목록과 활성 세션 수").set_defaults(func=cmd_account_list)
    a_sub.add_parser("signups", help="승인 대기 큐").set_defaults(func=cmd_account_signups)

    p_ok = a_sub.add_parser("approve", help="가입 신청 승인 → 캠프 공간 생성")
    p_ok.add_argument("request_id", type=int)
    p_ok.add_argument("--operator", type=int, required=True, help="승인하는 운영자 계정 id")
    p_ok.add_argument("--camp-id", help="생략하면 이메일에서 만든다")
    p_ok.add_argument("--note", help="판단 근거")
    p_ok.set_defaults(func=cmd_account_approve)

    p_no = a_sub.add_parser("reject", help="가입 신청 거절 (사유 필수)")
    p_no.add_argument("request_id", type=int)
    p_no.add_argument("--operator", type=int, required=True)
    p_no.add_argument("--note", required=True, help="거절 사유. 신청자가 무엇을 고칠지 알아야 한다")
    p_no.set_defaults(func=cmd_account_reject)

    p_lo = a_sub.add_parser("logout", help="그 계정의 세션을 전부 끊는다")
    p_lo.add_argument("account_id", type=int)
    p_lo.set_defaults(func=cmd_account_logout)

    p_pw = a_sub.add_parser("passwd", help="임시 비밀번호 발급 (기존 세션도 끊는다)")
    p_pw.add_argument("account_id", type=int)
    p_pw.add_argument("password")
    p_pw.set_defaults(func=cmd_account_passwd)

    p_camp = sub.add_parser("camp", help="캠프 공간 (P-001)")
    c_sub = p_camp.add_subparsers(dest="camp_command", required=True)

    p_cnew = c_sub.add_parser("new", help="캠프와 첫 선거 주기를 만든다 (온보딩)")
    p_cnew.add_argument("camp_id", help="캠프 id. 경로가 되므로 소문자·숫자·하이픈만")
    p_cnew.add_argument("--candidate", required=True, help="우리 후보 이름")
    p_cnew.add_argument("--party", required=True, help="우리 후보 정당")
    p_cnew.add_argument(
        "--type",
        required=True,
        choices=[e.value for e in ElectionType],
        help="선거 계열. 레코드의 election_type 과 같은 값이어야 렌즈가 동작한다",
    )
    p_cnew.add_argument(
        "--office", required=True, choices=[o.value for o in Office], help="노리는 직위"
    )
    p_cnew.add_argument(
        "--lineage",
        required=True,
        choices=[c.value for c in Camp],
        help="우리 진영. party_lineage.yaml 의 4축과 같은 값",
    )
    p_cnew.add_argument("--date", help="선거일 YYYY-MM-DD. 모르면 생략하고 --cycle 을 준다")
    p_cnew.add_argument("--cycle", help="주기 이름. 생략하면 선거일+계열로 만든다")
    p_cnew.add_argument("--preset", help="관할을 채울 선거구 id (districts.yaml)")
    p_cnew.add_argument(
        "--sigungu", help="관할을 채울 자치구 이름. 구청장처럼 선거구 여럿을 아울러야 할 때"
    )
    p_cnew.add_argument(
        "--emd", action="append", default=[], help="관할 행정동코드 직접 지정 (반복 가능)"
    )
    p_cnew.add_argument("--incumbent", action="store_true", help="우리 후보가 현역인가")
    p_cnew.add_argument("--reviewer", help="법률 검토자")
    p_cnew.set_defaults(func=cmd_camp_new)

    p_clist = c_sub.add_parser("list", help="캠프와 선거 주기 목록")
    p_clist.set_defaults(func=cmd_camp_list)

    p_cshow = c_sub.add_parser("show", help="한 주기의 설정을 확인한다 (관할 검증 포함)")
    p_cshow.add_argument("camp_id")
    p_cshow.add_argument("cycle_id", nargs="?", help="생략하면 가장 최근 주기")
    p_cshow.set_defaults(func=cmd_camp_show)

    p_serve = sub.add_parser("serve", help="로컬 웹앱 (L3)")
    p_serve.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=(
            f"기본 {DEFAULT_HOST}. 0.0.0.0 으로 열면 미검토 산출물이 뜨는 화면이 "
            "LAN 에 공개되고, 그건 의도치 않은 공표가 된다"
        ),
    )
    p_serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    p_serve.add_argument(
        "--district",
        help=(
            "기본으로 열 선거구. 생략하면 `/` 가 선거구 선택 화면을 띄운다 "
            "(선거구가 하나뿐이면 그리로 바로 이동)"
        ),
    )
    p_serve.add_argument(
        "--camp",
        help=(
            "이 캠프의 관점으로 본다 (렌즈). 생략하면 진영 중립으로 그린다 — "
            "숫자는 어느 쪽이든 같고 읽는 방식만 달라진다"
        ),
    )
    p_serve.add_argument("--cycle", help="선거 주기. 생략하면 그 캠프의 가장 최근 주기")
    p_serve.set_defaults(func=cmd_serve)

    return parser


REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_env() -> None:
    """`.env` 를 읽어 이미 export 된 값은 덮어쓰지 않고 채워 넣는다.

    매번 `export DATA_GO_KR_SERVICE_KEY=...` 하지 않아도 되게 하는 통로다.
    `encoding="utf-8-sig"` 는 BOM 이 붙은 `.env`(메모장 등으로 저장한 경우)도
    첫 변수명이 깨지지 않게 한다.
    """
    load_dotenv(REPO_ROOT / ".env", encoding="utf-8-sig", override=False)


def main(argv: list[str] | None = None) -> int:
    _load_env()
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
