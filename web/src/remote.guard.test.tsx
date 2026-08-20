import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';

/**
 * The federated mount runs on the kilianmc.com origin, so each of these damages the live
 * portfolio rather than this app: a service worker scoped to kilianmc.com intercepting
 * its requests, a navigation yanking the shell to another URL, or storage writes and
 * deletions hitting the portfolio's own keys.
 *
 * Low likelihood, severe blast radius, and nothing in the type system or a lint rule
 * catches it. Spies and final-state checks rather than a source scan, because the
 * realistic regression is a module BOTH entries import.
 */

/** Stands in for a key the portfolio already owns on this origin. */
const HOST_KEY = 'portfolio-theme';
const HOST_VALUE = 'dark';

let register: MockInstance;
let pushState: MockInstance<History['pushState']>;
let replaceState: MockInstance<History['replaceState']>;
let setItem: MockInstance<Storage['setItem']>;
let removeItem: MockInstance<Storage['removeItem']>;
let clear: MockInstance<Storage['clear']>;

/**
 * Storage has four mutation paths and they fail differently, so all four are watched:
 * `Object.keys` catches the final state (including `localStorage.foo = 'x'`, which writes
 * the value while bypassing `Storage.prototype.setItem` entirely — verified under jsdom
 * 30), the `setItem` spy catches a write that is later removed, and `clear`/`removeItem`
 * catch destruction, which leaves no trace in the final state at all.
 */
function foreignKeys(): string[] {
  return Object.keys(localStorage).filter((key) => key !== HOST_KEY && !key.startsWith('ct:'));
}

/**
 * jsdom is already `readyState: 'complete'` when a test runs, so a listener registered during
 * render never fires on its own — hence the dispatch.
 *
 * ⚠️ It is NOT `virtual:pwa-register` that needs it, contrary to what this comment said before
 * (and what CLAUDE.md said before PR #7): `workbox-window`'s `Workbox.register` is
 * `if (!immediate && document.readyState !== 'complete') await load`, and under jsdom that
 * condition is always false, so the real registration happens SYNCHRONOUSLY. The dispatch stays
 * because a hand-rolled `window.addEventListener('load', … register …)` in a shared module is
 * still a plausible regression, and it costs nothing.
 */
async function settle() {
  window.dispatchEvent(new Event('DOMContentLoaded'));
  window.dispatchEvent(new Event('load'));
  await act(async () => {
    await Promise.resolve();
  });
}

/**
 * The entry is imported HERE, not at the top of the file, and `vi.resetModules()` below
 * re-evaluates the route tree for every test. A module-scope side effect — `localStorage
 * .clear()` at the top of `__root.tsx`, say — otherwise runs once when this file's static
 * imports are hoisted, i.e. before any spy exists, and the guard cannot see it. Module
 * evaluation has to happen inside the observation window.
 */
async function mount() {
  const { default: ClimbTrainerApp } = await import('./remote');
  const view = render(<ClimbTrainerApp />);
  await screen.findByRole('heading', { name: 'climb-trainer' });
  await settle();
  return view;
}

