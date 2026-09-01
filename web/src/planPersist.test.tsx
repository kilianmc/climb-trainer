import { QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider, createMemoryHistory } from '@tanstack/react-router';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

import type {
  ActivePlanResponse,
  ExerciseLibrary,
  PlanTree,
  Profile,
  Vocabulary,
} from './api/types';
import { AuthProvider, createAuth } from './auth/AuthProvider';
import { nextMonday } from './plan/blueprint';
import { ACTIVE_PLAN_KEY } from './plan/api';
import { createAppRouter, createQueryClient } from './router';

/**
 * **The write path on `/plan`: Start, "Build a different plan", and the ways either can look like
 * it worked when it did not.** Core-user-path and data-losing under CLAUDE.md's testing policy —
 * a plan is up to 2,421 prescribed rows, and the second control clears every setup answer.
 *
 * Every test here is a guard against a specific defect, and each was **shown to fail** against a
 * deliberately broken version before being trusted (the failures are in PR #11b's notes):
 *
 * 1. **No optimistic value is ever written into the query cache** — the PR #9 bug class, which
 *    cost three review rounds and left a fabricated 71% on screen against a truth of 57%. Here
 *    the fabrication would be a whole plan tree.
 * 2. **A 409 is not an error.** It means "you already have an active plan", which is *true*, so
 *    the screen must go and read that plan rather than tell the climber their Start failed.
 * 3. **`{plan: null}` is the empty state**, a 200, and the state every new account is in.
 * 4. **A failing background refetch must not replace a screen with something on it** — gating on
 *    `isError` instead of `isLoadingError` is exactly how a user's unsaved draft was destroyed.
 * 5. **In demo scope the write affordances are ABSENT, not disabled** (issue #65). A disabled
 *    control reads as broken software; the demo mount must simply not be offered the action.
 *
 * Asserted through the real router, the real query client and the real API client, because the
 * behaviour under test lives in the seam between them: a harness that stubbed the mutation would
 * reproduce the intended behaviour rather than the shipped one.
 */
const TARGET_GRADE_ID = 11;
const CURRENT_GRADE_ID = 10;
const FINGERS_ID = 1;
const CORE_ID = 2;
const PERSISTED_PLAN_ID = 77;

const VOCABULARY: Vocabulary = {
  grade_systems: [{ id: 1, key: 'font', name: 'Fontainebleau', discipline: 'boulder' }],
  grades: [
    { id: CURRENT_GRADE_ID, grade_system_id: 1, label: '6A', ordinal: 1010 },
    { id: TARGET_GRADE_ID, grade_system_id: 1, label: '6B', ordinal: 1012 },
  ],
  climbing_aspects: [
    { id: FINGERS_ID, key: 'finger_strength', name: 'Finger strength', description: 'Force.' },
    { id: CORE_ID, key: 'core', name: 'Core tension', description: 'Tension.' },
  ],
  equipment: [{ id: 5, key: 'hangboard', name: 'Hangboard', description: 'Edges.' }],
  injury_areas: [{ id: 8, key: 'elbow', name: 'Elbow', description: 'Tendons.' }],
  // Irrelevant to this fixture; the phase copy is covered by tests/test_phase_guide.py.
  plan_goal: '',
  phase_guide: [],
  enums: {
    disciplines: ['boulder', 'sport'],
    activity_kinds: ['climbing'],
    ascent_styles: ['redpoint'],
    protocol_kinds: ['max_hang'],
    phases: ['base'],
    session_statuses: ['planned'],
  },
};

/** Fully answered, so `previewBlocker` is `null` and the screen is on the plan path. */
const PLANNABLE: Profile = {
  email: 'a@example.com',
  display_name: null,
  target_grade_id: TARGET_GRADE_ID,
  current_grade_id: CURRENT_GRADE_ID,
  primary_discipline: 'boulder',
  sessions_per_week: 3,
  available_weekdays: 0b0010101,
  strength_aspect_id: FINGERS_ID,
  weakness_aspect_id: CORE_ID,
  show_body_metrics: true,
  injuries_reviewed_at: '2026-08-20T00:00:00Z',
  aspect_ratings: [{ climbing_aspect_id: FINGERS_ID, score: 5, rated_at: '2026-08-21T00:00:00Z' }],
  injuries: [],
};

