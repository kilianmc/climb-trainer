import { formatDay } from '../plan/blueprint';
import { useVocabulary } from '../profile/api';
import { useAspectVolume } from './api';
import { aspectNames, volumeBars } from './volume';

/** Ten aspects is past where a colour per series stays legible, so they are ROWS and the count
 *  is text in every one — colour carries no value, and the chart is its own table view. */
export function AspectVolume() {
  const volume = useAspectVolume();
  const vocabulary = useVocabulary();

  // `data === undefined`, never `isError`: a failed refetch must not replace numbers being read.
  // `training_days === 0` renders nothing — ten empty bars on a fresh account is not information.
  const data = volume.data;
  if (data === undefined || vocabulary.data === undefined) return null;
  if (data.training_days === 0) return null;

  const bars = volumeBars(data.aspects, aspectNames(vocabulary.data.climbing_aspects));
  const days =
    data.training_days === 1 ? '1 training day' : `${String(data.training_days)} training days`;
  const span =
    data.from_date === null || data.to_date === null
      ? ''
      : `, ${formatDay(data.from_date)} – ${formatDay(data.to_date)}`;

  return (
    <section className="ct-app__card">
      <h2>Sets by aspect</h2>
      <p className="ct-app__muted">
        {days}
        {span}
        {data.truncated ? '. Older training is not included.' : '.'}
      </p>
      <table className="ct-app__volume">
        <caption className="ct-app__sr-only">
          Sets logged against each climbing aspect, most trained first.
        </caption>
        <thead>
          <tr>
            <th scope="col">Aspect</th>
            <th scope="col">Sets</th>
          </tr>
        </thead>
        <tbody>
          {bars.map((bar) => (
            <tr key={bar.key}>
              <th scope="row">{bar.name}</th>
              <td className="ct-app__volume-cell">
                {/* Presentation only: `sets` sits beside it as text. */}
                <span className="ct-app__volume-track">
                  <span
                    className="ct-app__volume-bar"
                    style={{ inlineSize: `${String(bar.percent)}%` }}
                  />
                </span>
                <span className="ct-app__volume-sets">{bar.sets}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
