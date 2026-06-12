# Manchester Art Gallery – export events from your browser

The Manchester Art Gallery site is behind Cloudflare, so the scraper often cannot load the event page. You can **export the current list from your browser** and the scraper will use it automatically.

## Steps

1. Open **https://manchesterartgallery.org/event/** in your browser (Chrome, Edge, Firefox) and wait until the page has fully loaded (all events visible).

2. Open Developer Tools: press **F12** (or right‑click → Inspect). Go to the **Console** tab.

3. Paste the script below into the console and press **Enter**.

4. The script will print a JSON array. **Copy the whole output** (from `[` to `]`).

5. Save it as:  
   `north-art-exhibitions/data/manchester_events_export.json`  
   (overwrite the file if it already exists).

6. Run the main scraper as usual. It will use this file when it cannot fetch the event page.

You can repeat this whenever the programme changes (e.g. every few weeks or before a run).

---

## Script to paste in the console

```javascript
(function() {
  var out = [];
  var links = document.querySelectorAll('a[href*="/event/"]');
  var seen = {};
  for (var i = 0; i < links.length; i++) {
    var a = links[i];
    var href = (a.getAttribute('href') || '').trim();
    if (href === '' || href === '/event/' || href === '/event' || href.endsWith('manchesterartgallery.org/event')) continue;
    if (seen[href]) continue;
    seen[href] = true;
    var title = (a.textContent || '').trim().replace(/\s+/g, ' ');
    if (title.length < 3) continue;
    if (/^(read more|book now|more info|events|exhibitions|what's on|view all)$/i.test(title)) continue;
    var fullUrl = href.startsWith('http') ? href : 'https://manchesterartgallery.org' + (href.startsWith('/') ? href : '/' + href);
    var card = a.closest('article, .event, .card, [class*="event"], [class*="card"]') || a.parentElement;
    for (var j = 0; j < 8 && card; j++) {
      if (card.querySelector && card.querySelector('img[src]')) {
        var img = card.querySelector('img[src]');
        var src = img.getAttribute('src') || '';
        if (src && src.indexOf('data:') !== 0) break;
      }
      card = card.parentElement;
    }
    var imgSrc = card && card.querySelector && card.querySelector('img[src]') ? (card.querySelector('img[src]').getAttribute('src') || '') : '';
    if (imgSrc && imgSrc.indexOf('data:') === 0) imgSrc = '';
    var dateText = '';
    card = a.parentElement;
    for (var k = 0; k < 6 && card; k++) {
      dateText = (card.textContent || '').replace(/\s+/g, ' ');
      if (/\d{1,2}\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}/.test(dateText)) break;
      card = card.parentElement;
    }
    out.push({
      title: title,
      url: fullUrl,
      date_text: dateText || null,
      start_date: null,
      end_date: null,
      image_url: imgSrc || null
    });
  }
  console.log(JSON.stringify(out, null, 2));
  return out;
})();
```

After it runs, copy the printed JSON and save it as `data/manchester_events_export.json`.
