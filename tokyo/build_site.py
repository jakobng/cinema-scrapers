#!/usr/bin/env python3
"""Build the static cinematokyo.com site from the enriched showtimes feed.

Reads the canonical, enriched ``tokyo/data/showtimes.json`` (the flat list produced
by ``main_scraper.py``) and emits a fully static, crawlable site:

  out/
    index.html              # the existing SPA, with a pre-rendered SEO block + JSON-LD
    cinema/<slug>/index.html# one page per cinema  (MovieTheater + ScreeningEvent schema)
    film/<slug>/index.html  # one page per film    (Movie + ScreeningEvent schema)
    data/showtimes.json     # copy of the full feed (SPA fallback)
    data/showtimes_slim.json# regenerated slim feed the SPA consumes
    sitemap.xml             # index + every cinema + every film page
    robots.txt
    CNAME

The slim feed is regenerated to stay byte-compatible with what the SPA expects:
``inflateSlim`` merges ``films[showing.f]`` with each showing, so the film key is
``t<tmdb_id>`` (or ``n<movie_title>`` when there is no TMDB id) and showings carry
only ``{f, cinema_name, date_text, showtime}``.

Stdlib only — no third-party deps, so it runs unchanged in CI.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import re
import shutil
import unicodedata
from collections import defaultdict
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    JST = ZoneInfo("Asia/Tokyo")
except Exception:  # pragma: no cover - zoneinfo always present on 3.9+
    JST = dt.timezone(dt.timedelta(hours=9))

TMDB_IMG = "https://image.tmdb.org/t/p"

# Film-level fields kept in the slim feed (mirrors the existing slim schema exactly).
SLIM_FILM_FIELDS = [
    "booking_url", "clean_title_jp", "detail_page_url", "director", "director_en",
    "genres", "genres_en", "movie_title", "movie_title_en", "movie_title_jp",
    "movie_title_original", "original_language", "runtime", "runtime_min",
    "synopsis", "tags", "tmdb_backdrop_path", "tmdb_id", "tmdb_overview_en",
    "tmdb_overview_jp", "tmdb_poster_path", "vote_average", "year",
]
# Extra fields we also aggregate for the rich static pages (not part of slim).
PAGE_FILM_FIELDS = SLIM_FILM_FIELDS + [
    "synopsis_en", "country", "image_url", "purchase_url",
]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def jst_today() -> str:
    return dt.datetime.now(JST).strftime("%Y-%m-%d")


def first_nonempty(values):
    for v in values:
        if v not in (None, "", [], {}):
            return v
    return None


def film_id(rec: dict) -> str:
    """Replicate the SPA's film key: t<tmdb_id> or n<movie_title>."""
    tmdb = rec.get("tmdb_id")
    if tmdb not in (None, "", 0, "0"):
        return f"t{tmdb}"
    title = (rec.get("movie_title") or rec.get("movie_title_jp") or "").strip()
    return f"n{title}"


_slug_re = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    if not text:
        return ""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return _slug_re.sub("-", ascii_text.lower()).strip("-")


def short_hash(text: str, n: int = 8) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:n]


def unique(slug: str, taken: set, fallback: str) -> str:
    slug = slug or fallback
    base = slug
    i = 2
    while slug in taken:
        slug = f"{base}-{i}"
        i += 1
    taken.add(slug)
    return slug


