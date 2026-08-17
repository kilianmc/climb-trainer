import { createMemoryHistory, type RouterHistory } from '@tanstack/react-router';

/** The standalone deployment's origin — where a link opened outside the shell must land. */
export const STANDALONE_ORIGIN = 'https://climb.kilianmc.com';

/**
 * Memory history for the federated mount, with `<Link>` hrefs rendered as absolute
 * standalone URLs. Relative hrefs resolve against the HOST document, so cmd-click,
 * middle-click and "copy link address" would leave the viewer for a 404 on
 * kilianmc.com (issue #16). Left-clicks are unaffected: only `<Link>` reads
 * `createHref`, while `push`/`replace` get the raw path.
 *
 * `createMemoryHistory` hardcodes `createHref` to the identity and accepts no option for
 * it, hence the assignment. **Never spread a history object** — `location` and `length`
 * are getters, and a copy would freeze them at their initial values.
 */
export function createRemoteHistory(): RouterHistory {
  const history = createMemoryHistory({ initialEntries: ['/'] });
  history.createHref = (path) => `${STANDALONE_ORIGIN}${path}`;
  return history;
}
