"use client";

import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { FeatureWeight } from "@/lib/types";

const LABELS: Record<string, string> = {
  elo_gap: "Elo gap",
  form_last10: "Recent form",
  head_to_head: "Head-to-head",
  host_advantage: "Host advantage",
  goals_for_avg: "Scoring rate",
};

/** Horizontal bar chart of the top factors behind a prediction (PRD §12). */
export function FeatureImportanceChart({ features }: { features: FeatureWeight[] }) {
  if (!features.length) return null;
  const data = features.map((f) => ({
    name: LABELS[f.name] ?? f.name,
    weight: Math.round(f.weight * 100),
  }));

  return (
    <div style={{ width: "100%", height: Math.max(120, data.length * 44) }}>
      <ResponsiveContainer>
        <BarChart data={data} layout="vertical" margin={{ left: 12, right: 24 }}>
          <XAxis type="number" hide domain={[0, 100]} />
          <YAxis
            type="category"
            dataKey="name"
            width={100}
            tick={{ fontSize: 12 }}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip formatter={(v) => `${v}%`} cursor={{ fill: "rgba(0,0,0,0.04)" }} />
          <Bar dataKey="weight" radius={[0, 4, 4, 0]}>
            {data.map((_, i) => (
              <Cell key={i} fill="hsl(142 71% 45%)" />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
