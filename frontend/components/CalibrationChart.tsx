"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export interface ReliabilityBin {
  mean_predicted: number;
  empirical_freq: number;
  count: number;
}

/** Reliability (calibration) curve: predicted probability vs how often it
 *  actually happened. A perfectly calibrated model tracks the dashed y = x line. */
export function CalibrationChart({ bins }: { bins: ReliabilityBin[] }) {
  const data = bins.map((b) => ({
    predicted: Math.round(b.mean_predicted * 100),
    observed: Math.round(b.empirical_freq * 100),
    perfect: Math.round(b.mean_predicted * 100),
    count: b.count,
  }));
  const height = 300;

  return (
    <div style={{ width: "100%", height }}>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 24, left: 4 }}>
          <CartesianGrid stroke="hsl(153 18% 18%)" strokeDasharray="3 3" />
          <XAxis
            dataKey="predicted"
            type="number"
            domain={[0, 100]}
            tickCount={6}
            unit="%"
            tick={{ fontSize: 11, fill: "hsl(150 8% 60%)" }}
            tickLine={false}
            label={{
              value: "Predicted probability",
              position: "insideBottom",
              offset: -12,
              style: { fill: "hsl(150 8% 60%)", fontSize: 12 },
            }}
          />
          <YAxis
            domain={[0, 100]}
            tickCount={6}
            unit="%"
            tick={{ fontSize: 11, fill: "hsl(150 8% 60%)" }}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip
            contentStyle={{
              background: "hsl(156 22% 9%)",
              border: "1px solid hsl(153 18% 18%)",
              borderRadius: 12,
              fontSize: 12,
            }}
            labelStyle={{ color: "hsl(150 20% 96%)" }}
            formatter={(v: number, name: string) => [`${v}%`, name === "observed" ? "Actually happened" : "Perfect"]}
            labelFormatter={(v) => `Predicted ~${v}%`}
          />
          <Line
            type="monotone"
            dataKey="perfect"
            stroke="hsl(150 8% 45%)"
            strokeDasharray="5 5"
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="observed"
            stroke="hsl(84 78% 55%)"
            strokeWidth={2.5}
            dot={{ r: 3, fill: "hsl(84 78% 55%)" }}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
