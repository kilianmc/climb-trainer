import { describe, expect, it } from 'vitest';

import type { AspectVolume, ReferenceRow } from '../api/types';
import { aspectNames, volumeBars } from './volume';

function row(id: number, key: string, name: string): ReferenceRow {
  return { id, key, name, description: '' };
}

function volume(aspect_key: string, sets: number): AspectVolume {
  return { aspect_key, sets };
}

const NAMES = aspectNames([
  row(1, 'finger_strength', 'Finger strength'),
  row(2, 'power', 'Power'),
  row(3, 'endurance', 'Endurance'),
]);

describe('volumeBars', () => {
  it('orders the aspects by volume, busiest first', () => {
    const bars = volumeBars(
      [volume('power', 2), volume('finger_strength', 9), volume('endurance', 5)],
      NAMES,
    );

    expect(bars.map((bar) => bar.key)).toEqual(['finger_strength', 'endurance', 'power']);
  });

  it('leaves equal volumes in the order the server sent them', () => {
    const bars = volumeBars(
      [volume('endurance', 4), volume('finger_strength', 4), volume('power', 4)],
      NAMES,
    );

    expect(bars.map((bar) => bar.key)).toEqual(['endurance', 'finger_strength', 'power']);
  });

  it('scales every bar against the busiest aspect rather than against 100', () => {
    const bars = volumeBars([volume('finger_strength', 8), volume('power', 2)], NAMES);

    expect(bars.map((bar) => bar.percent)).toEqual([100, 25]);
  });

  it('gives an untrained aspect a zero bar rather than dropping its row', () => {
    const bars = volumeBars([volume('finger_strength', 3), volume('power', 0)], NAMES);

    expect(bars.map((bar) => [bar.key, bar.sets, bar.percent])).toEqual([
      ['finger_strength', 3, 100],
      ['power', 0, 0],
    ]);
  });

  it('divides by no zero when nothing at all is logged', () => {
    const bars = volumeBars([volume('finger_strength', 0), volume('power', 0)], NAMES);

    expect(bars.map((bar) => bar.percent)).toEqual([0, 0]);
  });

  it('reads an aspect the vocabulary has not caught up with from its own key', () => {
    const bars = volumeBars([volume('core_tension', 4)], NAMES);

    expect(bars[0]?.name).toBe('Core tension');
  });
});