# Curated romaji slugs for the ~56 venues (most are Japanese-only names with no Latin
# text to slugify). Romaji sourced from the tokyo/cinema_modules/ filenames. Any cinema
# not listed here falls back to the Latin-portion slug, then a hash — so new venues
# still get a working (if uglier) URL until added here.
CINEMA_SLUG_MAP = {
    "Bunkamura ル・シネマ 渋谷宮下": "bunkamura",
    "CINEMA AMIGO": "cinema-amigo",
    "CINEMA Chupki TABATA": "cinema-chupki-tabata",
    "Cinema Neko (シネマネコ)": "cinema-neko",
    "K's Cinema (ケイズシネマ)": "ks-cinema",
    "K2 Cinema": "k2-cinema",
    "Kadokawa Cinema Yurakucho (角川シネマ有楽町)": "kadokawa-cinema-yurakucho",
    "Morc阿佐ヶ谷": "morc-asagaya",
    "Stranger (ストレンジャー)": "stranger",
    "YEBISU GARDEN CINEMA": "yebisu-garden-cinema",
    "kino cinéma新宿": "kino-cinema-shinjuku",
    "kino cinéma横浜みなとみらい": "kino-cinema-yokohama-minatomirai",
    "kino cinéma立川髙島屋S.C.館": "kino-cinema-tachikawa",
    "あつぎのえいがかんkiki": "atsugi-no-eigakan-kiki",
    "アップリンク吉祥寺": "uplink-kichijoji",
    "アンスティチュ・フランセ東京": "institut-francais-tokyo",
    "キネカ大森": "cineka-omori",
    "キネマ旬報シアター": "kinema-junpo-theater",
    "シアターギルド代官山": "theater-guild-daikanyama",
    "シアター・イメージフォーラム": "theatre-image-forum",
    "シネクイント": "cine-quinto",
    "シネコヤ": "cinekoya",
    "シネスイッチ銀座": "cine-switch-ginza",
    "シネマシティ": "cinema-city",
    "シネマブルースタジオ": "cinema-blue-studio",
    "シネマリス": "cinemaris",
    "シネマヴェーラ渋谷": "cinema-vera-shibuya",
    "シネマ・ノヴェチェント": "cinema-novecento",
    "シネマート新宿": "cinemart-shinjuku",
    "テアトル新宿": "theatre-shinjuku",
    "ヒューマントラストシネマ有楽町": "human-trust-cinema-yurakucho",
    "ヒューマントラストシネマ渋谷": "human-trust-cinema-shibuya",
    "ホワイト シネクイント": "white-cine-quinto",
    "ポレポレ東中野": "pole-pole-higashi-nakano",
    "ユーロスペース": "eurospace",
    "ラピュタ阿佐ヶ谷": "laputa-asagaya",
    "下北沢トリウッド": "shimokitazawa-tollywood",
    "下高井戸シネマ": "shimotakaido-cinema",
    "千葉劇場": "chiba-gekijo",
    "吉祥寺オデヲン": "kichijoji-odeon",
    "国立映画アーカイブ": "national-film-archive",
    "小田原シネマ館": "odawara-cinema",
    "川崎市アートセンター アルテリオ映像館": "kawasaki-art-center",
    "川越スカラ座": "kawagoe-scalaza",
    "新宿武蔵野館": "shinjuku-musashinokan",
    "新文芸坐": "shin-bungeiza",
    "早稲田松竹": "waseda-shochiku",
    "東京都写真美術館": "tokyo-photographic-art-museum",
    "東劇": "togeki",
    "横浜シネマリン": "yokohama-cinemarine",
    "横浜シネマ・ジャック＆ベティ": "yokohama-cinema-jack-and-betty",
    "池袋シネマ・ロサ": "ikebukuro-cinema-rosa",
    "深谷シネマ": "fukaya-cinema",
    "目黒シネマ": "meguro-cinema",
    "神保町シアター": "jinbocho-theater",
    "角川シネマ有楽町": "kadokawa-cinema-yurakucho",
}


def cinema_slug(name: str) -> str:
    """Curated romaji slug; else the Latin portion of "K's Cinema (ケイズシネマ)"."""
    if name in CINEMA_SLUG_MAP:
        return CINEMA_SLUG_MAP[name]
    latin = re.split(r"[（(]", name, 1)[0]
    return slugify(latin) or slugify(name)


def film_slug(fid: str, film: dict) -> str:
    title = first_nonempty([
        film.get("movie_title_en"), film.get("movie_title_original"),
        film.get("movie_title"),
    ]) or ""
    base = slugify(title)
    if fid.startswith("t"):
        tmdb = fid[1:]
        return f"{tmdb}-{base}".rstrip("-")
    return f"{base}-{short_hash(fid)}".lstrip("-") if base else f"film-{short_hash(fid)}"


def iso_start(date_text: str, showtime: str) -> str | None:
    if not date_text:
        return None
    t = (showtime or "").strip()
    if re.fullmatch(r"\d{1,2}:\d{2}", t):
        h, m = t.split(":")
        return f"{date_text}T{int(h):02d}:{m}:00+09:00"
    return f"{date_text}T00:00:00+09:00"


def e(text) -> str:
    return html.escape("" if text is None else str(text), quote=True)


def poster_url(path: str | None, size: str = "w342") -> str | None:
    return f"{TMDB_IMG}/{size}{path}" if path else None


