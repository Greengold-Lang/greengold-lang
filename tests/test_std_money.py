"""std.money: minor-unit amounts, explicit rounding, no lost cents when splitting, no mixing currencies.

Spec: 16
"""
from tests.helpers import run_gg_source


def test_money_arithmetic_rounding_and_allocation(tmp_path):
    r = run_gg_source(tmp_path, """import std.money { usd, eur, jpy, parse_money, money_new, HALF_EVEN, HALF_UP, FLOOR, CEILING, TOWARD_ZERO }

fn show_all(parts: List[Money]):
    for p in parts:
        print(p.to_string().as_str())

fn main():
    total = usd(1999).times(3)
    print(total.to_string().as_str())
    print(total.scaled(825, 10000, HALF_EVEN).to_string().as_str())
    print(usd(25).scaled(1, 2, HALF_EVEN).to_string().as_str(), usd(35).scaled(1, 2, HALF_EVEN).to_string().as_str(), usd(25).scaled(1, 2, HALF_UP).to_string().as_str())
    print(usd(-25).scaled(1, 2, HALF_UP).to_string().as_str(), usd(-25).scaled(1, 2, FLOOR).to_string().as_str(), usd(-25).scaled(1, 2, CEILING).to_string().as_str(), usd(-25).scaled(1, 2, TOWARD_ZERO).to_string().as_str())
    thirds: [3]i64 = [1, 1, 1]
    split: [2]i64 = [3, 7]
    show_all(usd(100).allocate(thirds[..]))
    show_all(usd(5).allocate(split[..]))
    show_all(usd(-100).allocate(thirds[..]))
    print(jpy(1234).to_string().as_str(), money_new(-5, "KWD", 3).to_string().as_str())
    print(usd(5).plus(eur(5)).is_ok(), usd(5).plus(usd(7)).value_or_panic().to_string().as_str())
    print(parse_money("12.34", "USD", 2).value_or_panic().minor, parse_money("-0.5", "USD", 2).value_or_panic().minor, parse_money("7", "JPY", 0).value_or_panic().minor)
    print(parse_money("1.234", "USD", 2).is_ok(), parse_money("1..2", "USD", 2).is_ok(), parse_money("abc", "USD", 2).is_ok(), parse_money("", "USD", 2).is_ok())
""".replace("import std.money { usd,", "import std.money { Money, usd,"))
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == [
        "59.97 USD", "4.95 USD",
        "0.12 USD 0.18 USD 0.13 USD",
        "-0.13 USD -0.13 USD -0.12 USD -0.12 USD",
        "0.34 USD", "0.33 USD", "0.33 USD",
        "0.02 USD", "0.03 USD",
        "-0.34 USD", "-0.33 USD", "-0.33 USD",
        "1234 JPY -0.005 KWD",
        "false 0.12 USD",
        "1234 -50 7",
        "false false false false",
    ]
