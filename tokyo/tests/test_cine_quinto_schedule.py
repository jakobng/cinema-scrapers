"""White Cine Quinto groups nonconsecutive dates into one timetable heading."""
from datetime import date
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cinema_modules.cine_quinto_common import _expand_date_line, _parse_showtimes


def test_weekday_and_weekend_groups_do_not_fill_the_gap_between_them():
    anchor = date(2026, 10, 17)
    assert _expand_date_line("■10/16(金)・19(月)～22(木)", anchor) == [
        date(2026, 10, day) for day in (16, 19, 20, 21, 22)]
    assert _expand_date_line("■10/17(土)・18(日)", anchor) == [
        date(2026, 10, 17), date(2026, 10, 18)]
    assert _expand_date_line("10/16(金)～10/22(木)", anchor) == [
        date(2026, 10, day) for day in range(16, 23)]
    assert _expand_date_line("10/16(金)・未定", anchor) == []
    assert _expand_date_line("12/31(木)・1/1(金)", date(2026, 12, 30)) == [
        date(2026, 12, 31), date(2027, 1, 1)]
    assert _parse_showtimes("9:45-(12:18終)") == ["09:45"]
