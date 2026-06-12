# Shared helpers for venue scrapers
import re
from datetime import date
from urllib.parse import urljoin

MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
MONTH_MAP = {m: i for i, m in enumerate(MONTHS.split("|"), 1)}

# e.g. "25 July 2025 – 5 July 2026" or "13 February–31 May 2026" or "22 November 2025 – 4 May 2026"
DATE_RANGE_RE = re.compile(
    r"(\d{1,2})\s+(" + MONTHS + r")\s+(\d{4})\s*[–\-]\s*(\d{1,2})\s+(" + MONTHS + r")\s+(\d{4})",
    re.IGNORECASE
)
# e.g. "28 March – 6 September 2026" or "13 February–31 May 2026" (year only at end)
HALF_RANGE_RE = re.compile(
    r"(\d{1,2})\s+(" + MONTHS + r")\s*[–\-]\s*(\d{1,2})\s+(" + MONTHS + r")\s+(\d{4})",
    re.IGNORECASE
)
# e.g. "26 February 2026 – August 2026" (end month without a day = end of month)
MONTH_END_RANGE_RE = re.compile(
    r"(\d{1,2})\s+(" + MONTHS + r")\s+(\d{4})\s*[–\-]\s*(" + MONTHS + r")\s+(\d{4})",
    re.IGNORECASE
)
# Single date e.g. "14 March 2026"
SINGLE_DATE_RE = re.compile(r"(\d{1,2})\s+(" + MONTHS + r")\s+(\d{4})", re.IGNORECASE)
# "February 7, 2023" or "March 14, 2025 - March 15, 2026"
MONTH_FIRST_RE = re.compile(
    r"(" + MONTHS + r")\s+(\d{1,2}),?\s+(\d{4})\s*[–\-]\s*(" + MONTHS + r")\s+(\d{1,2}),?\s+(\d{4})",
    re.IGNORECASE
)
MONTH_FIRST_SINGLE_RE = re.compile(r"(" + MONTHS + r")\s+(\d{1,2}),?\s+(\d{4})", re.IGNORECASE)


# Text that suggests a single date is an event (e.g. "Every Tuesday"), not an exhibition run
_EVENT_HINT_RE = re.compile(
    r"every\s+(tuesday|wednesday|thursday|friday|saturday|sunday)|book your|guided tour|lecture|performance|workshop|teacher cpd|family-friendly|artist in conversation|part of .+ part of|starts? at \d|tours? start",
    re.IGNORECASE
)


def parse_date_range(text):
    """Parse date range from text. Returns (start_date_str, end_date_str) or (None, None)."""
    if not text:
        return None, None
    text = re.sub(r"\s+", " ", text.strip())
    m = DATE_RANGE_RE.search(text)
    if m:
        d1, mo1, y1, d2, mo2, y2 = m.groups()
        try:
            start = date(int(y1), MONTH_MAP[mo1.capitalize()], int(d1))
            end = date(int(y2), MONTH_MAP[mo2.capitalize()], int(d2))
            return start.isoformat(), end.isoformat()
        except (ValueError, KeyError):
            pass
    m = HALF_RANGE_RE.search(text)
    if m:
        d1, mo1, d2, mo2, y = m.groups()
        try:
            m1, m2 = MONTH_MAP[mo1.capitalize()], MONTH_MAP[mo2.capitalize()]
            year = int(y)
            start_year = year if m1 <= m2 else year - 1
            start = date(start_year, m1, int(d1))
            end = date(year, m2, int(d2))
            if start <= end:
                return start.isoformat(), end.isoformat()
        except (ValueError, KeyError):
            pass
    m = MONTH_END_RANGE_RE.search(text)
    if m:
        import calendar
        d1, mo1, y1, mo2, y2 = m.groups()
        try:
            start = date(int(y1), MONTH_MAP[mo1.capitalize()], int(d1))
            end_month = MONTH_MAP[mo2.capitalize()]
            end = date(int(y2), end_month, calendar.monthrange(int(y2), end_month)[1])
            if start <= end:
                return start.isoformat(), end.isoformat()
        except (ValueError, KeyError):
            pass
    m = SINGLE_DATE_RE.search(text)
    if m:
        if _EVENT_HINT_RE.search(text):
            return None, None
        d, mo, y = m.groups()
        try:
            single = date(int(y), MONTH_MAP[mo.capitalize()], int(d))
            return single.isoformat(), single.isoformat()
        except (ValueError, KeyError):
            pass
    m = MONTH_FIRST_RE.search(text)
    if m:
        mo1, d1, y1, mo2, d2, y2 = m.groups()
        try:
            start = date(int(y1), MONTH_MAP[mo1.capitalize()], int(d1))
            end = date(int(y2), MONTH_MAP[mo2.capitalize()], int(d2))
            return start.isoformat(), end.isoformat()
        except (ValueError, KeyError):
            pass
    m = MONTH_FIRST_SINGLE_RE.search(text)
    if m:
        if _EVENT_HINT_RE.search(text):
            return None, None
        mo, d, y = m.groups()
        try:
            single = date(int(y), MONTH_MAP[mo.capitalize()], int(d))
            return single.isoformat(), single.isoformat()
        except (ValueError, KeyError):
            pass
    if "ongoing" in text.lower() or "permanent" in text.lower():
        today = date.today().isoformat()
        return today, None  # no end date
    return None, None


