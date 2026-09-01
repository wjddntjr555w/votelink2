# collectors/ — 수집기(L1)

이 디렉터리에서 작업할 때 읽을 것: `docs/20-collector-spec.md` + `docs/10-data-contract.md`.
**다른 수집기의 구현을 참고하러 읽지 않는다.** 필요하면 스킬 `new-collector` 의 템플릿을 쓴다.

- 수집기 하나 = 폴더 하나. 폴더 밖으로 코드를 흘리지 않는다.
- `fetch`는 네트워크만, `parse`는 순수 함수. 이 분리를 깨지 않는다.
- `parse` 안에서 해석(감성·분류·추정)하지 않는다. 그건 L2의 일이다.
- `geo_code` 매핑 실패는 예외를 던진다. null로 넘기지 않는다.
- HTTP는 `votelink.collect.http.polite_client` 만 사용한다.
- `registry.yaml` 은 자동 생성물. 손으로 고치지 않는다.

새 수집기 추가는 직접 하지 말고 스킬 `new-collector` 를 호출한다.
