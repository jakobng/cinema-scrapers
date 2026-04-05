const fs = require("fs");
const vm = require("vm");

const html = fs.readFileSync(0, "utf8");
const match = html.match(/<script>window\.__NUXT__=(.*?)<\/script>/s);

if (!match) {
  process.stderr.write("Unable to locate OPENTIX Nuxt payload.\n");
  process.exit(1);
}

const source = match[0].replace("<script>", "").replace("</script>", "");
const sandbox = { window: {} };
vm.createContext(sandbox);
vm.runInContext(source, sandbox, { timeout: 5000 });

const program = sandbox.window && sandbox.window.__NUXT__ && sandbox.window.__NUXT__.data
  ? sandbox.window.__NUXT__.data[0].program
  : null;

if (!program) {
  process.stderr.write("Unable to decode OPENTIX program payload.\n");
  process.exit(1);
}

process.stdout.write(JSON.stringify(program));
