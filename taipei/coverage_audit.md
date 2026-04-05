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

## Deferred

- `國家電影及視聽文化中心 / TFAI`
  - Source: `https://www.tfai.org.tw/zh/program/topicList`
  - Status: deferred
  - Reason: public program pages are blocked by Cloudflare from this environment. The venue fits scope, but the source currently behaves like a hard anti-bot gate for automated access.

## Explicitly Out Of Scope

- Major multiplex chains and mainstream commercial circuits in the Taipei area
  - Examples: `Vieshow`, `Showtime`, `in89`, large chain branches
  - Reason: excluded by the product brief for this v1.

