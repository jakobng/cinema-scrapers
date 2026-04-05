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

