import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { FakeWakeLockSentinel } from '../test/setup';

import {
  KEEP_SCREEN_ON_KEY,
  getKeepScreenOn,
  releaseWakeLock,
  setKeepScreenOn,
  useWakeLock,
  wakeLockAvailable,
} from './wakeLock';

/**
 * The wake lock, and the two rules that make it honest.
 *
 * **Availability decides whether the control EXISTS** — Firefox on Android has no
 * `navigator.wakeLock` and an installed iOS PWA below 18.4 has one that never holds, and in
 * both the toggle must be absent rather than disabled.
 *
 * **`held` is the sentinel's state, never the click.** The OS releases silently on background,
 * so the tests below flip the sentinel behind the hook's back and assert the switch follows.
 */

interface NavigatorOverrides {
  userAgent?: string;
  platform?: string;
  maxTouchPoints?: number;
  standalone?: boolean;
  wakeLock?: unknown;
}

const originals = new Map<string, PropertyDescriptor | undefined>();

function override(overrides: NavigatorOverrides): void {
  for (const [key, value] of Object.entries(overrides)) {
    if (!originals.has(key)) {
      originals.set(key, Object.getOwnPropertyDescriptor(navigator, key));
    }
    Object.defineProperty(navigator, key, { value, configurable: true, writable: true });
  }
}

function restoreNavigator(): void {
  for (const [key, descriptor] of originals) {
    if (descriptor === undefined) {
      Reflect.deleteProperty(navigator, key);
    } else {
      Object.defineProperty(navigator, key, descriptor);
    }
  }
  originals.clear();
}

/** Every acquisition in one place, so a test can hand back a sentinel it still holds. */
function stubRequest(): { sentinels: FakeWakeLockSentinel[]; request: ReturnType<typeof vi.fn> } {
  const sentinels: FakeWakeLockSentinel[] = [];
  const request = vi.fn(() => {
    const sentinel = new FakeWakeLockSentinel();
    sentinels.push(sentinel);
    return Promise.resolve(sentinel);
  });
  override({ wakeLock: { request } });
  return { sentinels, request };
}

/** `sentinels[0]` with the index check the strict compiler wants. */
function only(sentinels: FakeWakeLockSentinel[]): FakeWakeLockSentinel {
  const first = sentinels[0];
  if (first === undefined) throw new Error('no sentinel was handed out');
  return first;
}

function setVisibility(state: DocumentVisibilityState): void {
  Object.defineProperty(document, 'visibilityState', { value: state, configurable: true });
  document.dispatchEvent(new Event('visibilitychange'));
}

const IOS_18_3 = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_3 like Mac OS X) AppleWebKit/605.1.15';
const IOS_18_4 = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_4 like Mac OS X) AppleWebKit/605.1.15';

beforeEach(() => {
  window.localStorage.clear();
  setKeepScreenOn(false);
  setVisibility('visible');
});

afterEach(async () => {
  await releaseWakeLock();
  restoreNavigator();
  vi.restoreAllMocks();
});

describe('wakeLockAvailable', () => {
  it('is true in a browser that implements the API', () => {
    expect(wakeLockAvailable()).toBe(true);
  });

  it('is false when navigator.wakeLock is missing — Firefox on Android', () => {
    override({ wakeLock: undefined });
    expect(wakeLockAvailable()).toBe(false);
  });

  it('is false when the API is present but request() is not a function', () => {
    override({ wakeLock: {} });
    expect(wakeLockAvailable()).toBe(false);
  });

  it('is false in an installed iOS PWA below 18.4, where the lock never holds', () => {
    override({ userAgent: IOS_18_3, standalone: true });
    expect(wakeLockAvailable()).toBe(false);
  });

  it('is true in an installed iOS PWA from 18.4 on', () => {
    override({ userAgent: IOS_18_4, standalone: true });
    expect(wakeLockAvailable()).toBe(true);
  });

  it('is true on iOS 18.3 in a browser tab — only the installed case is broken', () => {
    override({ userAgent: IOS_18_3, standalone: false });
    expect(wakeLockAvailable()).toBe(true);
  });

  it('treats an unparseable iOS version in a PWA as too old rather than guessing high', () => {
    override({ userAgent: 'Mozilla/5.0 (iPhone)', standalone: true });
    expect(wakeLockAvailable()).toBe(false);
  });
});

