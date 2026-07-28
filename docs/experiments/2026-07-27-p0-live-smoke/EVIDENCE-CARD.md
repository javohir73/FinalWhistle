# P0 read-only live venue smoke — 2026-07-27

## Scope

Read-only public catalogue, order-book, market-state, and settlement requests.
The smoke used no venue credentials, trading endpoints, orders, production
database, paid infrastructure, or deployment.

## Kalshi

- Complete discovery returned 1,890 soccer markets across 35 cursor-paginated
  event pages: 1,862 active, 17 finalized, and 11 determined.
- The measured smoke made 39 requests, received HTTP 200 for all of them, read
  139,730,918 response bytes, and completed in 15.742 seconds.
- Sample active market `KXWCCAREERGOALS-KMBAPPE-30` returned a complete normalized
  Yes book with 15 bid levels and 7 ask levels. Best bid/ask were 0.82/0.83 and
  last was 0.83.
- A bounded five-page terminal-market lookup found finalized soccer market
  `KXLIGAMXTEAMTOTAL-26JUL26NCXMON-NCX4`; the adapter normalized its result to
  `settled`, outcome `no`, settled at `2026-07-27T01:06:26.056937Z`.

## Polymarket

- Complete discovery returned 46,960 soccer markets across 39 keyset-paginated
  event pages: 44,571 active, 591 inactive, 1,797 closed, and 1 archived.
- Seventeen malformed catalogue markets whose end preceded their start were
  rejected visibly rather than silently stored or guessed.
- The measured smoke made 43 requests, received HTTP 200 for all of them, read
  209,370,324 response bytes, and completed in 29.911 seconds.
- Sample active condition
  `0x87091dc5932f015d80c40e71e47cb043c3f8b6098484eb5bc3943cf35ee9afc1`
  returned a complete normalized Yes book with 72 bid levels and 143 ask levels.
  Best bid/ask were 0.100/0.101 and the source timestamp was
  `2026-07-27T01:20:37.873Z`.
- A bounded recent-closed-event lookup found resolved condition
  `0x6695d4275bc981644db15f57032fc81b9b7aba6f7eb7f392264381ff099b800a`;
  the adapter normalized it to `settled`, outcome `Yes`.

## Clock and in-play state

Both sampled live books had explicit null `is_in_play` and `clock_state` fields.
The adapter preserved those nulls. This validates fail-closed behavior but does
not answer whether Polymarket remains usable after kickoff; OQ-3 still requires
a prospective listed-match capture spanning kickoff.

## Verdict

`pass` for the bounded task 5.2 live API smoke. The catalogue volume also
confirms that an unfiltered all-market worker would be operationally unsafe:
eligibility must be bounded before a full-weekend run.
