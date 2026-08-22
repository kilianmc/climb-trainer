import {
  Link,
  Outlet,
  createRootRouteWithContext,
  useRouter,
  useRouterState,
} from '@tanstack/react-router';
import type { QueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';

import { useAuth, type Auth } from '../auth/AuthProvider';
import { useThemeChoice } from '../theme';
import {
  BrandMark,
  IconCalendar,
  IconGrid,
  IconHome,
  IconJournal,
  IconMenu,
  IconSignIn,
  IconUserPlus,
  IconPower,
  IconTimer,
  IconUser,
} from '../ui/icons';
import { CtAppScope, RouteError, RouteNotFound } from '../ui/status';
import { ThemeSwitch } from '../ui/ThemeSwitch';
import '../styles/app.scss';

/**
 * The app shell, and the `.ct-app` element. Every style and every design token hangs off
 * it rather than `:root`/`body`, because in the federated mount this tree is injected
 * into kilianmc.com's document and anything global restyles the shell.
 *
 * A root-level error, not-found or pending render replaces this component, so the three
 * status renders re-establish `.ct-app` themselves (issue #15) — `CtAppScope` is what
 * tells them not to when they render inside the outlet instead. See `ui/status.tsx`.
 *
 * `app.scss` is imported here, not in the entries, so both mounts get it from the
 * single route tree.
 */

/**
 * Router context. `beforeLoad` runs outside React, so the guard reads auth from here rather
 * than from `useAuth()`; the entries hand the same `Auth` instance to both.
 */
export interface AppContext {
  auth: Auth;
  queryClient: QueryClient;
}

/** The burger's panel, and the id `aria-controls` points at. One nav, so one constant. */
const MENU_ID = 'ct-nav-menu';

function AppNav() {
  const router = useRouter();
  const { isAuthenticated, scope, client } = useAuth();
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const [menuOpen, setMenuOpen] = useState(false);
  const burger = useRef<HTMLButtonElement>(null);
  const nav = useRef<HTMLElement>(null);

  function closeMenu() {
    setMenuOpen(false);
  }

  /**
   * The two ways out of an open disclosure that are not the trigger itself.
   *
   * **Escape returns focus to the trigger**, because that is where the user was: closing a panel
   * and dropping focus on `<body>` loses a keyboard user's place entirely. **A pointer outside the
   * nav closes it** — `pointerdown`, not `click`, so it fires before focus moves and cannot be
   * beaten by the panel's own handlers.
   *
   * Both listeners exist only while the panel is open, so the closed state costs nothing. The
   * `setMenuOpen` calls are inside event callbacks rather than in the effect body, which is the
   * distinction `react-hooks`' `set-state-in-effect` rule draws.
   */
  useEffect(() => {
    if (!menuOpen) return;

    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== 'Escape') return;
      setMenuOpen(false);
      burger.current?.focus();
    }
    function onPointerDown(event: PointerEvent) {
      if (nav.current?.contains(event.target as Node) === true) return;
      setMenuOpen(false);
    }

    document.addEventListener('keydown', onKeyDown);
    document.addEventListener('pointerdown', onPointerDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.removeEventListener('pointerdown', onPointerDown);
    };
  }, [menuOpen]);

  /**
   * Clearing the session does NOT re-run `beforeLoad`, so without the navigation the visitor
   * would sit on a guarded route with an anonymous nav and no way back. `session.clear()`
   * runs synchronously inside `logout()` before its first `await`, so `/` already sees an
   * anonymous store by the time it evaluates its own redirect.
   */
  function logOut() {
    void client.logout();
    void router.navigate({ to: '/' });
  }

  // The landing page renders NO nav, and it is the only route that does not. Its three anonymous
  // destinations are Home (itself), Log in and Create account, and the hero already carries the
  // last two as primary actions — so the nav there was a second copy of the same page. This is
  // shared chrome, not landing chrome: every other route, signed in or out, still gets it, which
  // is why this is a route check and not a deletion.
  if (pathname === '/') return null;

  // Anonymous and authenticated navs are disjoint on purpose: linking a signed-out visitor
  // to /plan would only bounce them off the guard and back to /login.
  //
  // **Two sections, left and right, and the centred group is gone** (Kilian, round 7). Centring
  // the links cost a lot: with `1fr auto 1fr` the outer tracks must be equal, so the right-hand
  // one had to match the brand's width and the labels could not fit until 66rem. Left/right drops
  // that constraint entirely — see `_chrome.scss` for the re-measurement.
  return (
    // ⚠️ The variant class carries THRESHOLDS, not centring. The anonymous nav has three
    // destinations and no Log out, so it fits its icons ~9rem earlier and its labels ~13rem
    // earlier than the authenticated one; sharing one pair made it wait for ~130px it does not
    // need (`_chrome.scss` has the arithmetic). Round 10's revert was about centring the group,
    // which stays right-aligned in both.
    <nav
      className={isAuthenticated ? 'ct-app__nav ct-app__nav--app' : 'ct-app__nav ct-app__nav--anon'}
      aria-label="Main"
      ref={nav}
    >
      {/* ⚠️ **Not a link, and that is checked rather than assumed.** Both navs already carry a
          destination for the app's front door — "Dashboard" when signed in, "Home" when not — so
          a linked brand would be a second control with the same target, and the mark beside it
          would have to be silent to avoid announcing the name twice. It is a title. */}
      <p className="ct-app__brand">
        <BrandMark />
        {/* Properly cased in the DOM; `text-transform: uppercase` does the wordmark, so a screen
            reader says "Climb Trainer" rather than spelling out two initialisms. */}
        <span className="ct-app__brand-title">Climb Trainer</span>
      </p>

      <div className="ct-app__nav-end">
        {/* ⚠️ `data-open` rather than conditional rendering: above the threshold this panel is
            ordinary inline chrome and must render whatever the state says. The state only draws
            it when the stylesheet has made it a panel.
            ⚠️ **The five destinations only** (Kilian, round 8). The theme switch and Log out are
            siblings of this panel, not children, so they stay on the bar at every width — a
            theme toggle you have to open a menu to reach is one nobody uses, and Log out is the
            one control a visitor may need in a hurry. */}
        <div className="ct-app__nav-items" id={MENU_ID} data-open={menuOpen ? 'true' : 'false'}>
          {isAuthenticated ? (
            <>
              {/* ⚠️ **`aria-label` on every item, at every width, and it is not redundant with
                  the text.** In the icon-only band the label span is a TOOLTIP —
                  `visibility: hidden` until hover or focus — and `visibility: hidden` removes a
                  node from the accessibility tree, so without the label those would be five
                  unnamed links. The glyphs stay `aria-hidden` (the shared `Icon` frame), so the
                  accessible name is exactly the label at every width and
                  `getByRole('link', { name })` is unchanged. */}
              <Link to="/dashboard" aria-label="Dashboard" onClick={closeMenu}>
                <IconGrid />
                <span className="ct-app__nav-label">Dashboard</span>
              </Link>
              <Link to="/plan" aria-label="Plan" onClick={closeMenu}>
                <IconCalendar />
                <span className="ct-app__nav-label">Plan</span>
              </Link>
              <Link to="/session" aria-label="Session" onClick={closeMenu}>
                <IconTimer />
                <span className="ct-app__nav-label">Session</span>
              </Link>
              <Link to="/diary" aria-label="Diary" onClick={closeMenu}>
                <IconJournal />
                <span className="ct-app__nav-label">Diary</span>
              </Link>
              <Link to="/profile" aria-label="Profile" onClick={closeMenu}>
                <IconUser />
                <span className="ct-app__nav-label">Profile</span>
              </Link>
            </>
          ) : (
            <>
              {/* Same three rules as the authenticated items: `aria-label` at every width (the
                  label span is a bubble in the icon-only band, and `visibility: hidden` takes a
                  node out of the accessibility tree), glyphs `aria-hidden` from the shared frame.
                  `IconUserPlus` was drawn for exactly this in PR #7 and `IconSignIn` for its
                  neighbour — only Home is new. `IconUser` stays Profile's: the plain user and the
                  user-plus never appear in the same nav, since these three are the signed-OUT
                  set. */}
              <Link to="/" aria-label="Home" onClick={closeMenu}>
                <IconHome />
                <span className="ct-app__nav-label">Home</span>
              </Link>
              <Link to="/login" aria-label="Log in" onClick={closeMenu}>
                <IconSignIn />
                <span className="ct-app__nav-label">Log in</span>
              </Link>
              <Link to="/register" aria-label="Create account" onClick={closeMenu}>
                <IconUserPlus />
                <span className="ct-app__nav-label">Create account</span>
              </Link>
            </>
          )}
        </div>

        {/* ⚠️ **Burger, then theme, then Log out** (Kilian, round 10). The burger is the leftmost
            of the three, and the two always-visible controls sit at the end of the bar. */}
        <button
          type="button"
          className="ct-app__button ct-app__button--quiet ct-app__button--icon ct-app__nav-burger"
          aria-label="Menu"
          aria-expanded={menuOpen}
          aria-controls={MENU_ID}
          ref={burger}
          onClick={() => {
            setMenuOpen(!menuOpen);
          }}
        >
          <IconMenu />
        </button>

        {/* Always on the bar, at every width. Signed out too: the theme is the device's choice,
            not the account's. */}
        <ThemeSwitch />
        {isAuthenticated && (
          <button
            type="button"
            className="ct-app__button ct-app__button--quiet ct-app__button--icon"
            aria-label="Log out"
            onClick={logOut}
          >
            <IconPower />
            {/* ⚠️ `nav-tip`, not `nav-label`: Log out is icon-only at EVERY width now, exactly like
                the theme switch, so its label is a hover/focus bubble and never an inline word. It
                is also what buys the labelled regime ~53px. */}
            <span className="ct-app__nav-tip">Log out</span>
          </button>
        )}
        {scope === 'demo' && (
          <span className="ct-app__badge" role="status">
            Demo — read only
          </span>
        )}
      </div>
    </nav>
  );
}

function RootLayout() {
  const theme = useThemeChoice();

  return (
    /**
     * ⚠️ `data-theme` goes HERE and nowhere else. `_tokens.scss::overrides` re-declares the
     * token block behind `&[data-theme='…']`, which beats the `prefers-color-scheme` block
     * because a media query carries no specificity — and it stays inside `.ct-app`, so nothing
     * about it can reach kilianmc.com's document in the federated mount.
     *
     * With the System position gone (round 5) the attribute is always present: `matchMedia`
     * seeds the FIRST choice from the OS, and from then on the attribute is the answer.
     */
    <div className="ct-app" data-theme={theme}>
      <AppNav />
      <main className="ct-app__main">
        <CtAppScope>
          <Outlet />
        </CtAppScope>
      </main>
    </div>
  );
}

export const Route = createRootRouteWithContext<AppContext>()({
  component: RootLayout,
  notFoundComponent: RouteNotFound,
  errorComponent: RouteError,
});