/** What `POST /api/profile/reset` answers with: the four steps un-answered, the account kept. */
const UNANSWERED: Profile = {
  ...PLANNABLE,
  target_grade_id: null,
  current_grade_id: null,
  primary_discipline: null,
  sessions_per_week: null,
  available_weekdays: null,
  strength_aspect_id: null,
  weakness_aspect_id: null,
  injuries_reviewed_at: null,
  aspect_ratings: [],
  injuries: [],
};

const LIBRARY: ExerciseLibrary = {
  exercises: [
    {
      id: 3,
      key: 'weighted_max_hangs',
      name: 'Weighted max hangs',
      instructions: 'Hang.',
      climbing_aspect_id: FINGERS_ID,
      protocol_kind: 'max_hang',
      discipline: null,
      media_url: null,
      substitution_hint: null,
      progression_of_id: null,
      regression_of_id: null,
      equipment_ids: [5],
      contraindicated_injury_area_ids: [],
      prescriptions: [],
    },
  ],
};

/**
 * ⚠️ **One fixture builder for both shapes, because there is one response model.** Round 2 of
 * this PR collapsed the `Persisted*Out` hierarchy: the only difference between a preview and a
 * persisted plan is that a preview is not a row, so every `id` — plus a block's `exercise_id`, a
 * session's `status` and the plan's `activated_at` — is `null`. Building the two fixtures from
 * one function is what makes that a property of the test rather than a claim in a comment: if
 * the shapes ever fork, this stops compiling.
 */
function planTree(ids: { readonly persisted: boolean }): PlanTree {
  const id = (value: number) => (ids.persisted ? value : null);
  return {
    id: id(PERSISTED_PLAN_ID),
    // Derived on serialisation from `generator_input`; this fixture carries no ordinal, so the
    // server would send `null`. `plan/explain.test.ts` is where the derived figures are read.
    climbing_band: null,
    name: 'Road to 6B',
    start_date: '2026-08-31',
    week_count: 1,
    discipline: 'boulder',
    target_grade_id: TARGET_GRADE_ID,
    current_grade_id: CURRENT_GRADE_ID,
    grade_gap: 2,
    generator_version: '1.0.0',
    generator_input: { library_digest: 'abc' },
    activated_at: ids.persisted ? '2026-08-24T10:00:00Z' : null,
    notes: [],
    shortfalls: [],
    mesocycles: [
      {
        id: id(101),
        phase: 'base',
        start_week: 1,
        end_week: 1,
        microcycles: [
          {
            id: id(201),
            week_no: 1,
            phase: 'base',
            is_deload: false,
            start_date: '2026-08-31',
            sessions: [
              {
                id: id(301),
                weekday: 0,
                scheduled_on: '2026-08-31',
                title: 'Finger strength',
                activity_kind: 'climbing',
                estimated_minutes: 60,
                status: ids.persisted ? 'planned' : null,
                shortfalls: [],
                blocks: [
                  {
                    id: id(401),
                    order_index: 0,
                    exercise_key: 'weighted_max_hangs',
                    exercise_id: id(3),
                    aspect_key: 'finger_strength',
                    protocol_kind: 'max_hang',
                    rest_after_seconds: 180,
                    rest_between_sets_seconds: 120,
                    shortfall: null,
                    sets: [
                      {
                        id: id(501),
                        set_index: 0,
                        target_reps: 1,
                        target_work_seconds: 10,
                        target_rest_seconds: null,
                        target_intensity_pct: 90,
                        target_rpe: 8,
                        target_load_kg: null,
                        target_grade_id: null,
                      },
                    ],
                  },
                ],
              },
            ],
          },
        ],
      },
    ],
  };
}

const PREVIEW = planTree({ persisted: false });
const PERSISTED = planTree({ persisted: true });