def norm(text):
    """Normalize whitespace."""
    if not text:
        return ""
    return " ".join(str(text).split()).strip()


_UK_MONTHS = {m[:3]: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], 1)}
_UK_PERMANENT_RE = re.compile(r"continuing display|now open|permanent|ongoing|daily display", re.IGNORECASE)


def _uk_one_date(text, default_year=None):
    """Parse a single 'DD Month [YYYY]' fragment to (year, month, day) or None."""
    if not text:
        return None
    text = re.sub(r"([A-Za-z])(\d{4})", r"\1 \2", text)  # repair "Nov2026" -> "Nov 2026"
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3,})\.?\s*(\d{4})?", text)
    if not m:
        return None
    month = _UK_MONTHS.get(m.group(2)[:3].lower())
    if not month:
        return None
    year = int(m.group(3)) if m.group(3) else default_year
    if not year:
        return None
    return (year, month, int(m.group(1)))


def parse_uk_date_text(text):
    """
    Parse the loose UK date phrasings museums put in card/detail text into
    (start_iso, end_iso); either may be None. Handles ranges
    ("12 Jun - 13 Sep 2026", "14 March - 15 November 2026", cross-year),
    open-ended forms ("Until 29 Nov 2026", "From 26 Feb 2026"), single dates,
    and permanent displays ("Continuing Display", "Now Open") -> (None, None).
    A trailing "| Venue" suffix is ignored.
    """
    if not text:
        return None, None
    t = " ".join(str(text).replace("\xa0", " ").split()).split("|")[0].strip()
    if not t or _UK_PERMANENT_RE.search(t):
        return None, None
    low = t.lower()
    iso = lambda p: f"{p[0]:04d}-{p[1]:02d}-{p[2]:02d}" if p else None
    if low.startswith(("until", "ends", "closes")):
        return None, iso(_uk_one_date(t))
    if low.startswith(("from", "opens")):
        return iso(_uk_one_date(t)), None
    parts = re.split(r"\s*[–—-]\s*", t, maxsplit=1)
    if len(parts) == 2:
        end = _uk_one_date(parts[1])
        start = _uk_one_date(parts[0], default_year=end[0] if end else None)
        return iso(start), iso(end)
    one = _uk_one_date(t)
    return iso(one), iso(one)


def card_text_for(anchor, max_levels=5, max_chars=600):
    """
    Walk up from an anchor to the smallest enclosing element that looks like a
    full listing card (contains a 4-digit year, i.e. date text), without
    ballooning to the whole page. Returns normalized text.
    """
    el = anchor
    best = norm(anchor.get_text(" "))
    for _ in range(max_levels):
        if re.search(r"\d{4}", best) and len(best) >= 25:
            break
        if el.parent is None:
            break
        el = el.parent
        text = norm(el.get_text(" "))
        if len(text) > max_chars:
            break
        best = text
    return best


MONTHS_ABBR = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
ABBR_MAP = {m: i for i, m in enumerate(MONTHS_ABBR.split("|"), 1)}
_DOW = r"(?:Mon|Tue|Tues|Wed|Thu|Thur|Thurs|Fri|Sat|Sun)[a-z]*\s+"
# e.g. "Fri 19 Jun - Sun 6 Sep", "Sat 6 Jun – Sun 6 Sep 2026", "19 Jun 2026 - 6 Sep 2026"
SHORT_RANGE_RE = re.compile(
    r"(?:" + _DOW + r")?(\d{1,2})\s+(" + MONTHS_ABBR + r")[a-z]*\.?,?\s*(\d{4})?\s*[–\-—]\s*"
    r"(?:" + _DOW + r")?(\d{1,2})\s+(" + MONTHS_ABBR + r")[a-z]*\.?,?\s*(\d{4})?",
    re.IGNORECASE
)


