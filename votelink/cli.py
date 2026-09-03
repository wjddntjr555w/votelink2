"""votelink 명령줄 도구."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from votelink.analyze import registry as analyze_registry
from votelink.analyze import runner as analyze_runner
from votelink.analyze.base import AnalyzeError
from votelink.collect import geo, registry, runner
from votelink.collect.http import FetchError
from votelink.contract.models import GEO_CODE_DIGITS, KST
from votelink.reference import compliance, districts
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
    collector = registry.load(args.collector_id)

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


def cmd_analyze(args: argparse.Namespace) -> int:
    if args.sync:
        path = analyze_registry.sync()
        metas = analyze_registry.discover()
        print(f"{path} 갱신 · 분석기 {len(metas)}개")
        return 0

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

    analyzer = analyze_registry.load(args.analyzer_id)
    if not analyzer.meta.verified:
        print(
            f"[주의] {analyzer.id} 는 실제 입력으로 검증되지 않았다 (meta.verified=false). "
            "산출물을 신뢰하기 전에 테스트를 통과시키고 verified 를 올려라"
        )
    try:
        report = analyze_runner.run(analyzer, dry_run=args.dry_run)
    except AnalyzeError as exc:
        # 참조 데이터 결손 같은 것은 사용자가 고칠 일이다. 트레이스백을 보여줄 이유가 없다.
        print(f"분석 실패: {exc}", file=sys.stderr)
        return 1
    print(report.summary())
    if args.dry_run:
        print("(dry-run: 아무것도 저장하지 않았다)")
    return 1 if report.failed else 0


def cmd_serve(args: argparse.Namespace) -> int:
    """로컬 웹앱(L3)을 띄운다.

    `fastapi`·`uvicorn` 을 **여기서 늦게 import 한다.** 모듈 최상단에서 부르면 웹
    의존성이 없는 환경에서 `collect`·`analyze` 까지 같이 죽는다.
    """
    try:
        import uvicorn

        from votelink.web.app import create_app
    except ImportError as exc:
        print(f"웹 의존성이 없다 ({exc}). `uv sync` 를 먼저 실행하라", file=sys.stderr)
        return 1

    settings = WebSettings(district_id=args.district, host=args.host, port=args.port)

    # 기동 전 점검. 여기서 걸리는 것은 전부 사용자가 고칠 일이라 트레이스백을 보여주지 않는다.
    try:
        profiles = load_profiles(settings)
        compliance.load_policy(settings.policy_path)
    except (AmbiguousDistrict, districts.DistrictNotFound) as exc:
        print(f"선거구를 정할 수 없다: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"참조 데이터가 없다: {exc}", file=sys.stderr)
        return 1

    if profiles.profiles:
        diag = profiles.diagnostics
        print(f"{profiles.district.name} · 행정동 {diag.loaded}/{diag.expected}")
    else:
        # 실패로 처리하지 않는다. 서버가 안 뜨면 *왜* 비었는지 볼 화면조차 없다.
        print(
            "[주의] 표시할 분석 결과가 0건이다. "
            "`uv run votelink analyze voter_profile` 을 먼저 돌려라"
        )

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

    p_analyze = sub.add_parser("analyze", help="분석기 실행 (L2)")
    p_analyze.add_argument("analyzer_id", nargs="?", help="생략하면 등록된 분석기 목록")
    p_analyze.add_argument("--dry-run", action="store_true", help="저장 없이 계약 검증만")
    p_analyze.add_argument("--sync", action="store_true", help="analyzers/registry.yaml 재생성")
    p_analyze.set_defaults(func=cmd_analyze)

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
    p_serve.add_argument("--district", help="districts.yaml 에 선거구가 둘 이상일 때 필요")
    p_serve.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
