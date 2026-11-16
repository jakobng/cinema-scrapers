from pathlib import Path
import subprocess
import sys

TOKYO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOKYO))
from build_site import booking_click_attribute, showtime_link_fields


def test_booking_markers_exclude_fallback_links():
    official = "https://cinema.example/showtimes"
    ticket = "https://cinema.example/tickets/123"
    booking = showtime_link_fields({"purchase_url": ticket, "cinema_site_url": official})
    fallback = showtime_link_fields({"cinema_site_url": official})
    assert booking["booking_url"] == ticket
    assert fallback["booking_url"] == official
    assert booking_click_attribute(booking) == " data-booking-click"
    assert booking_click_attribute(fallback) == ""


def test_clicks_are_counted_without_link_data_or_navigation_control():
    script = r"""
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import worker from "./booking_click_worker.mjs";

const handlers = {};
const requests = [];
const navigator = {};
vm.runInNewContext(readFileSync("site_template/booking-clicks.js", "utf8"), {
    document: { addEventListener: (type, handler) => { handlers[type] = handler; } },
    navigator,
    fetch: (url, options) => {
        requests.push(new Request(url, options));
        return Promise.resolve();
    },
});
const event = {
    type: "click", isTrusted: true, button: 0,
    target: { closest: selector => selector === "a[data-booking-click]" ? {} : null },
    preventDefault: () => assert.fail("Click must retain normal navigation"),
};
handlers.click({ ...event, target: { closest: () => null } });
handlers.click({ ...event, isTrusted: false });
handlers.auxclick({ ...event, type: "auxclick", button: 2 });
navigator.globalPrivacyControl = true;
handlers.click(event);
navigator.globalPrivacyControl = false;
navigator.doNotTrack = "1";
handlers.click(event);
navigator.doNotTrack = "0";
assert.equal(requests.length, 0);
handlers.click(event);
handlers.auxclick({ ...event, type: "auxclick", button: 1 });
assert.equal(requests.length, 2);

const [request] = requests;
assert.equal(request.method, "POST");
assert.equal(request.body, null);
assert.equal(request.keepalive, true);
assert.equal(request.credentials, "omit");
assert.equal(request.referrerPolicy, "no-referrer");

const statements = [];
const env = {
    BOOKING_CLICKS: { prepare: sql => ({ run: () => Promise.resolve(statements.push(sql)) }) },
};
assert.equal(worker.fetch(new Request(request.url), env).status, 404);
assert.equal(worker.fetch(request, env).status, 403);
assert.equal(statements.length, 0);
const origin = "https://cinematokyo.com";
const accepted = await worker.fetch(new Request(request, { headers: { Origin: origin } }), env);
assert.equal(accepted.status, 204);
assert.equal(accepted.headers.get("Access-Control-Allow-Origin"), origin);
const streamed = new Request(request.url, {
    method: "POST", headers: { Origin: origin },
    body: new Uint8Array(), duplex: "half",
});
assert.notEqual(streamed.body, null);
assert.equal((await worker.fetch(streamed, env)).status, 204);
assert.equal(statements.length, 2);
assert.match(statements[0], /ON CONFLICT\(day\) DO UPDATE SET clicks = clicks \+ 1/);
"""
    subprocess.run(["node", "--input-type=module", "-e", script], cwd=TOKYO, check=True)