def jsonld(obj) -> str:
    return ('<script type="application/ld+json">'
            + json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
            + "</script>")


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #
def aggregate(showings: list[dict]):
    """Return (films, cinemas) keyed structures from the flat showings list."""
    films: dict[str, dict] = {}
    film_recs: dict[str, list] = defaultdict(list)
    cinemas: dict[str, dict] = {}

    for rec in showings:
        fid = film_id(rec)
        film_recs[fid].append(rec)
        cname = (rec.get("cinema_name") or "").strip()
        if not cname:
            continue
        cin = cinemas.setdefault(cname, {"name": cname, "showings": [], "meta": {}})
        cin["showings"].append({
            "f": fid,
            "date_text": rec.get("date_text", ""),
            "showtime": rec.get("showtime", ""),
        })
        for key in ("cinema_address", "cinema_site_url"):
            if not cin["meta"].get(key) and rec.get(key):
                cin["meta"][key] = rec[key]

    for fid, recs in film_recs.items():
        film = {k: first_nonempty([r.get(k) for r in recs]) for k in PAGE_FILM_FIELDS}
        film["_showings"] = [{
            "cinema_name": (r.get("cinema_name") or "").strip(),
            "date_text": r.get("date_text", ""),
            "showtime": r.get("showtime", ""),
        } for r in recs]
        films[fid] = film

    return films, cinemas


def build_slim(films: dict, cinemas: dict, generated_at: str) -> dict:
    slim_films = {}
    for fid, film in films.items():
        slim_films[fid] = {k: film.get(k) for k in SLIM_FILM_FIELDS
                           if film.get(k) not in (None, "", [], {})}
    showings = []
    for cin in cinemas.values():
        for s in cin["showings"]:
            showings.append({
                "f": s["f"],
                "cinema_name": cin["name"],
                "date_text": s["date_text"],
                "showtime": s["showtime"],
            })
    showings.sort(key=lambda s: (s["date_text"], s["showtime"], s["cinema_name"]))
    return {"schema": 1, "generated_at": generated_at,
            "films": slim_films, "showings": showings}


# --------------------------------------------------------------------------- #
# Page rendering
# --------------------------------------------------------------------------- #
PAGE_CSS = """
:root{--bg:#f5f3ef;--ink:#1a1a1a;--muted:#6b6660;--line:#e0dcd4;--accent:#b3331f}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
 font-family:'Space Grotesk',system-ui,-apple-system,'Hiragino Kaku Gothic ProN',sans-serif;
 line-height:1.5}
a{color:inherit}
.wrap{max-width:860px;margin:0 auto;padding:24px 20px 64px}
.crumb{font-size:.85rem;color:var(--muted);margin-bottom:20px}
.crumb a{text-decoration:none;border-bottom:1px solid var(--line)}
h1{font-size:1.7rem;line-height:1.2;margin:0 0 4px}
.sub{color:var(--muted);font-size:1.05rem;margin:0 0 16px}
.meta{font-size:.9rem;color:var(--muted);margin:0 0 20px}
.hero{display:flex;gap:20px;flex-wrap:wrap;margin-bottom:24px}
.hero img{width:200px;height:auto;border-radius:8px;background:var(--line)}
.hero .info{flex:1;min-width:240px}
.synopsis{margin:16px 0;max-width:62ch}
.synopsis.en{color:var(--muted)}
h2{font-size:1.1rem;border-top:1px solid var(--line);padding-top:18px;margin:28px 0 12px}
.group{margin-bottom:16px}
.group h3{font-size:.95rem;margin:0 0 6px}
.group h3 a{text-decoration:none;border-bottom:1px solid var(--line)}
.times{display:flex;flex-wrap:wrap;gap:6px;margin:0;padding:0;list-style:none}
.times li{background:#fff;border:1px solid var(--line);border-radius:6px;
 padding:3px 9px;font-size:.9rem}
.btn{display:inline-block;margin-top:6px;font-size:.85rem;text-decoration:none;
 border-bottom:1px solid var(--accent);color:var(--accent)}
.foot{margin-top:40px;font-size:.8rem;color:var(--muted);
 border-top:1px solid var(--line);padding-top:16px}
"""


