import type { Module } from "../types";

const COLORS = ["#795bff", "#38c8c4", "#e9a64d", "#e46f91", "#6787df", "#69ad7d"];

function percentages(scores: Record<string, number>) {
  const entries = Object.entries(scores).filter(([, value]) => Number.isFinite(value) && value >= 0);
  const sum = entries.reduce((total, [, value]) => total + value, 0);
  if (!entries.length || sum <= 0) return [];

  const precise = entries.map(([label, value], index) => {
    const percent = value / sum * 100;
    return { label, value, color: COLORS[index % COLORS.length], percent, rounded: Math.floor(percent) };
  });
  let remaining = 100 - precise.reduce((total, item) => total + item.rounded, 0);
  [...precise].sort((a, b) => (b.percent - b.rounded) - (a.percent - a.rounded))
    .slice(0, remaining).forEach((item) => { item.rounded += 1; });
  return precise;
}

function isNumericScores(value: unknown): value is Record<string, number> {
  return value !== null && typeof value === "object" &&
    Object.values(value).every((score) => typeof score === "number" && Number.isFinite(score));
}

export default function ScoreChart({ module }: { module: Module }) {
  if (module.status !== "completed" || !isNumericScores(module.score) ||
      !/class scores|per-label model output/i.test(module.score_semantics ?? "")) return null;

  const items = percentages(module.score);
  if (!items.length) return null;
  let cursor = 0;
  const stops = items.map((item) => {
    const start = cursor;
    cursor += item.percent;
    return `${item.color} ${start}% ${cursor}%`;
  }).join(", ");

  return (
    <section className="score-panel" aria-label="Supported model score breakdown">
      <div className="score-panel-heading">
        <div><h2>Model score breakdown</h2><p>Normalized from this model's returned class scores; not calibrated probabilities.</p></div>
        <span>{module.name}</span>
      </div>
      <div className="score-panel-content">
        <div className="score-donut" role="img" aria-label={items.map((item) => `${item.label}: ${item.rounded}%`).join(", ")}
          style={{ background: `conic-gradient(${stops})` }}>
          <span>Model<br />scores</span>
        </div>
        <ul className="score-legend">{items.map((item) => (
          <li key={item.label}><span className="score-swatch" style={{ background: item.color }} />
            <span>{item.label}</span><b>{item.rounded}%</b></li>
        ))}</ul>
      </div>
      <p className="score-note">{module.score_semantics} Score distribution is shown only for labels the configured model returned.</p>
    </section>
  );
}
