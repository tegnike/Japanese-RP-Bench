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
  assert.match(html, /<title>Japanese-RP-Bench v2 — 最新ベンチマーク<\/title>/i);
  assert.match(html, /EXPLORE THE RESULTS/);
  assert.match(html, /最新ベンチマーク結果/);
  assert.match(html, /GPT-5\.4 mini/);
  assert.match(html, /Claude Haiku 4\.5/);
  assert.match(html, /Claude Fable 5/);
  assert.match(html, /RP Balance/);
  assert.match(html, /aria-label="表示する評価指標"/);
  assert.doesNotMatch(
    html,
    /キャラクターを守り抜ける|ALL SCORES|HOW TO READ|codex-preview|react-loading-skeleton|Your site is taking shape/,
  );
});

test("ships 13 official models and one Fable reference result", async () => {
  const data = await readFile(new URL("../app/data.ts", import.meta.url), "utf8");
  const dashboard = await readFile(
    new URL("../app/dashboard.tsx", import.meta.url),
    "utf8",
  );
  const packageJson = await readFile(
    new URL("../package.json", import.meta.url),
    "utf8",
  );

  assert.match(data, /modelCount:\s*13/);
  assert.match(data, /referenceModelCount:\s*1/);
  assert.match(data, /scenariosPerModel:\s*36/);
  assert.match(data, /judgeCount:\s*3/);
  assert.equal((data.match(/\n\s+rank:\s+\d+,/g) ?? []).length, 13);
  assert.equal((data.match(/\n\s+rank:\s+null,/g) ?? []).length, 1);
  assert.equal((data.match(/\n\s+balance:\s+[\d.]+,/g) ?? []).length, 14);
  assert.match(dashboard, /metricKeys\.map/);
  assert.match(
    dashboard,
    /getScore\(b, metric\) - getScore\(a, metric\)/,
  );
  assert.doesNotMatch(dashboard, /metric === "balance" \? a\.rank/);
  assert.match(dashboard, /Object\.entries\(model\.tracks\)/);
  assert.match(dashboard, /Object\.entries\(model\.legacyDimensions\)/);
  assert.doesNotMatch(packageJson, /react-loading-skeleton/);
});
