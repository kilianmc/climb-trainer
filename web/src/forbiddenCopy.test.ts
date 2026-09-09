import { describe, expect, it } from 'vitest';

import { forbiddenCopyHits } from './test/forbiddenCopy';

/** The weight-copy guard's own guard. Two screens assert an ABSENCE against this list, so it
 *  has to catch real copy AND leave ordinary words alone — a false alarm distorts the UI. */
describe('the weight-copy matcher', () => {
  it('catches copy that recommends losing weight, inflections included', () => {
    const sample =
      'Your goal weight is 65 kg — lose 6 kg to be a lighter, leaner climber. ' +
      'She sheds 2 kg a month and her BMI drops.';
    expect(forbiddenCopyHits(sample)).toEqual([
      'lose',
      'lighter',
      'leaner',
      'shed',
      'goal weight',
      'bmi',
    ]);
  });

  // ⚠️ The regression that made this file exist: a bare substring flagged the chart legend's
  // "dashed", and a Close control's "close", so the copy got bent to satisfy the test.
  it('leaves ordinary words that merely CONTAIN a banned term alone', () => {
    const innocent =
      'Close this dashed line. The session is finished and the hold is polished. ' +
      '<span class="ct-app__chartline--dashes">dotted line</span>';
    expect(forbiddenCopyHits(innocent)).toEqual([]);
  });
});
