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
const sortResults = (metric: ScoreKey) =>
  [...results].sort((a, b) => getScore(b, metric) - getScore(a, metric));

const metricEntries = (
  result: ModelResult,
): [Exclude<ScoreKey, "summary">, number][] => [
  ["roleFidelity", result.metrics.roleFidelity],
  ["quality", result.metrics.quality],
  ["personaStability", result.metrics.personaStability],
  ["robustness", result.metrics.robustness],
  ["recovery", result.metrics.recovery],
];

const scenarioLabels: Record<keyof ModelResult["scenarios"], string> = {
  careerMentor: "キャリアメンター",
  windGuide: "風の案内人",
  museumCurator: "美術館キュレーター",
  teaRoom: "茶房・12ターン",
  nikechanBaseline: "AIニケ・通常",
  nikechanAdversarial: "AIニケ・人格置換",
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
          <span>Major-free率</span>
          <strong>
            {model.majorFreeRate.toFixed(1)}
            <small> %</small>
          </strong>
        </div>
        <div>
          <span>Major率</span>
          <strong className={model.majorRate > 25 ? "warning" : ""}>
            {model.majorRate.toFixed(1)}
            <small> / 100会話</small>
          </strong>
        </div>
        <div>
          <span>1位確率</span>
          <strong>
            {model.firstPlaceProbability.toFixed(1)}
            <small> %</small>
          </strong>
        </div>
      </div>

      <p className="incomplete-note">
        RP Summary 95%区間: {model.summaryCi95[0].toFixed(1)}–
        {model.summaryCi95[1].toFixed(1)}
      </p>

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
            <span className="eyebrow">6 SCENARIOS</span>
            <h3>シナリオ別RP Summary</h3>
          </div>
        </div>
        <div className="track-grid">
          {(Object.entries(model.scenarios) as [keyof ModelResult["scenarios"], number][]).map(
            ([key, value]) => {
              const comparison = compareModel?.scenarios[key];
              const difference = comparison === undefined ? null : value - comparison;
              return (
                <div className="track-row" key={key}>
                  <span>{scenarioLabels[key]}</span>
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
    </aside>
  );
}

export function Dashboard() {
  const [metric, setMetric] = useState<ScoreKey>("summary");
  const [selectedId, setSelectedId] = useState(results[0].id);
  const [compareId, setCompareId] = useState(results[1].id);

  const visibleResults = useMemo(() => sortResults(metric), [metric]);

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

  return (
    <main className="results-page">
      <section className="leaderboard-shell">
        <div className="leaderboard-intro">
          <div>
            <span className="eyebrow">REPEATED BENCHMARK</span>
            <h1>日本語ロールプレイLLM 反復評価</h1>
            <p>
              {benchmarkMeta.updatedAt} · {benchmarkMeta.modelCount}モデル ×
              {benchmarkMeta.scenariosPerModel}シナリオ ×
              {benchmarkMeta.generationsPerScenario}生成 · {benchmarkMeta.judgeCount} Judge
            </p>
            <p className="incomplete-note">{benchmarkMeta.note}</p>
          </div>
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
                        総合順位 #{result.rank} · Major-free {result.majorFreeRate.toFixed(1)}%
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
              各モデル名の下にMajor-free率、Major率、RP Summaryを順に使った総合順位を表示します。
              8モデル28ペア×8指標の比較では、Holm補正後に優位と判定できた組み合わせは0件です。
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
