import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", {
      headers: { accept: "text/html" },
    }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );
}

test("server-renders the benchmark dashboard", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>Japanese-RP-Bench v2 — 反復評価<\/title>/i);
  assert.match(html, /日本語ロールプレイLLM 反復評価/);
  assert.match(html, /Grok 4\.5/);
  assert.match(html, /Hy3/);
  assert.match(html, /Qwen3\.7 Max/);
  assert.match(html, /Qwen3\.8 Max/);
  assert.match(html, /MiMo V2\.5 Pro/);
  assert.match(html, /Challenge RP Summary/);
  assert.match(html, /Major-free率/);
  assert.match(html, /95%区間/);
  assert.match(html, /aria-label="表示する評価指標"/);
  assert.doesNotMatch(
    html,
    /正式順位|GPT-5\.6 Luna|Claude Fable 5|REPEATED BENCHMARK|EXPLORE THE RESULTS|codex-preview|react-loading-skeleton|Your site is taking shape/,
  );
});

test("ships nine repeated-evaluation models with uncertainty metadata", async () => {
  const data = await readFile(new URL("../app/data.ts", import.meta.url), "utf8");
  const dashboard = await readFile(
    new URL("../app/dashboard.tsx", import.meta.url),
    "utf8",
  );
  const packageJson = await readFile(
    new URL("../package.json", import.meta.url),
    "utf8",
  );

  assert.match(data, /modelCount:\s*9/);
  assert.match(data, /scenariosPerModel:\s*6/);
  assert.match(data, /generationsPerScenario:\s*10/);
  assert.match(data, /conversationsPerModel:\s*60/);
  assert.match(data, /judgeCount:\s*3/);
  assert.match(data, /judgeOutputs:\s*7290/);
  assert.equal((data.match(/\n\s+rank:\s+\d+,/g) ?? []).length, 9);
  assert.equal((data.match(/\n\s+summary:\s+[\d.]+,/g) ?? []).length, 9);
  assert.equal((data.match(/\n\s+summaryCi95:\s*\[\d/g) ?? []).length, 9);
  assert.equal((data.match(/\n\s+firstPlaceProbability:\s+[\d.]+,/g) ?? []).length, 9);
  assert.match(dashboard, /metricKeys\.map/);
  assert.match(
    dashboard,
    /getScore\(b, metric\) - getScore\(a, metric\)/,
  );
  assert.match(dashboard, /Object\.entries\(model\.scenarios\)/);
  assert.doesNotMatch(dashboard, /legacyDimensions|正式順位|providerOptions/);
  assert.doesNotMatch(packageJson, /react-loading-skeleton/);
});
