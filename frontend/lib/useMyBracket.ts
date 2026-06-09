"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { Group, MatchSummary, SavedBracket } from "./types";
import type { BracketPayload } from "./auth";
import {
  groupTable, groupStageComplete, seedKnockouts, matchSides, champion,
  pruneKnockoutPicks, encodeBracket, decodeBracket,
  type BGroup, type GroupPicks, type KnockoutPicks, type Outcome, type Seeding,
} from "./myBracket";

const STORAGE_KEY = "finalwhistle:mybracket:v1";

interface Stored {
  groupPicks: GroupPicks;
  koPicks: KnockoutPicks;
}

/** Build the bracket model (teams + fixtures per group) from the API shapes. */
function buildGroups(groups: Group[], matches: MatchSummary[]): BGroup[] {
  return groups
    .map((g) => {
      const teams = g.standings.map((s) => ({
        id: s.team_id,
        name: s.team,
        strength: s.qualification_prob ?? 0,
      }));
      const fixtures = matches
        .filter((m) => m.group === g.name && m.teams.home && m.teams.away)
        .map((m) => ({ matchId: m.match_id, home: m.teams.home, away: m.teams.away }));
      return { letter: g.name.replace(/^Group\s+/i, "").trim(), teams, fixtures };
    })
    .sort((a, b) => a.letter.localeCompare(b.letter));
}

export function useMyBracket(groups: Group[] | null, matches: MatchSummary[] | null) {
  const model = useMemo(
    () => (groups && matches ? buildGroups(groups, matches) : []),
    [groups, matches],
  );
  const teamId = useMemo(() => {
    const m: Record<string, number> = {};
    for (const g of model) for (const t of g.teams) m[t.name] = t.id;
    return m;
  }, [model]);

  const [groupPicks, setGroupPicks] = useState<GroupPicks>({});
  const [koPicks, setKoPicks] = useState<KnockoutPicks>({});
  const [loaded, setLoaded] = useState(false);

  // Initialize once the model is available: a shared ?b= bracket takes
  // precedence over local storage (then the param is stripped so edits persist
  // cleanly and a refresh won't reload the shared copy).
  useEffect(() => {
    if (loaded || model.length === 0) return;
    let applied = false;
    try {
      const params = new URLSearchParams(window.location.search);
      const code = params.get("b");
      if (code) {
        const { groupPicks: gp, koPicks: kp } = decodeBracket(model, code);
        setGroupPicks(gp);
        setKoPicks(kp);
        applied = true;
        params.delete("b");
        const qs = params.toString();
        window.history.replaceState({}, "", window.location.pathname + (qs ? `?${qs}` : ""));
      }
    } catch {
      /* malformed share code — fall back to storage */
    }
    if (!applied) {
      try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (raw) {
          const s = JSON.parse(raw) as Stored;
          setGroupPicks(s.groupPicks ?? {});
          setKoPicks(s.koPicks ?? {});
        }
      } catch {
        /* ignore corrupt storage */
      }
    }
    setLoaded(true);
  }, [model, loaded]);

  // Persist after load.
  useEffect(() => {
    if (!loaded) return;
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ groupPicks, koPicks }));
    } catch {
      /* storage full / unavailable — non-fatal */
    }
  }, [groupPicks, koPicks, loaded]);

  const tables = useMemo(() => {
    const t: Record<string, ReturnType<typeof groupTable>> = {};
    for (const g of model) t[g.letter] = groupTable(g, groupPicks);
    return t;
  }, [model, groupPicks]);

  const complete = useMemo(() => model.length > 0 && groupStageComplete(model, groupPicks), [model, groupPicks]);
  const seeding: Seeding | null = useMemo(
    () => (complete ? seedKnockouts(model, groupPicks) : null),
    [complete, model, groupPicks],
  );

  const setGroupPick = useCallback((matchId: number, outcome: Outcome) => {
    setGroupPicks((prev) => {
      const next = { ...prev, [matchId]: outcome };
      // Group results changed -> re-seed and drop any now-invalid KO picks.
      if (groups && matches) {
        const m = buildGroups(groups, matches);
        if (groupStageComplete(m, next)) {
          setKoPicks((ko) => pruneKnockoutPicks(seedKnockouts(m, next), ko));
        } else {
          setKoPicks({});
        }
      }
      return next;
    });
  }, [groups, matches]);

  const setKoPick = useCallback((no: number, team: string) => {
    setKoPicks((prev) => {
      if (!seeding) return prev;
      const next = { ...prev, [no]: team };
      return pruneKnockoutPicks(seeding, next);
    });
  }, [seeding]);

  const reset = useCallback(() => {
    setGroupPicks({});
    setKoPicks({});
  }, []);

  const sidesFor = useCallback(
    (no: number) => (seeding ? matchSides(no, seeding, koPicks) : {}),
    [seeding, koPicks],
  );

  const shareCode = useMemo(
    () => (model.length ? encodeBracket(model, groupPicks, koPicks) : ""),
    [model, groupPicks, koPicks],
  );

  const idToName = useMemo(() => {
    const m: Record<number, string> = {};
    for (const [name, id] of Object.entries(teamId)) m[id] = name;
    return m;
  }, [teamId]);

  // Convert to/from the backend's saved-bracket shape (ids instead of names).
  const toBracketPayload = useCallback((): BracketPayload => {
    const champ = champion(koPicks);
    return {
      group_picks: Object.entries(groupPicks).map(([mid, pick]) => ({
        match_id: Number(mid), pick,
      })),
      knockout_picks: Object.entries(koPicks).flatMap(([no, name]) => {
        const id = teamId[name];
        return id ? [{ match_no: Number(no), picked_team_id: id }] : [];
      }),
      champion_team_id: champ ? teamId[champ] ?? null : null,
      encoded_state: shareCode,
    };
  }, [groupPicks, koPicks, teamId, shareCode]);

  const loadFromServer = useCallback((b: SavedBracket) => {
    const gp: GroupPicks = {};
    for (const p of b.group_picks) gp[p.match_id] = p.pick;
    const kp: KnockoutPicks = {};
    for (const p of b.knockout_picks) {
      const name = idToName[p.picked_team_id];
      if (name) kp[p.match_no] = name;
    }
    setGroupPicks(gp);
    setKoPicks(kp);
  }, [idToName]);

  const groupsPicked = useMemo(
    () => model.reduce((n, g) => n + g.fixtures.filter((f) => groupPicks[f.matchId]).length, 0),
    [model, groupPicks],
  );
  const totalGroupFixtures = useMemo(
    () => model.reduce((n, g) => n + g.fixtures.length, 0),
    [model],
  );

  return {
    model, tables, teamId,
    groupPicks, koPicks,
    complete, seeding,
    setGroupPick, setKoPick, reset,
    sidesFor,
    champion: champion(koPicks),
    shareCode,
    toBracketPayload,
    loadFromServer,
    progress: { groupsPicked, totalGroupFixtures },
  };
}
