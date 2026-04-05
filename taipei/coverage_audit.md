# Taipei Coverage Audit

## Implemented

- `SPOT台北之家 / SPOT Taipei Film House`
  - Source: `https://www.spot.org.tw/`
  - Status: implemented
  - Notes: current movie detail pages expose inline schedule text and basic metadata.

- `光點華山電影館 / SPOT-Huashan`
  - Source: `https://www.spot-hs.org.tw/movie/nowplaying.html`
  - Status: implemented
  - Notes: current movie detail pages expose `MovieSchedule` JavaScript arrays with dated sessions.

- `誠品電影院（松菸） / Eslite Art House Songyan`
  - Source: `https://arthouse.eslite.com/`
  - Status: implemented
  - Notes: public schedule is accessible after the ticket-rules agreement flow; session tables are rendered server-side.

- `真善美劇院 / Wonderful Theatre`
  - Source: `https://wonderful.movie.com.tw/time`
  - Status: implemented
  - Notes: public `/lightbox/index?id=...` responses expose dated session lists; detail pages expose runtime and director.

- `府中15放映院 / Fuzhong 15`
  - Source: `https://www.fuzhong15.ntpc.gov.tw/xcmovie?xsmsid=0m361641875264878260`
  - Status: implemented
  - Notes: public schedule table includes date, time, title, runtime, and rating.
- `國家電影及視聽文化中心 / TFAI`
  - Source: `https://www.opentix.life/o/tfai`
  - Status: implemented
  - Notes: the main TFAI site is Cloudflare-blocked here, but the official OPENTIX organizer storefront exposes current film cards and event pages with structured session data.

## Explicitly Out Of Scope

- Major multiplex chains and mainstream commercial circuits in the Taipei area
  - Examples: `Vieshow`, `Showtime`, `in89`, large chain branches
  - Reason: excluded by the product brief for this v1.

## Added In This Pass

- `Skyline Film`
  - Source: `https://www.skyline.film/` and `https://api.skyline.film/api/activity`
  - Status: implemented
  - Notes: recurring rooftop screenings are exposed through the public Skyline activity API, with one ticket object per film slot.

- `æ¡ƒåœ’å…‰å½±æ–‡åŒ–é¤¨ / Taoyuan Arts Cinema II`
  - Source: `https://tyac2.afmc.gov.tw/Event_table`
  - Status: implemented
  - Notes: the official schedule page exposes direct session links, and detail pages provide director, country, year, runtime, synopsis, and ticket-link metadata.

- `ä¸­å£¢å…‰å½±é›»å½±é¤¨ / Zhongli Arts Cinema`
  - Source: `https://www.taoyuan.arts-cinema.com/`
  - Status: implemented
  - Notes: the public site exposes JSON endpoints for exhibition years, monthly programs, film lists, and per-film detail payloads.

## Excluded From Current Implementation

- `Broadway 3D Digital Cinema`
  - Reason: mainstream commercial cinema, not an independent / recurring film-club source.

- `in89 Deluxe Digital Cinema`
  - Reason: mainstream commercial cinema, not an independent / recurring film-club source.

- Museums, cafes, bars, music venues, and general arts sites with only occasional film events
  - Examples from the candidate list: `Taipei Fine Arts Museum`, `Taiwan Contemporary Culture Lab (C-LAB)`, `Taipei Zhongshan Hall`, `Museum of Contemporary Art Taipei (MoCA)`, `Bopiliao Historic Block`, `Treasure Hill Artist Village`, `Kishu An Forest of Literature`, `Kuandu Museum of Fine Arts`, `Polymer Art Space`, `The Wall Live House`, `Boven Magazine Library`, `Mayor's Residence Art Salon`, `Lightbox Photo Library`, `Woolloomooloo Out West`, `Cosma Taipei`, `Red Room Rendezvous`, `Taoyuan Arts Center`, `Zhongli Arts Hall`, `A8 Art Center`, `Keelung Cultural Center`
  - Reason: these may host one-off screenings, but they are not currently strong recurring cinema-program sources in the same way as the implemented venues above.

## Broader Venue Expansion

- `牯嶺街小劇場 / Guling Street Avant-garde Theatre`
  - Source: `https://www.glt.org.tw/`
  - Status: implemented
  - Notes: official search RSS feeds and detail pages are filtered to upcoming screening-oriented posts.

