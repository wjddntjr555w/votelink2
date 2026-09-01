# 참조 데이터

## geo_mapping.csv — 행정동코드 매핑표

**비어 있는 채로 커밋되어 있다.** 실제 코드값은 공식 파일에서 가져와야 하며,
손으로 만들어 넣으면 안 된다 (틀린 코드는 조용히 잘못된 지역에 데이터를 붙인다).

```bash
# 행정안전부 '행정기관(행정동) 코드' CSV 를 받아서
uv run votelink geo import ~/Downloads/행정동코드.csv --system mois

# 다른 체계(선관위·통계청)는 --append 로 덧붙인다
uv run votelink geo import nec_codes.csv --system nec --append

# 확인
uv run votelink geo lookup 풍납1동
```

열 이름은 자동 탐지한다(`행정기관코드`/`행정동코드`/`adm_cd` 등).
못 찾으면 `--code-col` / `--name-col` 로 지정한다.

| 열 | 뜻 |
|---|---|
| `source_system` | 출처 체계 (`mois` / `kosis` / `nec`) |
| `source_code` | 그 체계에서의 코드 |
| `source_name` | 출처 표기 그대로 (`서울특별시 송파구 풍납1동`) |
| `emd_code` | **내부 표준** 행정동코드 8자리 |
| `emd_name` | 짧은 동명 (`풍납1동`) |
