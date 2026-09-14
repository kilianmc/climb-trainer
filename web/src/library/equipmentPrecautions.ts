/* Safety copy authored ONCE PER GEAR (Kilian), keyed on `equipment.key`: the risk is the board's,
   not each protocol's. Guarded, DEFINITION trap included, by tests/test_equipment_precautions.py. */

/** `equipment.key` -> the precaution every exercise requiring that row renders. */
export const EQUIPMENT_PRECAUTIONS = {
  hangboard:
    'Warm up before you hang: several minutes of easy climbing or pulling, then two or three easier hangs working up to the prescribed load. Fingers take load far faster than they warm up, and the first hard set is where pulleys go.',
  campus_board:
    'A campus board is the fastest loading in this app, so never start one cold: warm up until easy climbing feels smooth, then take a few controlled pulls before a single dynamic one. Stop the session while the contact still feels sharp rather than when it stops working.',
  no_hang_device:
    'Nothing is suspended here, so the load never warns you: warm the hands up first and add weight in small steps. A no-hang reaches a maximum pull long before the fingers have agreed to one.',
} as const satisfies Record<string, string>;

/** The precautions this exercise's gear owes the reader, in the order the payload listed it.
 *  An id with no key, or gear with no precaution, contributes NOTHING — never a placeholder. */
export function precautionsFor(
  equipmentIds: readonly number[],
  keys: ReadonlyMap<number, string>,
): readonly string[] {
  const found: string[] = [];
  for (const id of equipmentIds) {
    const key = keys.get(id);
    if (key !== undefined && key in EQUIPMENT_PRECAUTIONS) {
      found.push(EQUIPMENT_PRECAUTIONS[key as keyof typeof EQUIPMENT_PRECAUTIONS]);
    }
  }
  return found;
}
