# analyzers/ — 분석기(L2)

이 디렉터리에서 작업할 때 읽을 것: `docs/30-analysis-spec.md` + `docs/10-data-contract.md`.
**다른 분석기의 구현을 참고하러 읽지 않는다.**

- 분석기 하나 = 폴더 하나. 폴더 밖으로 코드를 흘리지 않는다.
- `load`는 디스크만, `compute`는 순수 함수. 이 분리를 깨지 않는다.
- `compute` 안에서 네트워크·LLM·난수·시계를 쓰지 않는다. 재현되지 않으면
  `derived_from` 으로 근거를 추적해도 의미가 없다.
- **`derived_from` 을 반드시 채운다.** 계산에 실제로 쓴 레코드 전부.
- `confidence` 에 1.0 을 주지 않는다. 실측이 아니라 파생이다.
- `observed_at` 은 입력이 가리키는 시점이다. 분석 실행 시각이 아니다.
- 판단이 들어가는 값(진영 분류, 임계값)은 코드가 아니라 `data/reference/` 나
  `meta.yaml` 의 `config` 에 둔다.
- `votelink/collect/` 를 import 하지 않는다. 공용 입출력은 `votelink/store.py` 다.
- `registry.yaml` 은 자동 생성물. 손으로 고치지 않는다.

새 분석기는 `docs/proposals/A-XXX-*.md` 제안서 1장에서 시작한다.