- `臺灣當代文化實驗場 / C-LAB`
  - Source: `https://clab.org.tw/events/`
  - Status: implemented
  - Notes: official event cards and detail pages are filtered to film / moving-image programming rather than the full multidisciplinary event stream.

- `臺北市立美術館 / Taipei Fine Arts Museum`
  - Source: `https://www.tfam.museum/ashx/Event.ashx?ddlLang=zh-tw`
  - Status: implemented
  - Notes: the official event API is live; the scraper is intentionally keyword-gated and may return zero rows when no current film-coded museum events are published.

- `臺北市電影主題公園 / Taipei Cinema Park`
  - Source: `https://www.cinemapark.taipei/event_list.aspx` and `https://www.cinemapark.taipei/content.aspx`
  - Status: implemented
  - Notes: the official event API is mostly general park programming, so the scraper only emits seasonal screening / pop-up-cinema entries when the payload explicitly uses screening language.

- `Taipei Zhongshan Hall`
  - Status: not implemented
  - Notes: still not added because I have not found a reliable official event feed that consistently exposes screening events in a way worth scraping.

- `Lightbox Photo Library`
  - Status: implemented
  - Notes: the official events listing is straightforward to scrape; the scraper is intentionally strict and may return zero rows when the current program is talks/workshops rather than screenings.

- `濕地 / venue`
  - Status: not implemented
  - Notes: the official archive is scrapeable, but recent public event data does not show a stable recurring film-program pattern strong enough to justify a screening scraper yet.

- `寶藏巖國際藝術村 / Treasure Hill Artist Village`
  - Status: implemented
  - Notes: the official event listing and detail pages are scrapeable; the scraper is keyword-gated to moving-image language and may often be dormant outside qualifying programs.

## Organizer Expansion

- `Taipei Film Festival`
  - Source: `https://www.opentix.life/o/1419922383411732480`
  - Status: implemented
  - Notes: sourced from the official OPENTIX organizer storefront and program pages; expected to be dormant outside the active annual festival window.

- `Women Make Waves`
  - Source: `https://www.opentix.life/o/1559092709744377857`
  - Status: implemented
  - Notes: sourced from the official OPENTIX organizer storefront and intended for recurring screenings and festival windows rather than daily cinema output.

- `Taiwan International Queer Film Festival`
  - Source: `https://www.opentix.life/o/1544892925691940865`
  - Status: implemented
  - Notes: sourced from the official OPENTIX organizer storefront and expected to be sparse outside the active festival cycle.

## Hybrid Cinema Expansion

- `Taipei Changchun Ambassador Cinema`
  - Source: `https://www.ambassador.com.tw/home/Showtime?ID=453b2966-f7c2-44a9-b2eb-687493855d0e`
  - Status: implemented
  - Notes: added under the broader hybrid-cinema rule. The official site exposes dated showtime pages and detail pages cleanly enough to scrape the full cinema feed.

- `Xinzhuang Ambassador Cinema`
  - Source: `https://www.ambassador.com.tw/home/Showtime?ID=3301d822-b385-4aa8-a9eb-aa59d58e95c9`
  - Status: implemented
  - Notes: same official Ambassador source model as Changchun, extended to New Taipei under the broader hybrid-cinema rule.

- `Tamsui Ambassador Cinema`
  - Source: `https://www.ambassador.com.tw/home/Showtime?ID=1e42d235-c3cf-4f75-a382-af60f67a4aad`
  - Status: implemented
  - Notes: same official Ambassador source model as Changchun, extended to New Taipei under the broader hybrid-cinema rule.

- `Bade Ambassador Cinema`
  - Source: `https://www.ambassador.com.tw/home/Showtime?ID=8fda9934-73d4-4c14-b1c4-386c2b81045c`
  - Status: implemented
  - Notes: same official Ambassador source model as Changchun, extended to Taoyuan under the broader hybrid-cinema rule.

- `Taipei Ximen in89 Cinema`
  - Source: `https://www.in89.com.tw/index.aspx?TheaterId=3`
  - Status: implemented
  - Notes: added under the broader hybrid-cinema rule. The official site exposes a theater-scoped API for current stage listings, which makes the full cinema feed practical to scrape.

- `Taoyuan Station in89 Cinema`
  - Source: `https://www.in89.com.tw/index.aspx?TheaterId=1`
  - Status: implemented
  - Notes: same official in89 theater-scoped API as Ximen, extended to Taoyuan under the broader hybrid-cinema rule.

