"""Offline check for the CINEMA Chupki TABATA timetable parser.

Chupki publishes several `div.timetable` blocks at once - the current week, the
next week, and one-off event blocks - in two shapes, and cancels individual
slots with a red "＊10(木)〜13(日)休映" note appended inside the film's own
table cell. Reading only the first block loses most of the week; expanding
every block without reading those notes publishes screenings that do not
happen. This locks in both halves.

Run: python -m pytest tokyo/tests/test_chupki_timetable.py
 or: python tokyo/tests/test_chupki_timetable.py
"""
import datetime as dt
import sys
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cinema_modules.chupki_module import (  # noqa: E402
    _closure_days,
    _parse_movie_details,
    _parse_schedule,
)

# Trimmed verbatim from https://chupki.jpn.org/ (fetched 2026-09-08): the four
# timetable blocks the front page carried, plus the movie boxes the timetable
# titles are joined against.
SAMPLE = """
<div class="timetable">
  <h3 class="timetable__ttl">9月3日(木)〜9月8日(火)</h3>
  <table>
    <tr><th>10:00〜12:32</th><td>黒牢城</td></tr>
    <tr><th>18:30〜20:35</th><td>BLUE GIANT</td></tr>
  </table>
</div>
<div class="timetable">
  <h3 class="timetable__ttl">9月10日(木)〜9月15日(火)</h3>
  <table>
    <tr><th>10:00〜12:32</th><td>黒牢城</td></tr>
    <tr><th>16:30〜18:05</th><td>映画大好きポンポさん</td></tr>
    <tr><th>18:30〜20:35</th><td>BLUE GIANT<font color="red"><b>＊10(木)〜13(日)休映</b></font></td></tr>
  </table>
</div>
<div class="timetable">
  <h3 class="timetable__ttl">★9月11日(金)〜13日(日),16日(水)<br>「音声ガイド付き自主制作映画祭」</h3>
  <table>
    <tr><th>9月11日(金)</th><td>19:20〜21:00</td></tr>
    <tr><th>9月12日(土)</th><td>18:30〜20:10</td></tr>
    <tr><th>9月16日(水)</th><td>14:20〜16:00 ＊気にしない上映</td></tr>
  </table>
</div>
<div class="timetable">
  <h3 class="timetable__ttl"></h3>
  <table>
    <tr><th></th><td>上記は直近のスケジュールです。<br>以降の上映スケジュールは随時反映いたします。</td></tr>
  </table>
</div>
<section class="movie">
  <div class="movie__box">
    <h4 class="movie__ttl">『黒牢城』（通常版）</h4>
    <div class="movie_etc">2025年／152分／日本</div>
  </div>
  <div class="movie__box">
    <h4 class="movie__ttl">『BLUE GIANT』</h4>
    <div class="movie_etc">2023年／120分／日本</div>
  </div>
  <div class="movie__box">
    <h4 class="movie__ttl">『映画大好きポンポさん』</h4>
    <div class="movie_etc">2021年／90分／日本</div>
  </div>
  <div class="movie__box">
    <h4 class="movie__ttl">『音声ガイド付き自主制作映画祭』</h4>
    <div class="movie_etc">2026年／100分／日本</div>
  </div>
</section>
"""

TODAY = dt.date(2026, 9, 8)


def parsed():
    soup = BeautifulSoup(SAMPLE, "html.parser")
    return _parse_schedule(soup, _parse_movie_details(soup), max_days=14, today=TODAY)


def rows():
    return {(r["date_text"], r["showtime"], r["movie_title"]) for r in parsed()}


def test_every_timetable_block_is_read():
    found = rows()

    # First block, from today only - the past days of the week are dropped.
    assert ("2026-09-08", "10:00", "黒牢城") in found
    assert not [r for r in found if r[0] < "2026-09-08"]

    # Second block: it used to be invisible because only the first was parsed.
    assert ("2026-09-15", "16:30", "映画大好きポンポさん") in found

    # Event block: title comes from the header, dates from the rows.
    assert ("2026-09-11", "19:20", "音声ガイド付き自主制作映画祭") in found
    assert ("2026-09-16", "14:20", "音声ガイド付き自主制作映画祭") in found

    # The trailing prose block carries no times and must yield nothing.
    assert not [r for r in found if "スケジュール" in r[2]]


def test_the_closure_note_is_honoured_row_by_row():
    found = rows()

    # "＊10(木)〜13(日)休映" cancels this slot on 10-13 only...
    assert not [r for r in found if r[2] == "BLUE GIANT" and "2026-09-10" <= r[0] <= "2026-09-13"]
    # ...and leaves the rest of its own block standing.
    assert ("2026-09-14", "18:30", "BLUE GIANT") in found
    assert ("2026-09-15", "18:30", "BLUE GIANT") in found
    # The note must not cancel the other films in the same block.
    assert ("2026-09-10", "10:00", "黒牢城") in found

    # The note text must not leak into the title.
    assert all("休映" not in r[2] for r in found)


def test_unreadable_closure_notes_drop_rows_instead_of_publishing_them():
    assert _closure_days("BLUE GIANT ＊10(木)〜13(日)休映") == ({10, 11, 12, 13}, False)
    assert _closure_days("＊14(月)休映") == ({14}, False)
    assert _closure_days("＊9月10日〜11日休映") == ({10, 11}, False)
    # A time in the same cell is not a day number.
    assert _closure_days("18:30〜20:35 ＊12(金)休映") == ({12}, False)
    # No note at all.
    assert _closure_days("BLUE GIANT") == (set(), False)
    # Closure announced but unparseable -> caller drops the rows.
    assert _closure_days("＊都合により休映日あり") == (set(), True)


if __name__ == "__main__":
    test_every_timetable_block_is_read()
    test_the_closure_note_is_honoured_row_by_row()
    test_unreadable_closure_notes_drop_rows_instead_of_publishing_them()
    print(f"ok - {len(parsed())} listings parsed")
