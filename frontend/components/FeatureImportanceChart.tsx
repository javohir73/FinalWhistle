"use client";

import {
  Bar,
  BarChart,
  Cell,
  LabelList,
  ResponsiveContainer,
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

/** Horizontal bar chart of the top factors behind a prediction. */
export function FeatureImportanceChart({ features }: { features: FeatureWeight[] }) {
  if (!features.length) return null;
  const data = features.map((f) => ({
    name: LABELS[f.name] ?? f.name,
    weight: Math.round(f.weight * 100),
  }));
  const height = Math.max(120, data.length * 46);

  return (
    <div style={{ width: "100%", height }}>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} layout="vertical" margin={{ left: 8, right: 36 }}>
          <XAxis type="number" hide domain={[0, 100]} />
          <YAxis
            type="category"
            dataKey="name"
            width={104}
            tick={{ fontSize: 12, fill: "hsl(150 8% 70%)" }}
            axisLine={false}
            tickLine={false}
          />
          <Bar dataKey="weight" radius={[0, 6, 6, 0]} barSize={18}>
            {data.map((_, i) => (
              <Cell key={i} fill="hsl(84 78% 55%)" fillOpacity={1 - i * 0.16} />
            ))}
            <LabelList
              dataKey="weight"
              position="right"
              formatter={(v: number) => `${v}%`}
              style={{ fill: "hsl(150 8% 70%)", fontSize: 11, fontWeight: 600 }}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
