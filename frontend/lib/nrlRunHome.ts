/** Client for the finals-race predictor's conditional projections (design doc:
 *  NRL Round Tips, Slice 3 "the finals-race machine"). GET-only -- mirrors
 *  lib/nrlTips.ts's convention of one thin function per endpoint, via
 *  session.ts's `request` for uniform timeout/ApiError handling. */
import { request } from "./session";
import type { NrlConditionalProjectionsResponse } from "./types";

/** `picks` must already be in the backend's exact `<match_id><h|a>,...`
 *  encoding (see lib/nrlRunHomePicks.ts's encodePicks) -- pass "" for the
 *  unconditioned baseline. */
export const getNrlConditionalProjections = (season: number, picks: string) =>
  request<NrlConditionalProjectionsResponse>(
    `/api/nrl/projections/conditional?${new URLSearchParams({
      season: String(season),
      ...(picks ? { picks } : {}),
    })}`,
  );