function urlOf(input: unknown): string {
  if (typeof input === 'string') return input;
  if (input instanceof URL) return input.href;
  return input instanceof Request ? input.url : '';
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

/**
 * Everything the screen may ask for, keyed by PATH.
 *
 * ⚠️ The path is parsed and matched exactly rather than with `endsWith`: `/api/plans/active` also
 * ends with nothing that distinguishes it from `/api/plans` under a suffix match, and a mock that
 * answered the create route with the active-plan envelope would make every test here pass for the
 * wrong reason.
 */
interface Routes {
  active?: () => Promise<Response>;
  create?: () => Promise<Response>;
  reset?: () => Promise<Response>;
  preview?: () => Promise<Response>;
}

function stubFetch(routes: Routes) {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: unknown, init?: RequestInit) => {
      const path = new URL(urlOf(input), 'http://localhost').pathname;
      const method = init?.method ?? 'GET';
      if (path === '/api/vocabulary') return Promise.resolve(json(VOCABULARY));
      if (path === '/api/profile' && method === 'GET') return Promise.resolve(json(PLANNABLE));
      if (path === '/api/library') return Promise.resolve(json(LIBRARY));
      if (path === '/api/plans/active') {
        return (routes.active ?? (() => Promise.resolve(json({ plan: null }))))();
      }
      if (path === '/api/plans/preview') {
        return (routes.preview ?? (() => Promise.resolve(json(PREVIEW))))();
      }
      if (path === '/api/plans' && method === 'POST') {
        return (routes.create ?? (() => Promise.resolve(json(PERSISTED, 201))))();
      }
      if (path === '/api/profile/reset' && method === 'POST') {
        return (routes.reset ?? (() => Promise.resolve(json(UNANSWERED))))();
      }
      return Promise.reject(new Error(`unexpected request: ${method} ${path}`));
    }),
  );
}

/** The parsed JSON body of the first `METHOD /path` request, or `undefined`. */
function bodyOf(method: string, path: string): unknown {
  const call = vi
    .mocked(fetch)
    .mock.calls.find(
      ([input, init]) =>
        (init?.method ?? 'GET') === method &&
        new URL(urlOf(input), 'http://localhost').pathname === path,
    );
  const body = call?.[1]?.body;
  return typeof body === 'string' ? JSON.parse(body) : undefined;
}

/** Every request made, as `METHOD /path`, in order. */
function requests(): string[] {
  return vi
    .mocked(fetch)
    .mock.calls.map(
      ([input, init]) =>
        `${init?.method ?? 'GET'} ${new URL(urlOf(input), 'http://localhost').pathname}`,
    );
}