def head(title: str, description: str, canonical: str, base_url: str,
         image: str | None = None, extra_ld: list | None = None) -> str:
    tags = [
        "<!DOCTYPE html>", '<html lang="ja">', "<head>",
        '<meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
        f"<title>{e(title)}</title>",
        f'<meta name="description" content="{e(description)}">',
        f'<link rel="canonical" href="{e(canonical)}">',
        '<meta property="og:type" content="website">',
        f'<meta property="og:title" content="{e(title)}">',
        f'<meta property="og:description" content="{e(description)}">',
        f'<meta property="og:url" content="{e(canonical)}">',
        '<meta property="og:locale" content="ja_JP">',
        f'<meta name="twitter:card" content="{"summary_large_image" if image else "summary"}">',
    ]
    if image:
        tags.append(f'<meta property="og:image" content="{e(image)}">')
        tags.append(f'<meta name="twitter:image" content="{e(image)}">')
    tags += [
        '<link rel="preconnect" href="https://fonts.googleapis.com">',
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>',
        '<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">',
        f"<style>{PAGE_CSS}</style>",
    ]
    for ld in (extra_ld or []):
        tags.append(jsonld(ld))
    tags.append("</head>")
    return "\n".join(tags)


def render_film_page(fid, film, slug, base_url, today):
    title_jp = film.get("movie_title_jp") or film.get("movie_title") or "(無題)"
    title_en = film.get("movie_title_en") or film.get("movie_title_original") or ""
    canonical = f"{base_url}/film/{slug}/"
    img = poster_url(film.get("tmdb_poster_path"), "w500")

    upcoming = [s for s in film["_showings"] if s["date_text"] >= today]
    upcoming.sort(key=lambda s: (s["date_text"], s["showtime"]))

    # group by cinema for the human view
    by_cinema = defaultdict(list)
    for s in upcoming:
        by_cinema[s["cinema_name"]].append(s)

    meta_bits = []
    if film.get("year"):
        meta_bits.append(e(film["year"]))
    if film.get("director"):
        meta_bits.append("監督: " + e(film["director"]))
    rt = film.get("runtime") or film.get("runtime_min")
    if rt:
        meta_bits.append(f"{e(rt)}分")
    genres = film.get("genres") or []
    if genres:
        meta_bits.append(e(" / ".join(genres)))

    desc_src = (film.get("synopsis") or film.get("tmdb_overview_en")
                or f"{title_jp} screening times across Tokyo's independent cinemas.")
    description = f"{title_jp}（{title_en}）の東京での上映スケジュール。" if title_en \
        else f"{title_jp}の東京での上映スケジュール。"
    description = (description + " " + desc_src)[:300]

    # JSON-LD: Movie + ScreeningEvents
    movie_ld = {"@context": "https://schema.org", "@type": "Movie",
                "name": title_en or title_jp, "url": canonical}
    if title_en and title_jp != title_en:
        movie_ld["alternateName"] = title_jp
    if img:
        movie_ld["image"] = img
    if film.get("director"):
        movie_ld["director"] = {"@type": "Person",
                                "name": film.get("director_en") or film["director"]}
    if film.get("year"):
        movie_ld["datePublished"] = str(film["year"])
    if film.get("synopsis") or film.get("tmdb_overview_en"):
        movie_ld["description"] = film.get("synopsis") or film.get("tmdb_overview_en")
    if film.get("genres_en") or film.get("genres"):
        movie_ld["genre"] = film.get("genres_en") or film.get("genres")
    events = []
    for s in upcoming:
        start = iso_start(s["date_text"], s["showtime"])
        if not start:
            continue
        events.append({"@context": "https://schema.org", "@type": "ScreeningEvent",
                       "name": f"{title_jp} @ {s['cinema_name']}",
                       "startDate": start,
                       "workPresented": {"@type": "Movie", "name": title_en or title_jp},
                       "location": {"@type": "MovieTheater", "name": s["cinema_name"]}})

    parts = [head(f"{title_jp}｜東京の上映スケジュール - cinematokyo", description,
                  canonical, base_url, image=img, extra_ld=[movie_ld] + events),
             "<body>", '<div class="wrap">',
             f'<div class="crumb"><a href="{base_url}/">← Tokyo Cinema</a></div>',
             '<div class="hero">']
    if img:
        parts.append(f'<img src="{e(img)}" alt="{e(title_jp)} poster" loading="lazy">')
    parts.append('<div class="info">')
    parts.append(f"<h1>{e(title_jp)}</h1>")
    if title_en and title_en != title_jp:
        parts.append(f'<p class="sub">{e(title_en)}</p>')
    if meta_bits:
        parts.append(f'<p class="meta">{" · ".join(meta_bits)}</p>')
    parts.append("</div></div>")

    if film.get("synopsis"):
        parts.append(f'<p class="synopsis">{e(film["synopsis"])}</p>')
    if film.get("tmdb_overview_en"):
        parts.append(f'<p class="synopsis en">{e(film["tmdb_overview_en"])}</p>')

    parts.append("<h2>上映スケジュール / Showtimes</h2>")
    if not upcoming:
        parts.append("<p>現在予定されている上映はありません。</p>")
    cinema_slugs = render_film_page.cinema_slugs
    for cname, slist in by_cinema.items():
        cslug = cinema_slugs.get(cname)
        link = f'<a href="{base_url}/cinema/{cslug}/">{e(cname)}</a>' if cslug else e(cname)
        parts.append(f'<div class="group"><h3>{link}</h3><ul class="times">')
        for s in slist:
            label = f'{s["date_text"][5:]} {s["showtime"]}'.strip()
            parts.append(f"<li>{e(label)}</li>")
        parts.append("</ul></div>")

    booking = film.get("booking_url") or film.get("purchase_url") or film.get("detail_page_url")
    if booking:
        parts.append(f'<a class="btn" href="{e(booking)}" rel="nofollow">公式サイト / Details →</a>')
    parts.append('<p class="foot">Source: <a href="' + base_url + '/">cinematokyo.com</a> · '
                 'Tokyo mini-theater &amp; independent cinema showtimes.</p>')
    parts.append("</div></body></html>")
    return "\n".join(parts)