describe('the ct:keepScreenOn preference', () => {
  it('persists the choice and reads it back', () => {
    setKeepScreenOn(true);
    expect(window.localStorage.getItem(KEEP_SCREEN_ON_KEY)).toBe('true');
    expect(getKeepScreenOn()).toBe(true);
  });

  it('costs persistence, not the choice, when the store throws', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota');
    });
    setKeepScreenOn(true);
    expect(getKeepScreenOn()).toBe(true);
  });
});

describe('useWakeLock', () => {
  it('acquires nothing until asked, then exactly once', async () => {
    const { request } = stubRequest();
    const view = renderHook(({ wanted }) => useWakeLock(wanted), {
      initialProps: { wanted: false },
    });
    await act(async () => await Promise.resolve());
    expect(request).not.toHaveBeenCalled();

    view.rerender({ wanted: true });
    await act(async () => await Promise.resolve());
    expect(request).toHaveBeenCalledTimes(1);
    expect(view.result.current.held).toBe(true);
  });

  it('hides itself and acquires nothing when the API is absent', async () => {
    override({ wakeLock: undefined });
    const view = renderHook(() => useWakeLock(true));
    await act(async () => await Promise.resolve());
    expect(view.result.current.available).toBe(false);
    expect(view.result.current.held).toBe(false);
  });

  it('reports held=false when the OS releases behind the switch back', async () => {
    const { sentinels } = stubRequest();
    const view = renderHook(() => useWakeLock(true));
    await act(async () => await Promise.resolve());
    expect(view.result.current.held).toBe(true);

    act(() => {
      only(sentinels).osRelease();
    });
    expect(view.result.current.held).toBe(false);
    expect(view.result.current.wanted).toBe(true);
  });

  it('re-acquires on visibilitychange while the switch is on', async () => {
    const { sentinels, request } = stubRequest();
    const view = renderHook(() => useWakeLock(true));
    await act(async () => await Promise.resolve());

    act(() => {
      only(sentinels).osRelease();
      setVisibility('hidden');
    });
    await act(async () => await Promise.resolve());
    expect(request).toHaveBeenCalledTimes(1);

    act(() => {
      setVisibility('visible');
    });
    await act(async () => await Promise.resolve());
    expect(request).toHaveBeenCalledTimes(2);
    expect(view.result.current.held).toBe(true);
  });

  it('releases on unmount, so no lock outlives the run', async () => {
    const { sentinels } = stubRequest();
    const view = renderHook(() => useWakeLock(true));
    await act(async () => await Promise.resolve());
    view.unmount();
    await act(async () => await Promise.resolve());
    expect(only(sentinels).released).toBe(true);
  });

  it('releases when wanted goes false — how finish and abort let go', async () => {
    const { sentinels } = stubRequest();
    const view = renderHook(({ wanted }) => useWakeLock(wanted), {
      initialProps: { wanted: true },
    });
    await act(async () => await Promise.resolve());
    view.rerender({ wanted: false });
    await act(async () => await Promise.resolve());
    expect(only(sentinels).released).toBe(true);
    expect(view.result.current.held).toBe(false);
  });

  it('treats a rejected request() as a normal outcome, not an error', async () => {
    override({ wakeLock: { request: () => Promise.reject(new Error('low battery')) } });
    const view = renderHook(() => useWakeLock(true));
    await act(async () => await Promise.resolve());
    expect(view.result.current.available).toBe(true);
    expect(view.result.current.held).toBe(false);
  });
});