beforeEach(() => {
  vi.resetModules();

  // Before the spies, so the reset is not itself recorded as a violation.
  localStorage.clear();
  localStorage.setItem(HOST_KEY, HOST_VALUE);

  register = vi.fn();
  // jsdom has no ServiceWorkerContainer at all, so it has to be supplied to be spied on.
  Object.defineProperty(navigator, 'serviceWorker', {
    value: { register, ready: Promise.resolve(), controller: null },
    configurable: true,
  });

  pushState = vi.spyOn(window.history, 'pushState');
  replaceState = vi.spyOn(window.history, 'replaceState');
  setItem = vi.spyOn(Storage.prototype, 'setItem');
  removeItem = vi.spyOn(Storage.prototype, 'removeItem');
  clear = vi.spyOn(Storage.prototype, 'clear');

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
    const { unmount } = await mount();

    // A real navigation is the case that would reach history.pushState if this entry
    // were ever handed a browser history by mistake. An anonymous destination, because the
    // mount starts signed out and the in-app leaves are behind the route guard. Clicked in
    // `main` because the landing page renders no nav — and the hero's call to action is the
    // link a visitor in the shell actually clicks, so it is the better subject anyway.
    fireEvent.click(within(screen.getByRole('main')).getByRole('link', { name: 'Create account' }));
    await screen.findByRole('heading', { name: 'Create account' });
    unmount();

    expect(register).not.toHaveBeenCalled();
    expect(pushState).not.toHaveBeenCalled();
    expect(replaceState).not.toHaveBeenCalled();
    expect(window.location.href).toBe(before);
  });

  /**
   * A relative href resolves against the HOST document, so cmd-click, middle-click and
   * "copy link address" would land on kilianmc.com/plan — a 404 on the portfolio. The
   * literal origin is asserted rather than imported: a typo in the constant is exactly
   * what this has to catch. The standalone arm lives in `router.test.tsx`. Issue #16.
   */
  it('renders absolute standalone hrefs, so a cmd-click leaves for the real app', async () => {
    await mount();

    // The landing page's calls to action are the links a visitor in the shell is most likely
    // to cmd-click. They are asserted first because `/` renders no nav.
    expect(
      within(screen.getByRole('main'))
        .getAllByRole('link')
        .map((link) => link.getAttribute('href')),
    ).toEqual(['https://climb.kilianmc.com/login', 'https://climb.kilianmc.com/register']);

    // …and then the nav, on the first route that has one. Both halves of the rewrite still get
    // asserted; only the route hosting the nav half moved.
    fireEvent.click(within(screen.getByRole('main')).getByRole('link', { name: 'Log in' }));
    await screen.findByRole('heading', { name: 'Log in' });

    expect(
      within(screen.getByRole('navigation', { name: 'Main' }))
        .getAllByRole('link')
        .map((link) => link.getAttribute('href')),
    ).toEqual([
      'https://climb.kilianmc.com/',
      'https://climb.kilianmc.com/login',
      'https://climb.kilianmc.com/register',
    ]);
  });

  it('holds the access token in a closure, never in the host origin storage', async () => {
    await mount();

    fireEvent.click(within(screen.getByRole('main')).getByRole('link', { name: 'Log in' }));
    await screen.findByRole('heading', { name: 'Log in' });

    // A real token body, so this is not vacuous: the store genuinely holds a token by the
    // end, and the assertions below are about where it is NOT.
    vi.mocked(fetch).mockResolvedValue(
      new Response(
        JSON.stringify({
          access_token: 'header.payload.signature',
          token_type: 'bearer',
          expires_in: 10_800,
          scope: 'user',
        }),
        { headers: { 'content-type': 'application/json' } },
      ),
    );

    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'a@b.example' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'x'.repeat(12) } });
    fireEvent.click(screen.getByRole('button', { name: 'Log in' }));
    await settle();

    // The login response above is the stubbed token body. Nothing token-shaped may land in
    // the portfolio's storage — see item 4 of the security verification list in CLAUDE.md.
    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument();
    expect(foreignKeys()).toEqual([]);
    expect(setItem).not.toHaveBeenCalled();
    expect(clear).not.toHaveBeenCalled();
  });

  it("leaves the portfolio's localStorage exactly as it found it", async () => {
    await mount();

    expect(foreignKeys()).toEqual([]);
    expect(setItem.mock.calls.filter(([key]) => !key.startsWith('ct:'))).toEqual([]);
    expect(clear).not.toHaveBeenCalled();
    expect(removeItem).not.toHaveBeenCalled();
    // Property assignment could overwrite the host's own key without adding a new one.
    expect(localStorage.getItem(HOST_KEY)).toBe(HOST_VALUE);
  });

  it('positive control: every detector above can actually see its violation', async () => {
    // Without this the guards above pass on an empty set, and would look identical if a
    // spy were mis-wired or an event never dispatched. Same class of defect as the
    // vacuous route-enumeration walk recorded in CLAUDE.md, so it gets the same
    // treatment: prove the detector fires before trusting that it stayed silent.
    //
    // The service-worker arm imports the same specifier `pwa/updatePrompt.ts` does, so it
    // exercises the module graph a stray import from the route tree would create. It is a STAND-IN
    // for the real registration, not the real thing: `vitest.config.ts` aliases the specifier to
    // `test/pwaRegisterStub.ts` (nothing resolves the virtual module without the plugin). The
    // emitted URL and the plugin options are asserted from the config and the build instead — see
    // `pwaContract.test.ts` and `distContract.test.ts` — because the arguments below are the
    // stub's own literals.
    //
    // Registration is synchronous: jsdom is `readyState: 'complete'`, so upstream's
    // `!immediate && readyState !== 'complete'` deferral never applies. See the stub.
    const { registerSW } = await import('virtual:pwa-register');
    registerSW();
    expect(register).toHaveBeenCalled();

    // The `load` dispatch must also not be what makes it fire, or the negative assertions above
    // would only be true until something registered from a listener.
    const callsBeforeLoad = register.mock.calls.length;
    await settle();
    expect(register.mock.calls.length).toBe(callsBeforeLoad);

    // …and a listener-based registration IS still caught, which is why `settle()` dispatches.
    window.addEventListener('load', () => void navigator.serviceWorker.register('/late-sw.js'), {
      once: true,
    });
    await settle();
    expect(register).toHaveBeenCalledWith('/late-sw.js');

    (localStorage as unknown as Record<string, string>)['injected'] = 'x';
    expect(foreignKeys()).toEqual(['injected']);

    localStorage.setItem('ct:allowed', '1');
    expect(foreignKeys()).toEqual(['injected']);

    localStorage.removeItem('injected');
    expect(removeItem).toHaveBeenCalled();

    localStorage.clear();
    expect(clear).toHaveBeenCalled();

    window.history.pushState({}, '', '/hijacked');
    expect(pushState).toHaveBeenCalled();
  });
});
