/* What an `intensity_pct` is a percentage OF. `PrescriptionTemplate` in `server/models.py`
   says the anchor needs no column because it follows from `protocol_kind`; this is that rule. */
import type { ProtocolKind } from '../api/types';

/** TOTAL over the enum, so no kind can arrive without one. Only `max_hang`, `repeaters`,
 *  `hold` and `straight_sets` carry an `intensity_pct` today; the other five are provisional. */
export const INTENSITY_ANCHORS: Record<ProtocolKind, string> = {
  max_hang: 'of your best hang',
  repeaters: 'of your best hang',
  hold: 'of your best hang',
  straight_sets: 'of your training max',
  intervals: 'of the hardest you could sustain for one interval',
  circuit: 'of the hardest circuit you could finish',
  laps: 'of the hardest grade you could lap',
  limit_boulder: 'of your limit grade',
  other: 'of your best effort at this exercise',
};

/** The words that follow the number, so `90%` never stands alone. */
export function intensityAnchor(kind: ProtocolKind): string {
  return INTENSITY_ANCHORS[kind];
}
