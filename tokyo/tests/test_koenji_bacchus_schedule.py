"""Offline check for the Koenji Theater Bacchus schedule parser.

Bacchus publishes one flat text block on its front page rather than per-film
article pages, so the parser is pure text-shape logic. This locks in the four
shapes that block actually uses:

  * "◆M/D（曜）" day header followed by "Part N  hh:mm / hh:mm" lines
  * a "●" header whose own date is the only date ("● 9月11日（金）")
  * dated showtime lines under a multi-day "●" header ("9月24・25日")
  * a "●" header that states the time before the title line

Run: python -m pytest tokyo/tests/test_koenji_bacchus_schedule.py
 or: python tokyo/tests/test_koenji_bacchus_schedule.py
"""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cinema_modules.koenji_bacchus_module import _normalize, _parse_schedule  # noqa: E402

# Trimmed verbatim from https://bacchus-tokyo.com/ (fetched 2026-09-08).
SAMPLE = """● 9月7日（月）～
『トレンケ・ラウケン』Part1 & Part2（2022年）
監督・脚本：ラウラ・シタレラ
http://trenquelauquen.eurospace.co.jp/
＜料金＞
￥2000
障がい者手帳をお持ちの方￥1000
◆9/7（月）
Part 1　11:00 / 19:00
Part 2　16:00
◆9/8（火）
Part 2　11:00 / 19:00
Part 1　16:00
● 9月11日（金）
【初上映】映画『メクボリアン』
➀12：00~　➁15:30~　➂17:30~　➃19:30~
https://peatix.com/event/5130387
● 9月24・25日（木・金）
活弁シネマライブ
『裁かるるジャンヌ』
9月24日（木）14：00 / 19：00
9月25日（金）14：00 / 19：00
料金：一般 3000円　学生・障害者手帳をお持ちの方 2000円
● 9月28日（月）～
『名もなき歌』（2019年）
メリーナ・レオン 第一回監督作品
● 9月28日（月）19：00～
上映会・交流会
『Bunka-ブンカ』（2025）
監督 オマール・ヤング
"""

TODAY = dt.date(2026, 9, 8)


def parsed():
    return _parse_schedule([_normalize(line) for line in SAMPLE.splitlines()], TODAY)


def test_parses_the_four_schedule_shapes():
    rows = set(parsed())

    # Day header + part label inherits the programme title.
    assert (dt.date(2026, 9, 8), "11:00", "トレンケ・ラウケン Part 2") in rows
    assert (dt.date(2026, 9, 8), "16:00", "トレンケ・ラウケン Part 1") in rows

    # Times on a "●" header block with no "◆" day line, circled numerals dropped.
    assert (dt.date(2026, 9, 11), "12:00", "メクボリアン") in rows
    assert (dt.date(2026, 9, 11), "19:30", "メクボリアン") in rows

    # Showtime lines carrying their own date beat the block's date list.
    assert (dt.date(2026, 9, 24), "14:00", "裁かるるジャンヌ") in rows
    assert (dt.date(2026, 9, 25), "19:00", "裁かるるジャンヌ") in rows

    # "● 9月28日（月）19：00～" states the time two lines before the title.
    assert (dt.date(2026, 9, 28), "19:00", "Bunka-ブンカ") in rows


def test_drops_past_dates_prices_and_untimed_programmes():
    rows = parsed()

    assert all(date_value >= TODAY for date_value, _, _ in rows)
    # 9/7 is in the past relative to TODAY and must not survive.
    assert not [row for row in rows if row[0] == dt.date(2026, 9, 7)]
    # "『名もなき歌』" has no published times yet.
    assert not [row for row in rows if "名もなき歌" in row[2]]
    # "料金：一般 3000円" must not read as a showtime.
    assert not [row for row in rows if row[1].startswith("30")]


if __name__ == "__main__":
    test_parses_the_four_schedule_shapes()
    test_drops_past_dates_prices_and_untimed_programmes()
    print(f"ok - {len(parsed())} listings parsed")
