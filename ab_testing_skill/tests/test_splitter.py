from skill.config import SplitConfig
from skill.splitter import bucket_tenure, split


def test_bucket_tenure_ranges():
    assert bucket_tenure(0.5) == "0-1"
    assert bucket_tenure(2) == "1-3"
    assert bucket_tenure(4) == "3-5"
    assert bucket_tenure(7) == "5-10"
    assert bucket_tenure(15) == "10+"
    assert bucket_tenure(None) == "unknown"


def test_split_covers_every_inn_exactly_once():
    inn_list = [str(i).zfill(10) for i in range(200)]
    grouping = {"opf": {inn: "OOO" if i % 2 == 0 else "AO" for i, inn in enumerate(inn_list)}}
    financial = {}
    result = split(inn_list, grouping, financial, SplitConfig(target_ratio=0.5, random_seed=1))

    assert sorted(result.control + result.target) == sorted(inn_list)
    assert set(result.control).isdisjoint(result.target)
    assert result.balanced  # no financial metrics => trivially balanced


def test_split_is_roughly_50_50_on_large_uniform_population():
    inn_list = [str(i).zfill(10) for i in range(1000)]
    grouping = {"opf": {inn: "OOO" for inn in inn_list}}
    result = split(inn_list, grouping, {}, SplitConfig(target_ratio=0.5, random_seed=7))
    assert abs(len(result.control) - len(result.target)) <= 2


def test_split_reshuffles_until_financial_balance_achieved():
    inn_list = [str(i).zfill(10) for i in range(300)]
    grouping = {"opf": {inn: "OOO" for inn in inn_list}}
    # make value strongly correlated with index parity so a "bad" first split is plausible,
    # but the reshuffle loop should still find a balanced assignment eventually.
    financial = {"chod": {inn: 100.0 + (i % 5) for i, inn in enumerate(inn_list)}}
    config = SplitConfig(target_ratio=0.5, random_seed=3, max_standardized_diff=0.10, max_reshuffle_attempts=50)
    result = split(inn_list, grouping, financial, config)
    assert result.balanced
    assert result.balance_report["chod"]["smd"] <= 0.10


def test_split_respects_custom_ratio():
    inn_list = [str(i).zfill(10) for i in range(400)]
    grouping = {"opf": {inn: "OOO" for inn in inn_list}}
    result = split(inn_list, grouping, {}, SplitConfig(target_ratio=0.2, random_seed=5))
    assert 60 <= len(result.target) <= 100
