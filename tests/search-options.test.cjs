const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

test("search options survive URL serialization and the original-spelling retry", async () => {
  const location = { hash: "" };
  const context = vm.createContext({
    URLSearchParams, location,
    window: { addEventListener() {} },
    document: { addEventListener() {}, querySelectorAll: () => [] },
    localStorage: { getItem: () => null },
    fetch: () => new Promise(() => {}),
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../app/static/sb.js"), "utf8"), context);
  const encoded = vm.runInContext("qs({spell:false, personalize:false, log:false, clusters:false, offset:0, topic:''})", context);
  assert.deepEqual(Object.fromEntries(new URLSearchParams(encoded)), {
    spell: "false", personalize: "false", log: "false", clusters: "false", offset: "0",
  });
  await vm.runInContext(`S.results = { params: { q: "boundry layer", personal: "off", mode: "bm25" } };
    onResultsClick({target:{closest: () => ({dataset:{orig:""}, closest: () => null})}})`, context);
  assert.equal(location.hash, "#/search?q=boundry+layer&personal=off&mode=bm25&spell=false");
});
