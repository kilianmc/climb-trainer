import type { ReactNode } from 'react';

import type { ItemStatus } from './runStore';
import type { ItemView } from './useSessionRun';

export const STATE_LABEL: Record<ItemStatus, string> = {
  pending: 'Not started',
  running: 'In progress',
  completed: 'Completed',
  skipped: 'Skipped',
};

/** One row of the session's list. The live player and the finished card share it, so the
 *  `data-state` palette in `_session.scss` has one markup to colour rather than two. */
export function ItemRow({ item, children }: { item: ItemView; children?: ReactNode }) {
  return (
    <li className="ct-app__item" data-state={item.status}>
      <div className="ct-app__item-head">
        <span className="ct-app__item-name">{item.label}</span>
        <span className="ct-app__item-state">{STATE_LABEL[item.status]}</span>
      </div>
      {/* ⚠️ No attempt count. A climber restarting a block does not need telling it is their
          third go at it, and the ordinal bookkeeping that number came from is an internal
          `set_index` concern (`RunItem.setIndexOffset`), not something to put on a screen. */}
      <p className="ct-app__item-meta">
        {String(item.setCount)} set{item.setCount === 1 ? '' : 's'}
      </p>
      {children}
    </li>
  );
}