def parse_short_date_range(text, today=None):
    """
    Parse UK short date ranges like "Fri 19 Jun - Sun 6 Sep" where the year may
    be missing; infers years assuming the run ends no more than ~6 weeks in the
    past. Returns (start_date_str, end_date_str) or (None, None).
    """
    if not text:
        return None, None
    from datetime import timedelta
    today = today or date.today()
    m = SHORT_RANGE_RE.search(re.sub(r"\s+", " ", text))
    if not m:
        return None, None
    d1, mo1, y1, d2, mo2, y2 = m.groups()
    try:
        m1 = ABBR_MAP[mo1.capitalize()[:3]]
        m2 = ABBR_MAP[mo2.capitalize()[:3]]
        if y2:
            end = date(int(y2), m2, int(d2))
        else:
            end = date(today.year, m2, int(d2))
            if end < today - timedelta(days=45):
                end = date(today.year + 1, m2, int(d2))
        if y1:
            start = date(int(y1), m1, int(d1))
        else:
            start_year = end.year if (m1, int(d1)) <= (m2, int(d2)) else end.year - 1
            start = date(start_year, m1, int(d1))
        if start > end:
            return None, None
        return start.isoformat(), end.isoformat()
    except (ValueError, KeyError):
        return None, None


# "Until 24 August 2025" / "Closes 4 May 2026" / "Ends 1 June 2026" — closing date only
_UNTIL_RE = re.compile(
    r"(?:until|closes?|closing|through|ends?)\s+(?:\w+day\s+)?(\d{1,2})\s+(" + MONTHS + r")\s+(\d{4})",
    re.IGNORECASE
)


def parse_detail_dates(text):
    """
    Conservative date extraction for detail pages: only accept an explicit
    range (start != end) or an explicit "until <date>" closing date.
    Returns (start_date_str_or_None, end_date_str_or_None).
    """
    if not text:
        return None, None
    text = re.sub(r"\s+", " ", text.strip())
    m = DATE_RANGE_RE.search(text)
    if m:
        d1, mo1, y1, d2, mo2, y2 = m.groups()
        try:
            start = date(int(y1), MONTH_MAP[mo1.capitalize()], int(d1))
            end = date(int(y2), MONTH_MAP[mo2.capitalize()], int(d2))
            if start != end:
                return start.isoformat(), end.isoformat()
        except (ValueError, KeyError):
            pass
    m = HALF_RANGE_RE.search(text)
    if m:
        d1, mo1, d2, mo2, y = m.groups()
        try:
            m1, m2 = MONTH_MAP[mo1.capitalize()], MONTH_MAP[mo2.capitalize()]
            year = int(y)
            start = date(year if m1 <= m2 else year - 1, m1, int(d1))
            end = date(year, m2, int(d2))
            if start < end:
                return start.isoformat(), end.isoformat()
        except (ValueError, KeyError):
            pass
    m = _UNTIL_RE.search(text)
    if m:
        d, mo, y = m.groups()
        try:
            return None, date(int(y), MONTH_MAP[mo.capitalize()], int(d)).isoformat()
        except (ValueError, KeyError):
            pass
    return None, None


def get_page_meta(url, headers=None, timeout=15):
    """
    Fetch a page and return og:title, og:image, og:description (or fallbacks),
    plus start_date/end_date conservatively parsed from the page.
    Returns dict with keys: title, image_url, description, start_date, end_date
    (values may be None).
    """
    empty = {"title": None, "image_url": None, "description": None, "start_date": None, "end_date": None}
    try:
        import requests
        from bs4 import BeautifulSoup
        h = headers or {}
        r = requests.get(url, headers=h, timeout=timeout)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        out = dict(empty)
        # og: tags
        for meta in soup.find_all("meta", property=True):
            p = (meta.get("property") or "").lower()
            c = (meta.get("content") or "").strip()
            if p == "og:title" and c:
                out["title"] = norm(c)
            elif p == "og:image" and c:
                out["image_url"] = c if c.startswith("http") else urljoin(url, c)
            elif p == "og:description" and c:
                out["description"] = norm(c)[:1000]
        # Fallback: h1 for title
        if not out["title"]:
            h1 = soup.find("h1")
            if h1:
                out["title"] = norm(h1.get_text())
        # Dates: og:description first, then the visible text of main/article
        candidates = []
        if out["description"]:
            candidates.append(out["description"])
        main_el = soup.find("main") or soup.find("article") or soup.body
        if main_el:
            candidates.append(norm(main_el.get_text(" "))[:4000])
        for t in candidates:
            s, e = parse_detail_dates(t)
            if s or e:
                out["start_date"], out["end_date"] = s, e
                break
        return out
    except Exception:
        return dict(empty)
