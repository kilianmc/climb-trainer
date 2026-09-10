/** Copy the app must never carry about a climber's weight — CLAUDE.md, "The app never
 *  recommends losing weight". ONE list: two copies is how one screen quietly stops checking. */
export const FORBIDDEN_COPY = [
  'lose',
  'losing',
  'lighter',
  'leaner',
  'slimmer',
  'shed',
  'overweight',
  'goal weight',
  'target weight',
  'ideal weight',
  'racing weight',
  'climbing weight',
  'bmi',
  'body fat',
] as const;

/** Which banned terms this text actually carries, in list order. **Whole words**, plus a plural:
 *  a bare substring flagged "dashed", "finished" and "close" — false alarms, not copy. */
export function forbiddenCopyHits(text: string): string[] {
  return FORBIDDEN_COPY.filter((term) => new RegExp(`\\b${term}s?\\b`, 'i').test(text));
}
