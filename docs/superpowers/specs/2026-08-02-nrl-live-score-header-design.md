# NRL Live Score in Match Header

Date: 2026-08-02
Status: Approved design

## Problem

The NRL match-detail hero shows `VS` until a match is marked finished. During play,
the current score is only visible deeper in the Live section and in its pinned strip.
Users should see the live result in the primary matchup card shown at the top of the
page, and it should update without a page reload.

## User experience

- Before kickoff, preserve the current matchup card: team crests, `VS`, model pick,
  probability bar, and expected margin.
- While the match is live:
  - show a pulsing `LIVE · <minute>′` status badge above the teams;
  - replace `VS` with the current `<home score>–<away score>`;
  - retain the probability bar, but label the call `Pre-match model pick` so it cannot
    be mistaken for an in-play probability;
  - refresh the score and minute automatically every 30 seconds.
- At full time, preserve the current final score, `Full time` badge, and model-result
  grading treatment.
- If a background refresh fails, keep the last valid score visible. The header must
  not blank, revert to `VS`, or replace the whole card with an error state.

## Architecture

Add a match-level client provider above the hero and Match Intelligence sections.
The provider owns the single call to the existing
`GET /api/nrl/matches/{match_id}/live` endpoint through the existing `useFetch`
polling hook.

The provider:

- receives the match id and server-rendered match state as its initial value;
- fetches immediately after mount;
- polls every 30 seconds unless the match is already final;
- exposes the latest `NrlLive` state through React context;
- relies on `useFetch`'s existing silent-poll behavior to retain the last successful
  payload when a later poll fails.

Two consumers use that shared state:

1. A client matchup-scoreboard component renders `VS`, live score, or final score
   according to the latest state.
2. The existing Live section stops running its own poll and renders from the same
   provider state, keeping its events card and pinned strip consistent with the hero.

This avoids duplicate requests and does not refresh the entire server page every 30
seconds. No backend or database change is required.

## State rules

| State | Hero status | Center display | Prediction label |
|---|---|---|---|
| Pre-match | none | `VS` | `<team> to win · <probability>` |
| Live | `LIVE · <minute>′` | current score | `Pre-match model pick · <team> <probability>` |
| Final | `Full time` | final score | existing called/missed verdict |

If the live endpoint temporarily has no score, render an en dash for that side rather
than inventing `0`. A minute may be omitted when the provider has not supplied one;
the badge then reads `LIVE` without a fabricated minute.

## Testing

Use test-driven development.

- Provider/component test: pre-match renders `VS`.
- Provider/component test: live state renders the score and live minute.
- Provider/component test: a later poll updates score and minute.
- Provider/component test: a failed later poll retains the last successful score.
- Page regression test: live prediction copy is explicitly labeled pre-match.
- Existing full-time tests remain unchanged and green.
- Existing Live section tests are updated to prove it consumes shared state rather
  than creating a second poller.

Before completion, run the focused match-detail tests, frontend typecheck and lint,
then the full frontend test suite.

## Scope

In scope: the NRL match-detail hero and reuse of the existing live feed within that
page. Out of scope: changing live-model calculations, polling cadence in the backend,
other fixture cards, alerts, push notifications, or score data ingestion.