def render_cinema_page(cname, cin, slug, films, film_slugs, base_url, today):
    canonical = f"{base_url}/cinema/{slug}/"
    upcoming = [s for s in cin["showings"] if s["date_text"] >= today]
    upcoming.sort(key=lambda s: (s["date_text"], s["showtime"]))
    by_date = defaultdict(list)
    for s in upcoming:
        by_date[s["date_text"]].append(s)

    n_films = len({s["f"] for s in upcoming})
    description = (f"{cname}の上映スケジュール。"
                   f"今後{len(upcoming)}回の上映、{n_films}作品。"
                   " Showtimes and screening schedule.")[:300]

    theater_ld = {"@context": "https://schema.org", "@type": "MovieTheater",
                  "name": cname, "url": canonical}
    if cin["meta"].get("cinema_address"):
        theater_ld["address"] = cin["meta"]["cinema_address"]
    if cin["meta"].get("cinema_site_url"):
        theater_ld["sameAs"] = cin["meta"]["cinema_site_url"]
    events = []
    for s in upcoming:
        start = iso_start(s["date_text"], s["showtime"])
        film = films.get(s["f"], {})
        ftitle = film.get("movie_title_jp") or film.get("movie_title") or ""
        if not start or not ftitle:
            continue
        events.append({"@context": "https://schema.org", "@type": "ScreeningEvent",
                       "name": f"{ftitle} @ {cname}", "startDate": start,
                       "workPresented": {"@type": "Movie", "name": ftitle},
                       "location": {"@type": "MovieTheater", "name": cname}})

    parts = [head(f"{cname}｜上映スケジュール - cinematokyo", description, canonical,
                  base_url, extra_ld=[theater_ld] + events),
             "<body>", '<div class="wrap">',
             f'<div class="crumb"><a href="{base_url}/">← Tokyo Cinema</a></div>',
             f"<h1>{e(cname)}</h1>"]
    site = cin["meta"].get("cinema_site_url")
    if cin["meta"].get("cinema_address"):
        parts.append(f'<p class="meta">{e(cin["meta"]["cinema_address"])}</p>')
    if site:
        parts.append(f'<a class="btn" href="{e(site)}" rel="nofollow">公式サイト →</a>')

    parts.append("<h2>上映スケジュール / Showtimes</h2>")
    if not upcoming:
        parts.append("<p>現在予定されている上映はありません。</p>")
    for date_text, slist in by_date.items():
        parts.append(f'<div class="group"><h3>{e(date_text)}</h3><ul class="times">')
        for s in sorted(slist, key=lambda x: x["showtime"]):
            film = films.get(s["f"], {})
            ftitle = film.get("movie_title_jp") or film.get("movie_title") or "?"
            fslug = film_slugs.get(s["f"])
            label = f'{s["showtime"]} {ftitle}'.strip()
            if fslug:
                parts.append(f'<li><a href="{base_url}/film/{fslug}/" '
                             f'style="text-decoration:none">{e(label)}</a></li>')
            else:
                parts.append(f"<li>{e(label)}</li>")
        parts.append("</ul></div>")

    parts.append('<p class="foot">Source: <a href="' + base_url + '/">cinematokyo.com</a></p>')
    parts.append("</div></body></html>")
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# Index pre-render (inject into the existing SPA)
# --------------------------------------------------------------------------- #
def build_index(template: Path, films, built_cinemas, built_films,
                base_url, today) -> str:
    """built_cinemas/built_films map name/fid -> slug for pages that actually exist."""
    html_src = template.read_text(encoding="utf-8")

    # Fix asset/data paths for the new repo layout (data/ and /icons/ at root).
    html_src = html_src.replace("tokyo-cinema-scrapers/data/", "data/")
    html_src = html_src.replace("/tokyo-cinema-scrapers/icons/", "/icons/")
    html_src = html_src.replace("tokyo-cinema-scrapers/icons/", "icons/")

    # Crawler-visible block; the SPA clears #film-results-list on first render,
    # so users never see it but search engines and link unfurlers do.
    rows = []
    rows.append("<noscript><p>JavaScript で絞り込み・検索ができます。"
                "以下は全上映の一覧です。</p></noscript>")
    rows.append('<h2>Cinemas / 映画館</h2><ul>')
    for cname in sorted(built_cinemas):
        rows.append(f'<li><a href="{base_url}/cinema/{built_cinemas[cname]}/">'
                    f'{e(cname)}</a></li>')
    rows.append("</ul>")
    rows.append('<h2>Films / 作品</h2><ul>')
    for fid in sorted(built_films, key=lambda k: films[k].get("movie_title_jp") or ""):
        title = films[fid].get("movie_title_jp") or films[fid].get("movie_title") or ""
        if title:
            rows.append(f'<li><a href="{base_url}/film/{built_films[fid]}/">'
                        f'{e(title)}</a></li>')
    rows.append("</ul>")
    seo_block = ('<div id="seo-prerender" data-prerender="1">'
                 + "\n".join(rows) + "</div>")

    anchor = 'id="film-results-list">'
    if anchor in html_src:
        html_src = html_src.replace(anchor, anchor + seo_block, 1)

    # Richer, bilingual head metadata + WebSite/ItemList JSON-LD.
    new_title = ("東京ミニシアター上映時間 | Tokyo Mini-Theater &amp; "
                 "Independent Cinema Showtimes")
    new_desc = ("東京のミニシアター・名画座・インディペンデント系映画館の上映スケジュールを"
                "毎日更新。A daily-updated bilingual guide to independent and "
                "mini-theater film showtimes across Tokyo.")
    html_src = re.sub(r"<title>.*?</title>", f"<title>{new_title}</title>",
                      html_src, count=1, flags=re.S)
    html_src = re.sub(r'<meta name="description" content=".*?">',
                      f'<meta name="description" content="{new_desc}">',
                      html_src, count=1, flags=re.S)
    html_src = re.sub(r'href="https://www\.leonelki\.com/tokyo-cinemas\.html"',
                      f'href="{base_url}/"', html_src)
    html_src = re.sub(r'content="https://www\.leonelki\.com/tokyo-cinemas\.html"',
                      f'content="{base_url}/"', html_src)

    site_ld = {"@context": "https://schema.org", "@type": "WebSite",
               "name": "Tokyo Cinema — cinematokyo", "url": base_url + "/",
               "inLanguage": ["ja", "en"]}
    cinema_ld = {"@context": "https://schema.org", "@type": "ItemList",
                 "name": "Tokyo independent cinemas",
                 "itemListElement": [
                     {"@type": "ListItem", "position": i + 1,
                      "url": f"{base_url}/cinema/{built_cinemas[c]}/", "name": c}
                     for i, c in enumerate(sorted(built_cinemas))]}
    head_ld = "\n" + jsonld(site_ld) + "\n" + jsonld(cinema_ld) + "\n</head>"
    html_src = html_src.replace("</head>", head_ld, 1)
    return html_src


