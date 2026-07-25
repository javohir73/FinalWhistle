import { ClubBadge } from "@/components/ClubBadge";
import { Flag } from "@/components/Flag";
import { localFlag } from "@/lib/flags";

/**
 * Chooses the right visual identity for a football team name: national teams
 * keep their flag, while known domestic clubs use their crest. This lets the
 * same Floodlight components serve WC26 and league fixtures without showing
 * misleading initial bubbles for Arsenal, Liverpool, and the rest.
 */
export function TeamBadge({
  team,
  size = 28,
  className,
}: {
  team: string;
  size?: number;
  className?: string;
}) {
  return localFlag(team) ? (
    <Flag team={team} size={size} className={className} />
  ) : (
    <ClubBadge name={team} size={size} className={className} />
  );
}
