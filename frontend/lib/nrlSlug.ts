/** Team-name -> URL slug. MUST stay in lockstep with _slugify() in
 *  backend/app/api/sports.py: lowercase, runs of non-alphanumerics -> "-",
 *  trimmed. "Wests Tigers" -> "wests-tigers". */
export function slugify(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}
