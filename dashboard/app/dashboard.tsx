"use client";

import { useMemo, useState } from "react";
import {
  benchmarkMeta,
  getScore,
  metricMeta,
  results,
  type ModelResult,
  type Provider,
  type ScoreKey,
} from "./data";

const metricKeys = Object.keys(metricMeta) as ScoreKey[];
const providerOptions: { value: "all" | Provider; label: string }[] = [
  { value: "all", label: "すべての経路" },
  { value: "openai", label: "OpenAI" },
  { value: "google", label: "Google" },
  { value: "anthropic", label: "Anthropic" },
  { value: "opencode", label: "OpenCode Go" },
];

const filterAndSortResults = (provider: "all" | Provider, metric: ScoreKey) => {
  const filtered =
    provider === "all"
      ? results
      : results.filter((result) => result.provider === provider);
  return [...filtered].sort((a, b) => getScore(b, metric) - getScore(a, metric));
};

const metricEntries = (
  result: ModelResult,
): [Exclude<ScoreKey, "summary">, number][] => [
  ["roleFidelity", result.metrics.roleFidelity],
  ["quality", result.metrics.quality],
  ["personaStability", result.metrics.personaStability],
  ["robustness", result.metrics.robustness],
  ["recovery", result.metrics.recovery],
];

const trackLabels: Record<keyof ModelResult["tracks"], string> = {
  adversarial: "攻撃耐性",
  coreJa: "通常会話",
  custom: "カスタム人格",
  legacyBase: "従来30設定",
  multiTurn: "複数ターン",
};

const legacyLabels: Record<string, string> = {
  "Roleplay Adherence": "ロールプレイ追従",
  Consistency: "一貫性",
  "Contextual Understanding": "文脈理解",
  Expressiveness: "表現力",
  Creativity: "創造性",
  "Naturalness of Japanese": "日本語の自然さ",
  "Enjoyment of the Dialogue": "会話の楽しさ",
  "Appropriateness of Turn-Taking": "ターン進行",
};

function ScoreBar({
  value,
  tone = "violet",
  compact = false,
}: {
  value: number;
  tone?: "violet" | "cyan" | "coral" | "lime";
  compact?: boolean;
}) {
  return (
    <span className={`score-track ${compact ? "is-compact" : ""}`}>
      <span
        className={`score-fill tone-${tone}`}
        style={{ width: `${Math.max(0, Math.min(100, value))}%` }}
      />
    </span>
  );
}

function ProviderMark({ provider }: { provider: Provider }) {
  return <span className={`provider-mark provider-${provider}`} aria-hidden />;
}

