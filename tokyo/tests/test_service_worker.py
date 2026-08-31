import re
import subprocess
import unittest
from pathlib import Path


SERVICE_WORKER = Path(__file__).resolve().parents[1] / "site_template" / "sw.js"


class ServiceWorkerCachingTest(unittest.TestCase):
    def test_showtime_json_is_network_first_and_static_assets_remain_cache_first(self):
        source = SERVICE_WORKER.read_text()

        self.assertEqual(source.count('const CACHE_NAME = "cinematokyo-v4";'), 1)
        self.assertNotIn("cinematokyo-v3", source)
        self.assertIn('url.pathname.startsWith("/data/")', source)
        self.assertIn('url.pathname.endsWith(".json")', source)
        self.assertLess(
            source.index("url.origin !== self.location.origin"),
            source.index("const isShowtimeData"),
        )

        network_first = re.search(
            r"if \(isHtml \|\| isShowtimeData\) \{(?P<body>.*?)\n  \}",
            source,
            re.DOTALL,
        )
        self.assertIsNotNone(network_first)
        self.assertIn(
            ".catch(() => caches.match(event.request))", network_first.group("body")
        )
        self.assertLess(
            network_first.group("body").index("fetch(event.request)"),
            network_first.group("body").index("caches.match(event.request)"),
        )

        cache_first = source[network_first.end() :]
        self.assertLess(
            cache_first.index("caches.match(event.request)"),
            cache_first.index("fetch(event.request)"),
        )

    def test_cache_strategy_semantics(self):
        check = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(process.argv[1], "utf8");
const response = (name, ok) => ({ name, ok, clone: () => ({ name, ok }) });
const execute = ({ url, network, cached, fetchError = null, putError = null }) => {
  const listeners = {};
  const writes = [];
  const fetches = [];
  const matches = [];
  const responses = [];
  const context = {
    URL,
    Promise,
    Error,
    self: {
      location: { origin: "https://cinematokyo.com" },
      addEventListener: (name, listener) => (listeners[name] = listener)
    },
    caches: {
      open: () => Promise.resolve({
        put: (...args) => (
          writes.push(args),
          putError ? Promise.reject(putError) : Promise.resolve()
        )
      }),
      match: (...args) => (matches.push(args), Promise.resolve(cached))
    },
    fetch: (...args) => (
      fetches.push(args),
      fetchError ? Promise.reject(fetchError) : Promise.resolve(network)
    )
  };
  vm.runInNewContext(source, context);
  listeners.fetch({
    request: { method: "GET", url },
    respondWith: (value) => responses.push(value)
  });
  return responses[0].then((value) => ({ value, writes, fetches, matches }));
};
const dataUrl = "https://cinematokyo.com/data/showtimes_slim.json";
const assetUrl = "https://cinematokyo.com/icons/icon-192.png";
const fresh = response("fresh", true);
const stale = { name: "stale" };
const failed = response("failed", false);
const cachedAsset = { name: "cached-asset" };
const deadline = setTimeout(() => {
  process.stderr.write("service-worker check timed out\n");
  process.exitCode = 1;
}, 1000);
Promise.all([
  execute({ url: dataUrl, network: fresh, cached: stale }),
  execute({ url: dataUrl, network: fresh, cached: stale, putError: new Error("quota") }),
  execute({ url: dataUrl, network: fresh, cached: stale, fetchError: new Error("offline") }),
  execute({ url: dataUrl, network: failed, cached: stale }),
  execute({ url: assetUrl, network: fresh, cached: cachedAsset })
])
  .then(([success, cacheFailure, offline, httpError, asset]) => {
    assert.strictEqual(success.value, fresh);
    assert.deepStrictEqual(
      [success.fetches.length, success.writes.length, success.matches.length],
      [1, 1, 0]
    );
    assert.strictEqual(cacheFailure.value, fresh);
    assert.deepStrictEqual(
      [cacheFailure.fetches.length, cacheFailure.writes.length, cacheFailure.matches.length],
      [1, 1, 0]
    );
    assert.strictEqual(offline.value, stale);
    assert.deepStrictEqual(
      [offline.fetches.length, offline.writes.length, offline.matches.length],
      [1, 0, 1]
    );
    assert.strictEqual(httpError.value, stale);
    assert.deepStrictEqual(
      [httpError.fetches.length, httpError.writes.length, httpError.matches.length],
      [1, 0, 1]
    );
    assert.strictEqual(asset.value, cachedAsset);
    assert.deepStrictEqual(
      [asset.fetches.length, asset.writes.length, asset.matches.length],
      [0, 0, 1]
    );
  })
  .then(() => clearTimeout(deadline))
  .catch((error) => {
    clearTimeout(deadline);
    process.stderr.write(`${error.stack || error}\n`);
    process.exitCode = 1;
  });
"""
        result = subprocess.run(
            ["node", "-e", check, str(SERVICE_WORKER)],
            capture_output=True,
            text=True,
            timeout=5,
        )

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
