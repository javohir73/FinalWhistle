import Link from "next/link";
import type { StandingRow } from "@/lib/types";
import { QualificationBar } from "./QualificationBar";

/** Predicted standings table with a qualification bar per team (PRD §12). */
export function GroupTable({ standings }: { standings: StandingRow[] }) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b border-border text-left text-xs text-foreground/60">
          <th className="py-2 pr-2 font-medium">Team</th>
          <th className="px-1 text-center font-medium" title="Predicted points">
            Pts
          </th>
          <th className="px-1 text-center font-medium" title="Predicted goal difference">
            GD
          </th>
          <th className="py-2 pl-2 text-right font-medium">Qualify</th>
        </tr>
      </thead>
      <tbody>
        {standings.map((row, i) => (
          <tr
            key={row.team_id}
            className={i < 2 ? "border-b border-border/50 bg-win/5" : "border-b border-border/50"}
          >
            <td className="py-2 pr-2">
              <Link href={`/team/${row.team_id}`} className="hover:underline">
                {row.team}
              </Link>
            </td>
            <td className="px-1 text-center tabular-nums">{row.points}</td>
            <td className="px-1 text-center tabular-nums">
              {row.goal_diff > 0 ? `+${row.goal_diff}` : row.goal_diff}
            </td>
            <td className="py-2 pl-2">
              <div className="flex justify-end">
                <QualificationBar prob={row.qualification_prob} />
              </div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