function ModelDetail({
  model,
  compareModel,
  onCompareChange,
}: {
  model: ModelResult;
  compareModel: ModelResult | null;
  onCompareChange: (id: string) => void;
}) {
  const strengths = [...metricEntries(model)].sort((a, b) => b[1] - a[1]);
  const best = strengths[0];
  const weakest = strengths[strengths.length - 1];

  return (
    <aside className="detail-panel" aria-label={`${model.name}の詳細`}>
      <div className="detail-heading">
        <div>
          <span className="eyebrow">MODEL PROFILE</span>
          <h2>{model.name}</h2>
          <span className="provider-label">
            <ProviderMark provider={model.provider} />
            {model.providerLabel}
          </span>
        </div>
        <div className="summary-orb">
          <strong>{model.summary.toFixed(1)}</strong>
          <span>RP Summary</span>
        </div>
      </div>

      <div className="gate-grid">
        <div>
          <span>重大違反なし</span>
          <strong>
            {model.majorFree}
            <small> / {model.scenarios}</small>
          </strong>
        </div>
        <div>
          <span>重大違反</span>
          <strong className={model.major > 5 ? "warning" : ""}>
            {model.major}
            <small> 件</small>
          </strong>
        </div>
        <div>
          <span>旧8指標平均</span>
          <strong>
            {model.legacyAverage.toFixed(3)}
            <small> / 5</small>
          </strong>
        </div>
      </div>

      <section className="detail-section axes-section">
        <div className="section-heading">
          <div>
            <span className="eyebrow">5 AXES</span>
            <h3>5つの評価指標</h3>
          </div>
          <div className="axes-actions">
            <p>
              最高: {metricMeta[best[0]].short} {best[1].toFixed(1)} ／ 注意:{" "}
              {metricMeta[weakest[0]].short} {weakest[1].toFixed(1)}
            </p>
            <label className="axes-compare">
              <span className="sr-only">比較するモデル</span>
              <select
                value={compareModel?.id ?? "none"}
                onChange={(event) => onCompareChange(event.target.value)}
              >
                <option value="none">比較しない</option>
                {results
                  .filter((item) => item.id !== model.id)
                  .map((item) => (
                    <option value={item.id} key={item.id}>
                      {item.name}
                    </option>
                  ))}
              </select>
            </label>
          </div>
        </div>
        {compareModel && (
          <div className="comparison-legend">
            <span>
              <i className="legend-dot primary" />
              {model.name}
            </span>
            <span>
              <i className="legend-dot secondary" />
              {compareModel.name}
            </span>
          </div>
        )}
        <div className="metric-stack">
          {metricEntries(model).map(([key, value], index) => {
            const comparison = compareModel?.metrics[key];
            const difference = comparison === undefined ? null : value - comparison;
            return (
              <div className="metric-row" key={key}>
                <span>{metricMeta[key].short}</span>
                <div className="metric-bars">
                  <ScoreBar
                    value={value}
                    tone={index === 1 ? "coral" : "violet"}
                    compact={Boolean(compareModel)}
                  />
                  {comparison !== undefined && (
                    <ScoreBar value={comparison} tone="cyan" compact />
                  )}
                </div>
                <div className="metric-value-stack">
                  <strong>{value.toFixed(1)}</strong>
                  {difference !== null && (
                    <small className={difference >= 0 ? "positive" : "negative"}>
                      {difference >= 0 ? "+" : ""}
                      {difference.toFixed(1)}
                    </small>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <section className="detail-section tracks-section">
        <div className="section-heading">
          <div>
            <span className="eyebrow">SCENARIO TYPES</span>
            <h3>シナリオ種別ごとの役柄追従度</h3>
          </div>
        </div>
        <div className="track-grid">
          {(Object.entries(model.tracks) as [keyof ModelResult["tracks"], number][]).map(
            ([key, value]) => {
              const comparison = compareModel?.tracks[key];
              const difference = comparison === undefined ? null : value - comparison;
              return (
                <div className="track-row" key={key}>
                  <span>{trackLabels[key]}</span>
                  <div className="track-bars">
                    <ScoreBar
                      value={value}
                      tone="violet"
                      compact={Boolean(compareModel)}
                    />
                    {comparison !== undefined && (
                      <ScoreBar value={comparison} tone="cyan" compact />
                    )}
                  </div>
                  <div className="track-value-stack">
                    <strong>{value.toFixed(1)}</strong>
                    {difference !== null && (
                      <small className={difference >= 0 ? "positive" : "negative"}>
                        {difference >= 0 ? "+" : ""}
                        {difference.toFixed(1)}
                      </small>
                    )}
                  </div>
                </div>
              );
            },
          )}
        </div>
      </section>

      <section className="detail-section legacy-details">
        <div className="section-heading">
          <div>
            <span className="eyebrow">LEGACY 8</span>
            <h3>旧8指標の内訳</h3>
          </div>
        </div>
        <div className="legacy-list">
          {Object.entries(model.legacyDimensions).map(([label, value]) => {
            const comparison = compareModel?.legacyDimensions[label];
            const difference = comparison === undefined ? null : value - comparison;
            return (
              <div className="legacy-row" key={label}>
                <span>{legacyLabels[label] ?? label}</span>
                <div className="legacy-bars">
                  <ScoreBar
                    value={value * 20}
                    tone="violet"
                    compact={Boolean(compareModel)}
                  />
                  {comparison !== undefined && (
                    <ScoreBar value={comparison * 20} tone="cyan" compact />
                  )}
                </div>
                <div className="legacy-value-stack">
                  <strong>{value.toFixed(2)}</strong>
                  {difference !== null && (
                    <small className={difference >= 0 ? "positive" : "negative"}>
                      {difference >= 0 ? "+" : ""}
                      {difference.toFixed(2)}
                    </small>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </section>
    </aside>
  );
}

export function Dashboard() {
  const [metric, setMetric] = useState<ScoreKey>("summary");
  const [provider, setProvider] = useState<"all" | Provider>("all");
  const [selectedId, setSelectedId] = useState(results[0].id);
  const [compareId, setCompareId] = useState(results[1].id);

  const visibleResults = useMemo(
    () => filterAndSortResults(provider, metric),
    [metric, provider],
  );

  const selected =
    visibleResults.find((result) => result.id === selectedId) ??
    visibleResults[0] ??
    results[0];
  const compare =
    compareId === "none"
      ? null
      : results.find((result) => result.id === compareId && result.id !== selected.id) ??
        null;
  const leader = visibleResults[0];

  const selectModel = (id: string) => {
    setSelectedId(id);
    if (id === compareId) {
      setCompareId("none");
    }
  };

  const selectProvider = (nextProvider: "all" | Provider) => {
    const nextResults = filterAndSortResults(nextProvider, metric);
    const selectedIsVisible = nextResults.some((result) => result.id === selectedId);

    setProvider(nextProvider);
    if (!selectedIsVisible && nextResults[0]) {
      setSelectedId(nextResults[0].id);
      if (compareId === nextResults[0].id) {
        setCompareId("none");
      }
    }
  };

  return (
    <main className="results-page">
      <section className="leaderboard-shell">
        <div className="leaderboard-intro">
          <div>
            <h1>日本語ロールプレイLLM 最新ベンチマーク結果</h1>
            <p>
              {benchmarkMeta.updatedAt} · 正式{benchmarkMeta.modelCount}モデル + 参考
              {benchmarkMeta.referenceModelCount}モデル · 最大
              {benchmarkMeta.scenariosPerModel}シナリオ / モデル
            </p>
            <p className="incomplete-note">{benchmarkMeta.incompleteNote}</p>
          </div>
          <label className="provider-filter">
            <span>評価経路</span>
            <select
              value={provider}
              onChange={(event) =>
                selectProvider(event.target.value as "all" | Provider)
              }
            >
              {providerOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="metric-tabs" role="tablist" aria-label="表示する評価指標">
          {metricKeys.map((key) => (
            <button
              type="button"
              role="tab"
              aria-selected={metric === key}
              className={metric === key ? "active" : ""}
              onClick={() => setMetric(key)}
              key={key}
            >
              <span>{metricMeta[key].short}</span>
              <small>{metricMeta[key].label}</small>
            </button>
          ))}
        </div>

        <div className="metric-explainer">
          <span>{metricMeta[metric].label}</span>
          <p>{metricMeta[metric].description}</p>
          <strong>
            高い順 · {leader?.name} {leader ? getScore(leader, metric).toFixed(1) : "—"}
          </strong>
        </div>

        <div className="results-layout">
          <section className="rank-chart" aria-label={`${metricMeta[metric].label}の比較`}>
            <div className="chart-scale" aria-hidden>
              <span>70</span>
              <span>80</span>
              <span>90</span>
              <span>100</span>
            </div>
            <div
              className="chart-list"
              style={{
                gridTemplateRows: `repeat(${results.length}, minmax(0, 1fr))`,
              }}
            >
              {visibleResults.map((result, index) => {
                const score = getScore(result, metric);
                const visualWidth = Math.max(4, ((score - 70) / 30) * 100);
                const isSelected = selected.id === result.id;
                return (
                  <button
                    type="button"
                    className={`chart-row ${isSelected ? "selected" : ""}`}
                    onClick={() => selectModel(result.id)}
                    aria-pressed={isSelected}
                    key={result.id}
                  >
                    <span
                      className="chart-position"
                      title={`${metricMeta[metric].short}順位`}
                    >
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    <span className="chart-model">
                      <span>
                        <ProviderMark provider={result.provider} />
                        <strong>{result.name}</strong>
                      </span>
                      <small>
                        正式順位 {result.rank === null ? "-" : `#${result.rank}`} · Major{" "}
                        {result.major}
                        {result.reference ? " · 参考値" : ""}
                      </small>
                    </span>
                    <span className="chart-bar-area">
                      <span className="chart-gridlines" />
                      <span
                        className={`chart-bar provider-bg-${result.provider}`}
                        style={{ width: `${visualWidth}%` }}
                      />
                    </span>
                    <strong className="chart-value">{score.toFixed(1)}</strong>
                  </button>
                );
              })}
            </div>
            <p className="chart-note">
              左端は「{metricMeta[metric].short}」の順位です。グラフはスコアの高い順に並び、
              各モデル名の下に重大違反ゲートを含む正式順位を表示しています。参考評価の
              Claude Fable 5は正式順位を「-」としています。
            </p>
          </section>

          <ModelDetail
            model={selected}
            compareModel={compare}
            onCompareChange={setCompareId}
          />
        </div>
      </section>
    </main>
  );
}
