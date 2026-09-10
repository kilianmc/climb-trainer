/** Bars are shares of the BUSIEST aspect, never of a target: nothing prescribes an aspect's
 *  volume, so `ProfileProgress`'s `progressbar` + `aria-valuemax` would assert a goal. */
import type { AspectVolume, ReferenceRow } from '../api/types';
import { humanise } from '../library/browse';

export interface VolumeBar {
  key: string;
  name: string;
  sets: number;
  /** 0-100: this aspect's share of the busiest one. 0 for every aspect when nothing is logged. */
  percent: number;
}

/** `key -> name`. Not `browse.ts`'s `nameIndex`, which is keyed by `id`: this payload carries
 *  `aspect_key`, because `key` is the data contract and a serial primary key is not. */
export function aspectNames(rows: readonly ReferenceRow[]): ReadonlyMap<string, string> {
  return new Map(rows.map((row) => [row.key, row.name]));
}

export function volumeBars(
  aspects: readonly AspectVolume[],
  names: ReadonlyMap<string, string>,
): readonly VolumeBar[] {
  const busiest = aspects.reduce((most, aspect) => Math.max(most, aspect.sets), 0);
  return [...aspects]
    .sort((first, second) => second.sets - first.sets)
    .map((aspect) => ({
      key: aspect.aspect_key,
      // `humanise` rather than dropping the row: a dropped aspect would understate the chart.
      name: names.get(aspect.aspect_key) ?? humanise(aspect.aspect_key),
      sets: aspect.sets,
      percent: busiest === 0 ? 0 : Math.round((aspect.sets / busiest) * 100),
    }));
}
