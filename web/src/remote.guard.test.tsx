import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';

import ClimbTrainerApp from './remote';

/**
 * The federated mount runs on the kilianmc.com origin, so each of these would damage
 * the live portfolio rather than this app: a service worker scoped to kilianmc.com
 * intercepting its requests, a navigation yanking the shell to another URL, or an
 * un-namespaced key colliding with the portfolio's own storage.
 *
 * Low likelihood, severe blast radius, and nothing in the type system or a lint rule
 * catches it — which is why it is a test. Spies rather than a source scan, because the
 * realistic regression is PR #7 putting SW registration in a module BOTH entries
 * import, and only a runtime check sees that.
 */
let register: MockInstance;
let pushState: MockInstance<History['pushState']>;
let replaceState: MockInstance<History['replaceState']>;
let setItem: MockInstance<Storage['setItem']>;

beforeEach(() => {
  register = vi.fn();
  // jsdom has no ServiceWorkerContainer at all, so it has to be supplied to be spied on.
  Object.defineProperty(navigator, 'serviceWorker', {
    value: { register, ready: Promise.resolve(), controller: null },
    configurable: true,
  });

  pushState = vi.spyOn(window.history, 'pushState');
  replaceState = vi.spyOn(window.history, 'replaceState');
  setItem = vi.spyOn(Storage.prototype, 'setItem');

  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: 'ok' }), {
        headers: { 'content-type': 'application/json' },
      }),
    ),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('the federated entry', () => {
  it('mounts, navigates and unmounts without touching the host origin', async () => {
    const before = window.location.href;
    const { unmount } = render(<ClimbTrainerApp />);

    await screen.findByRole('heading', { name: 'climb-trainer' });
    // A real navigation is the case that would reach history.pushState if this entry
    // were ever handed a browser history by mistake.
    fireEvent.click(screen.getByRole('link', { name: 'Plan' }));
    await screen.findByRole('heading', { name: 'Plan' });
    unmount();

    expect(register).not.toHaveBeenCalled();
    expect(pushState).not.toHaveBeenCalled();
    expect(replaceState).not.toHaveBeenCalled();
    expect(window.location.href).toBe(before);
  });

  it('writes no un-namespaced localStorage key', async () => {
    render(<ClimbTrainerApp />);
    await screen.findByRole('heading', { name: 'climb-trainer' });

    const keys = setItem.mock.calls.map(([key]) => key);
    expect(keys.filter((key) => !key.startsWith('ct:'))).toEqual([]);
  });
});