# --------------------------------------------------------------------------- #
# Sitemap / robots
# --------------------------------------------------------------------------- #
def build_sitemap(base_url, built_cinemas, built_films, generated_at):
    """Only list pages that were actually generated (avoids 404s in the sitemap)."""
    lastmod = generated_at[:10]
    urls = [f"{base_url}/"]
    urls += [f"{base_url}/cinema/{s}/" for s in sorted(set(built_cinemas.values()))]
    urls += [f"{base_url}/film/{s}/" for s in sorted(set(built_films.values()))]
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        freq = "daily" if u.endswith("/") and "/cinema/" not in u and "/film/" not in u else "daily"
        out.append(f"  <url><loc>{e(u)}</loc><lastmod>{lastmod}</lastmod>"
                   f"<changefreq>{freq}</changefreq></url>")
    out.append("</urlset>")
    return "\n".join(out)


def build_robots(base_url):
    return f"User-agent: *\nAllow: /\n\nSitemap: {base_url}/sitemap.xml\n"


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default="tokyo/data/showtimes.json")
    ap.add_argument("--template", default="tokyo/site_template")
    ap.add_argument("--out", default="tokyo/site_build")
    ap.add_argument("--base-url", default="https://cinematokyo.com")
    ap.add_argument("--domain", default="cinematokyo.com")
    ap.add_argument("--today", default=None,
                    help="Override 'today' (YYYY-MM-DD) for testing against fixed data.")
    args = ap.parse_args()

    base_url = args.base_url.rstrip("/")
    data_path = Path(args.data)
    template_dir = Path(args.template)
    out = Path(args.out)

    showings = json.loads(data_path.read_text(encoding="utf-8"))
    today = args.today or jst_today()
    generated_at = dt.datetime.now(JST).isoformat(timespec="seconds")
    print(f"Loaded {len(showings)} showings; today (JST) = {today}")

    films, cinemas = aggregate(showings)

    # Stable slug maps.
    cinema_slugs, taken_c = {}, set()
    for cname in sorted(cinemas):
        cinema_slugs[cname] = unique(cinema_slug(cname), taken_c, "cinema")
    film_slugs, taken_f = {}, set()
    for fid in sorted(films):
        film_slugs[fid] = unique(film_slug(fid, films[fid]), taken_f, "film")

    # Reset & prepare output tree.
    if out.exists():
        shutil.rmtree(out)
    (out / "data").mkdir(parents=True)
    (out / "cinema").mkdir()
    (out / "film").mkdir()

    # Static assets from the template dir.
    for name in ("manifest.webmanifest", "sw.js"):
        src = template_dir / name
        if src.exists():
            shutil.copy(src, out / name)
    if (template_dir / "icons").exists():
        shutil.copytree(template_dir / "icons", out / "icons")

    # Data feeds.
    shutil.copy(data_path, out / "data" / "showtimes.json")
    slim = build_slim(films, cinemas, generated_at)
    (out / "data" / "showtimes_slim.json").write_text(
        json.dumps(slim, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Slim: {len(slim['films'])} films, {len(slim['showings'])} showings")

    # Per-film pages (only films with upcoming showings).
    render_film_page.cinema_slugs = cinema_slugs  # share for cross-links
    built_films = {}
    for fid, film in films.items():
        if not any(s["date_text"] >= today for s in film["_showings"]):
            continue
        slug = film_slugs[fid]
        page = render_film_page(fid, film, slug, base_url, today)
        d = out / "film" / slug
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(page, encoding="utf-8")
        built_films[fid] = slug

    # Per-cinema pages (only cinemas with upcoming showings).
    built_cinemas = {}
    for cname, cin in cinemas.items():
        if not any(s["date_text"] >= today for s in cin["showings"]):
            continue
        slug = cinema_slugs[cname]
        page = render_cinema_page(cname, cin, slug, films, film_slugs, base_url, today)
        d = out / "cinema" / slug
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(page, encoding="utf-8")
        built_cinemas[cname] = slug

    # Index (SPA + pre-render), sitemap, robots, CNAME — only reference built pages.
    index_html = build_index(template_dir / "index.html", films, built_cinemas,
                             built_films, base_url, today)
    (out / "index.html").write_text(index_html, encoding="utf-8")
    (out / "sitemap.xml").write_text(
        build_sitemap(base_url, built_cinemas, built_films, generated_at), encoding="utf-8")
    (out / "robots.txt").write_text(build_robots(base_url), encoding="utf-8")
    (out / "CNAME").write_text(args.domain + "\n", encoding="utf-8")

    print(f"Built: index + {len(built_cinemas)} cinema pages + {len(built_films)} film pages")
    print(f"Output: {out}")


if __name__ == "__main__":
    main()
