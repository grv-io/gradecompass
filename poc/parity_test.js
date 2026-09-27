// Helper for parity_test.py: emits the 756-case JSON payload from either the
// engine.js module ("module") or the copy inlined in index.html ("inline").
// Usage: node parity_test.js <module|inline> <frontend-dir>
const fs = require("fs");
const path = require("path");
const [mode, frontendDir] = process.argv.slice(2);

let G;
if (mode === "module") {
  G = require(path.join(frontendDir, "engine.js"));
} else {
  global.window = {};
  global.performance = require("perf_hooks").performance;
  const src = fs.readFileSync(path.join(frontendDir, "index.html"), "utf8");
  const block = src.split("<script>")[1].split("</script>")[0]; // first <script> = engine
  new Function(block)();
  G = global.window.GradeCompass;
}

const out = [];
for (const app of Object.keys(G.APPLICATIONS))
  for (const dist of Object.keys(G.DISTRICTS))
    for (const cost of ["low", "medium", "high"])
      for (const weld of [null, true, false]) {
        const r = G.recommend(app, dist, cost, weld);
        delete r.engine_ms;
        out.push(r);
      }
process.stdout.write(JSON.stringify(out));
