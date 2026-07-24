/** "Why this prediction" list (explainable AI). Floodlight skin: each reason is
 *  a two-column sign+text row (prototype §257). `reasons` are plain strings with
 *  no polarity field, so the sign stays a uniform lime `+` supporting-point
 *  marker -- we never fabricate an against/negative signal the data doesn't
 *  carry. Pure server component. */
export function ReasonsList({ reasons }: { reasons: string[] }) {
  return (
    <ul className="flex flex-col gap-[7px]">
      {reasons.map((r, i) => (
        <li key={i} className="flex gap-[9px]">
          <span className="font-bold text-lime-deep" aria-hidden>
            +
          </span>
          <span className="text-[12.5px] leading-[1.5] text-foreground/85">{r}</span>
        </li>
      ))}
    </ul>
  );
}
