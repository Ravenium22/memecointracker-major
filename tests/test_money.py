from memetracker.utils.money import parse_money


def test_parse_money_k() -> None:
    assert parse_money("$181.8k") == 181800


def test_parse_money_m() -> None:
    assert parse_money("$2.4m") == 2400000


def test_parse_money_plain() -> None:
    assert parse_money("$990") == 990