/** Drain the microtask queue and React's work, inside `act` so no update is unbatched. */
async function settle(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

function renderPlan(scope: 'user' | 'demo' = 'user') {
  const auth = createAuth();
  // Signed in, or `_authed`'s guard redirects to /login and the screen never renders.
  auth.session.set(`${scope}-token`, scope);
  const queryClient = createQueryClient();
  const router = createAppRouter(createMemoryHistory({ initialEntries: ['/plan'] }), {
    auth,
    queryClient,
  });
  render(
    <AuthProvider auth={auth}>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </AuthProvider>,
  );
  return { queryClient, router };
}

/** What the cache holds for `GET /api/plans/active` — the envelope, exactly as the server sends it. */
const cachedEnvelope = (queryClient: ReturnType<typeof createQueryClient>) =>
  queryClient.getQueryData<ActivePlanResponse>(ACTIVE_PLAN_KEY);

afterEach(() => {
  vi.unstubAllGlobals();
});

beforeEach(() => {
  stubFetch({});
});

it('renders {plan: null} as "no plan yet" and offers Start, not an error', async () => {
  renderPlan();

  expect(await screen.findByRole('button', { name: 'Start this plan' })).toBeInTheDocument();
  expect(screen.getByText(/don't have a plan running yet/i)).toBeInTheDocument();
  // The whole point: a 200 carrying no plan is not a failure, so nothing on screen says so.
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  // …and the plan itself renders, through the same renderer a persisted plan uses.
  expect(screen.getByRole('heading', { level: 2, name: /Base/ })).toBeInTheDocument();
});

it('writes NO optimistic plan into the query cache while a Start is in flight', async () => {
  let release: ((response: Response) => void) | undefined;
  stubFetch({
    create: () =>
      new Promise<Response>((resolve) => {
        release = resolve;
      }),
  });
  const { queryClient } = renderPlan();

  const start = await screen.findByRole('button', { name: 'Start this plan' });
  fireEvent.click(start);
  await settle();

  // The request is on the wire and the button says so…
  expect(requests()).toContain('POST /api/plans');
  expect(screen.getByRole('button', { name: 'Starting…' })).toBeInTheDocument();
  // …and the cache still holds only what the SERVER said, which is "no plan".
  expect(cachedEnvelope(queryClient)).toEqual({ plan: null });

  release?.(json(PERSISTED, 201));
  await settle();

  // Only now, and it is the server's own 201 body.
  expect(cachedEnvelope(queryClient)?.plan).toEqual(PERSISTED);
  expect(await screen.findByRole('button', { name: 'Build a different plan' })).toBeInTheDocument();
});

it('treats a 409 as "you already have one": it reads the plan and renders it', async () => {
  stubFetch({
    create: () => Promise.resolve(json({ detail: 'You already have an active plan.' }, 409)),
    // First call is the initial load (nothing yet), every later one is the recovery read.
    active: (() => {
      let calls = 0;
      return () => {
        calls += 1;
        return Promise.resolve(json(calls === 1 ? { plan: null } : { plan: PERSISTED }));
      };
    })(),
  });
  const { queryClient } = renderPlan();

  fireEvent.click(await screen.findByRole('button', { name: 'Start this plan' }));
  await settle();

  // The 409 sent the client back to read, and what came back is on screen as the climber's plan.
  expect(requests().filter((call) => call === 'GET /api/plans/active')).toHaveLength(2);
  expect(await screen.findByRole('button', { name: 'Build a different plan' })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /^Start/ })).toBeNull();
  // Not a failure at any layer: no alert, and the cache holds the plan rather than an error.
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  expect(cachedEnvelope(queryClient)?.plan).toEqual(PERSISTED);
});

it('needs a confirmation before it clears a single setup answer', async () => {
  // ⚠️ `POST /api/profile/reset` clears both grades, the training days, both aspect picks, every
  // rating row and every open injury, with no undo. One tap must not be able to do that.
  stubFetch({ active: () => Promise.resolve(json({ plan: PERSISTED })) });
  renderPlan();

  fireEvent.click(await screen.findByRole('button', { name: 'Build a different plan' }));
  await settle();

  // One click writes nothing. The panel has a real accessible name and focus is on the
  // destructive choice, not on the safe one.
  expect(requests().some((call) => call.includes('/profile/reset'))).toBe(false);
  expect(screen.getByRole('group', { name: 'Build a different plan?' })).toBeInTheDocument();
  const yes = screen.getByRole('button', { name: 'Yes, set up again' });
  expect(yes).toHaveFocus();

  // Escape dismisses it and the profile is untouched.
  fireEvent.keyDown(yes, { key: 'Escape' });
  await settle();
  expect(screen.queryByRole('group', { name: 'Build a different plan?' })).not.toBeInTheDocument();
  expect(requests().some((call) => call.includes('/profile/reset'))).toBe(false);
});

it('resets the profile and goes to the wizard, but ONLY after the server agrees', async () => {
  stubFetch({ active: () => Promise.resolve(json({ plan: PERSISTED })) });
  const { router } = renderPlan();

  fireEvent.click(await screen.findByRole('button', { name: 'Build a different plan' }));
  await settle();
  fireEvent.click(screen.getByRole('button', { name: 'Yes, set up again' }));
  await settle();

  expect(requests()).toContain('POST /api/profile/reset');
  expect(router.state.location.pathname).toBe('/onboarding');
});

it('does NOT navigate when the reset fails, and says nothing has changed', async () => {
  // ⚠️ The round-1 onboarding bug: an unawaited navigate lands the wizard on whatever the cache
  // still held — here, a fully answered profile it would call complete.
  stubFetch({
    active: () => Promise.resolve(json({ plan: PERSISTED })),
    reset: () => Promise.resolve(json({ detail: 'nope' }, 500)),
  });
  const { router } = renderPlan();

  fireEvent.click(await screen.findByRole('button', { name: 'Build a different plan' }));
  await settle();
  fireEvent.click(screen.getByRole('button', { name: 'Yes, set up again' }));
  await settle();

  expect(router.state.location.pathname).toBe('/plan');
  const alert = screen.getByRole('alert');
  expect(alert).toHaveTextContent(/could not be cleared/i);
  expect(alert).toHaveTextContent(/nothing has changed/i);
});

it('keeps a plan on screen when a background refetch of it fails', async () => {
  let fail = false;
  stubFetch({
    active: () =>
      Promise.resolve(fail ? json({ detail: 'No such thing.' }, 404) : json({ plan: PERSISTED })),
  });
  const { queryClient } = renderPlan();

  expect(await screen.findByRole('button', { name: 'Build a different plan' })).toBeInTheDocument();

  fail = true;
  await act(async () => {
    await queryClient.refetchQueries({ queryKey: ACTIVE_PLAN_KEY });
  });
  await settle();

  // `query.js`'s error reducer sets `status: "error"` even with data present, so a screen gated
  // on `isError` would have replaced itself here. There is something to show, so it is shown.
  expect(screen.getByRole('heading', { level: 2, name: /Base/ })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Build a different plan' })).toBeInTheDocument();
  expect(screen.queryByText(/could not check whether you already have a plan/i)).toBeNull();
});

it('HIDES the write affordances in demo scope rather than disabling them', async () => {
  // ⚠️ `GET /api/plans/active` does NOT 403 for a demo token — `enforce_auth` gates on
  // `MUTATING_METHODS` — so the demo mount really does land here and really does read a plan.
  renderPlan('demo');

  expect(await screen.findByRole('heading', { level: 2, name: /Base/ })).toBeInTheDocument();

  // Absent, not disabled. Issue #65: the UI never offers an action the principal cannot take,
  // and a greyed-out control reads as broken software rather than as a demo.
  const buttons = screen.queryAllByRole('button');
  expect(buttons.map((button) => button.textContent)).not.toContain('Start this plan');
  expect(buttons.filter((button) => button.hasAttribute('disabled'))).toEqual([]);
  expect(screen.queryByRole('button', { name: /build a different plan/i })).toBeNull();
  expect(screen.queryByRole('button', { name: /start/i })).toBeNull();
});

it('NEVER generates a preview for a climber who already has a plan', async () => {
  // ⚠️ There is no path from a running plan to the most expensive read in the app — including
  // through the confirmation panel, which is why this clicks it.
  stubFetch({
    active: () => Promise.resolve(json({ plan: PERSISTED })),
    preview: () => Promise.reject(new Error('the preview must not be generated unasked')),
  });
  renderPlan();

  fireEvent.click(await screen.findByRole('button', { name: 'Build a different plan' }));
  await settle();

  expect(screen.getByRole('group', { name: 'Build a different plan?' })).toBeInTheDocument();
  expect(requests()).not.toContain('POST /api/plans/preview');
});

it('POSTs the start_date THAT WAS ON SCREEN, not a freshly recomputed Monday', async () => {
  // ⚠️ Deliberately a Monday that is NOT this week's. A tab left open across midnight — or over
  // a weekend — must persist the plan the climber READ, and re-deriving `nextMonday` at click
  // time is a silent bug: the plan simply starts a week from the one on screen. Nothing in the
  // rest of this file inspects a request body, so before this test that regression was green.
  const ON_SCREEN = '2026-11-30';
  expect(ON_SCREEN).not.toBe(nextMonday(new Date()));
  stubFetch({
    preview: () => Promise.resolve(json({ ...PREVIEW, start_date: ON_SCREEN })),
    create: () => Promise.resolve(json({ ...PERSISTED, start_date: ON_SCREEN }, 201)),
  });
  renderPlan();

  fireEvent.click(await screen.findByRole('button', { name: 'Start this plan' }));
  await settle();

  expect(bodyOf('POST', '/api/plans')).toEqual({ start_date: ON_SCREEN });
  // The preview asked for the recomputed Monday — that is its key — so the two really are
  // different values and the create used the right one.
  expect(bodyOf('POST', '/api/plans/preview')).toEqual({ start_date: nextMonday(new Date()) });
});

it('never claims a failed Start saved nothing, and names a STALE PAGE when that is the cause', async () => {
  // ⚠️ The response is serialised BEFORE `commit()`, so "nothing was saved" is true for almost
  // every failure — and false for one: a socket dropped at or after the commit leaves the new
  // plan active and the old one abandoned, with this screen asserting the opposite for up to ten
  // minutes. The fix is the COPY; an `onError` refetch here is the PR #9 bug.
  stubFetch({ create: () => Promise.resolve(json({ detail: 'nope' }, 500)) });
  renderPlan();

  fireEvent.click(await screen.findByRole('button', { name: 'Start this plan' }));
  await settle();

  const alert = screen.getByRole('alert');
  expect(alert).toHaveTextContent(/can’t tell whether it saved/i);
  expect(alert).toHaveTextContent(/reload/i);
  expect(alert.textContent).not.toMatch(/nothing was saved|so nothing was|is untouched/i);
});

it('tells a stale page to reload rather than showing it the generic failure', async () => {
  // `_START_DATE_BACKDATE_DAYS` is 7, and the client sends the date the preview showed — so a
  // tab open more than eight days is a 422, and the generic sentence would send the reader
  // hunting a fault that is not there.
  stubFetch({
    create: () =>
      Promise.resolve(json({ detail: 'start_date must be no more than 7 days in the past' }, 422)),
  });
  renderPlan();

  fireEvent.click(await screen.findByRole('button', { name: 'Start this plan' }));
  await settle();

  expect(screen.getByRole('alert')).toHaveTextContent(/open too long.*Reload it/i);
});
