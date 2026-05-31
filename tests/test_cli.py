from stocktracker.cli import build_parser


def test_check_defaults_to_respecting_market_hours():
    args = build_parser().parse_args(["check"])
    assert args.ignore_market_hours is False


def test_check_short_flag_sets_ignore():
    args = build_parser().parse_args(["check", "-i"])
    assert args.ignore_market_hours is True


def test_check_long_flag_sets_ignore():
    args = build_parser().parse_args(["check", "--ignore-market-hours"])
    assert args.ignore_market_hours is True
