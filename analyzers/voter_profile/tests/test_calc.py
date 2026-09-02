"""순수 계산 검증. 여기 있는 함수는 레코드도 파일도 모른다."""

import pytest

from votelink.contract.enums import AgeBand, Camp, Trend

from ..calc import CampTally, age_mix_of, classify_trend, slope, swing_of


def tally(**votes: int) -> CampTally:
    t = CampTally()
    for name, v in votes.items():
        t.add(Camp(name), v)
    return t


class TestCampTally:
    def test_share_uses_valid_votes_as_denominator(self):
        """분모는 유효투표수다. 선거인수로 나누면 투표율 변화가 성향 변화로 오독된다."""
        t = tally(conservative=60, progressive=40)
        share = t.share()
        assert share[Camp.CONSERVATIVE] == pytest.approx(60.0)
        assert share[Camp.PROGRESSIVE] == pytest.approx(40.0)
        assert sum(share.values()) == pytest.approx(100.0)

    def test_share_always_has_every_camp(self):
        """득표가 없는 진영도 0.0 으로 나온다 — payload 계약이 모든 키를 요구한다."""
        assert set(tally(conservative=10).share()) == set(Camp)

    def test_merge_is_weighted_not_averaged(self):
        """지역구 평균은 동별 단순평균이 아니라 득표 합/유효표 합이다.

        인구가 다른 동을 같은 무게로 세면 작은 동이 과대대표된다.
        """
        big = tally(conservative=900, progressive=100)  # 90%, 1000표
        small = tally(conservative=0, progressive=100)  # 0%, 100표
        big.merge(small)
        # 단순평균이면 45%. 가중이면 900/1100 = 81.8%.
        assert big.conservative_pct == pytest.approx(81.818, abs=0.01)

    def test_zero_valid_votes_is_an_error(self):
        with pytest.raises(ValueError, match="유효투표수가 0"):
            CampTally().share()


class TestSlope:
    def test_flat_series_has_zero_slope(self):
        assert slope([5.0, 5.0, 5.0]) == pytest.approx(0.0)

    def test_rising_series(self):
        assert slope([0.0, 1.0, 2.0]) == pytest.approx(1.0)

    def test_single_point_is_an_error(self):
        with pytest.raises(ValueError, match="2개 이상"):
            slope([1.0])


class TestClassifyTrend:
    """**절대 득표율이 아니라 지역구 편차**를 받는다는 것이 이 함수의 요점이다."""

    def test_uses_only_the_window(self):
        """33년 전 구도가 최근 추세에 섞이지 않는다."""
        # 앞 5회는 급락, 최근 3회는 상승. window=3 이면 상승으로 읽어야 한다.
        gaps = [50.0, 40.0, 30.0, 20.0, 10.0, 0.0, 1.0, 2.0]
        assert classify_trend(gaps, threshold=0.3, window=3) is Trend.CONSERVATIVE_SHIFT

    def test_threshold_creates_a_stable_band(self):
        gaps = [0.0, 0.1, 0.2]  # 기울기 0.1 < 0.3
        assert classify_trend(gaps, threshold=0.3, window=3) is Trend.STABLE

    def test_negative_slope_is_progressive_shift(self):
        gaps = [2.0, 1.0, 0.0]
        assert classify_trend(gaps, threshold=0.3, window=3) is Trend.PROGRESSIVE_SHIFT

    def test_too_few_points_is_stable_not_an_error(self):
        """선거가 한 번뿐인 동을 격리하지 않는다 — 추세를 모를 뿐이다."""
        assert classify_trend([1.0], threshold=0.3, window=3) is Trend.STABLE


class TestSwing:
    def test_swing_is_amplitude(self):
        assert swing_of([30.0, 60.0, 45.0]) == pytest.approx(30.0)

    def test_empty_series_is_an_error(self):
        with pytest.raises(ValueError, match="빈 시계열"):
            swing_of([])


class TestAgeMix:
    def test_percentages_sum_to_100_and_cover_every_band(self):
        breakdown = [
            {"age_band": "20-29", "sex": "M", "count": 100},
            {"age_band": "20-29", "sex": "F", "count": 100},
            {"age_band": "80+", "sex": "F", "count": 200},
        ]
        mix, sex_ratio, total = age_mix_of(breakdown)
        assert set(mix) == set(AgeBand)  # 출처가 빼먹은 구간도 0.0 으로 채운다
        assert sum(mix.values()) == pytest.approx(100.0)
        assert mix[AgeBand.A20_29] == pytest.approx(50.0)
        assert mix[AgeBand.A80_PLUS] == pytest.approx(50.0)
        assert mix[AgeBand.A30_39] == 0.0
        assert total == 400
        assert sex_ratio == pytest.approx(100 / 300)

    def test_zero_population_is_an_error(self):
        with pytest.raises(ValueError, match="총원이 0"):
            age_mix_of([{"age_band": "20-29", "sex": "M", "count": 0}])

    def test_zero_women_does_not_divide_by_zero(self):
        with pytest.raises(ValueError, match="성비"):
            age_mix_of([{"age_band": "20-29", "sex": "M", "count": 10}])
