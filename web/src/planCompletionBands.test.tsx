import { QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider, createMemoryHistory } from '@tanstack/react-router';
import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

import type {
  ExerciseLibrary,
  PlanBlock,
  PlanSession,
  PlanTree,
  Profile,
  SessionCompletionResponse,
  Vocabulary,
} from './api/types';
import { AuthProvider, createAuth } from './auth/AuthProvider';
import { PHASE_STORAGE_KEY } from './plan/phaseToggles';
import { createAppRouter, createQueryClient } from './router';
import { localIsoDate } from './session/today';

/**
 * **The completion band must be a property of the BADGE, not of anything above it (#95).**
 *
 * The shipped bug, in Kilian's words: *"when you have a phase 75% done, and it shows the yellow,
 * now the completed inside show with yellow too instead of green."* `_profile.scss` keyed its band
 * rules on an ANCESTOR — `.ct-app__disclosure[data-completion='partial'] .ct-app__completion` —
 * and a phase `<details>` and a session `<details>` are BOTH `ct-app__disclosure`. Once the phase
 * carried an aggregate band (#92) it matched as an ancestor of every session badge inside it, the
 * two rules tied on specificity, and source order handed it to the phase.
 *
 * ⚠️ **jsdom applies none of the compiled SCSS, so this test cannot see a colour.** What it can
 * see — and what the fix rests on — is that the RENDERED MARKUP ALONE determines the colour: each
 * badge carries its own `data-completion`, so there is no ancestor left for a rule to key on.
 * `markupCss.test.ts::lets no completion band leak from an ancestor` is the other half, and it is
 * the one that reads the stylesheet and forbids the selector shape coming back.
 *
 * Through the real router, query client and API client, for `planPersist.test.tsx`'s reason: the
 * badge is produced by the seam between the plan read and the completion read, and a harness that
 * rendered a hand-built tree would assert my fixture rather than the screen.
 */
const TARGET_GRADE_ID = 11;
const CURRENT_GRADE_ID = 10;
const FINGERS_ID = 1;
const PLAN_ID = 88;
const DONE_SESSION_ID = 901;
const HALF_SESSION_ID = 902;
const FUTURE_SESSION_ID = 903;

/** `session_block.id`, which is what `done_block_ids` names and what a block row is marked by. */
function blockIdsOf(sessionId: number): [number, number] {
  return [sessionId * 10, sessionId * 10 + 5];
}

/** Days back from the machine's own clock, not literals: `phaseCompletionBadge` only scores a
 *  phase ENTIRELY in the past, so a hard-coded date would rot into a green-for-nothing pass. */
function daysAgo(days: number): string {
  return localIsoDate(new Date(Date.now() - days * 86_400_000));
}

const TWO_DAYS_AGO = daysAgo(2);
const THREE_DAYS_AGO = daysAgo(3);
const IN_TWO_DAYS = daysAgo(-2);

const VOCABULARY: Vocabulary = {
  grade_systems: [{ id: 1, key: 'font', name: 'Fontainebleau', discipline: 'boulder' }],
  grades: [
    { id: CURRENT_GRADE_ID, grade_system_id: 1, label: '6A', ordinal: 1010 },
    { id: TARGET_GRADE_ID, grade_system_id: 1, label: '6B', ordinal: 1012 },
  ],
  climbing_aspects: [
    { id: FINGERS_ID, key: 'finger_strength', name: 'Finger strength', description: 'Force.' },
  ],
  equipment: [{ id: 5, key: 'hangboard', name: 'Hangboard', description: 'Edges.' }],
  injury_areas: [],
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

const PLANNABLE: Profile = {
  email: 'a@example.com',
  display_name: null,
  target_grade_id: TARGET_GRADE_ID,
  current_grade_id: CURRENT_GRADE_ID,
  primary_discipline: 'boulder',
  sessions_per_week: 2,
  available_weekdays: 0b0010101,
  strength_aspect_id: FINGERS_ID,
  weakness_aspect_id: null,
  show_body_metrics: true,
  injuries_reviewed_at: '2026-08-20T00:00:00Z',
  aspect_ratings: [{ climbing_aspect_id: FINGERS_ID, score: 5, rated_at: '2026-08-21T00:00:00Z' }],
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

/** TWO blocks per session, so a card has a done part AND a missed part to distinguish. */
function block(blockId: number, orderIndex: number): PlanBlock {
  return {
    id: blockId,
    order_index: orderIndex,
    exercise_key: 'weighted_max_hangs',
    exercise_id: 3,
    aspect_key: 'finger_strength',
    protocol_kind: 'max_hang',
    rest_after_seconds: 180,
    rest_between_sets_seconds: 120,
    shortfall: null,
    sets: [
      {
        id: blockId + 1,
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
  };
}

function session(id: number, weekday: number, scheduledOn: string, title: string): PlanSession {
  const [first, second] = blockIdsOf(id);
  return {
    id,
    weekday,
    scheduled_on: scheduledOn,
    title,
    activity_kind: 'climbing',
    estimated_minutes: 60,
    status: 'planned',
    shortfalls: [],
    blocks: [block(first, 0), block(second, 1)],
  };
}

/** One phase, wholly in the past, with two sessions — the shape the bug needs. */
const PLAN: PlanTree = {
  id: PLAN_ID,
  climbing_band: null,
  name: 'Road to 6B',
  start_date: THREE_DAYS_AGO,
  week_count: 2,
  discipline: 'boulder',
  target_grade_id: TARGET_GRADE_ID,
  current_grade_id: CURRENT_GRADE_ID,
  grade_gap: 2,
  generator_version: '1.0.0',
  generator_input: { library_digest: 'abc' },
  activated_at: '2026-08-20T10:00:00Z',
  notes: [],
  shortfalls: [],
  mesocycles: [
    {
      id: 101,
      phase: 'base',
      start_week: 1,
      end_week: 1,
      microcycles: [
        {
          id: 201,
          week_no: 1,
          phase: 'base',
          is_deload: false,
          start_date: THREE_DAYS_AGO,
          sessions: [
            session(DONE_SESSION_ID, 0, THREE_DAYS_AGO, 'Finger strength'),
            session(HALF_SESSION_ID, 2, TWO_DAYS_AGO, 'Core tension'),
          ],
        },
      ],
    },
    // A SECOND phase, wholly ahead: it carries no aggregate (`phaseCompletionBadge` scores only a
    // phase entirely in the past), which is exactly the unmarked case the block marks owe too.
    {
      id: 102,
      phase: 'base',
      start_week: 2,
      end_week: 2,
      microcycles: [
        {
          id: 202,
          week_no: 2,
          phase: 'base',
          is_deload: false,
          start_date: IN_TWO_DAYS,
          sessions: [session(FUTURE_SESSION_ID, 4, IN_TWO_DAYS, 'Power endurance')],
        },
      ],
    },
  ],
};

/**
 * 100% and 50% over two equally weighted sessions is a phase mean of 75 — `partial` — around a
 * session that is `full`. That is precisely the pair the ancestor-keyed rule repainted.
 */
const COMPLETION: SessionCompletionResponse = {
  as_of: daysAgo(0),
  sessions: [
    {
      planned_session_id: DONE_SESSION_ID,
      scheduled_on: THREE_DAYS_AGO,
      state: 'completed',
      status: 'completed',
      block_count: 2,
      blocks_done: 2,
      done_block_ids: blockIdsOf(DONE_SESSION_ID),
      percent: 100,
    },
    {
      // The FIRST of its two blocks only: the other is the part Kilian could not see.
      planned_session_id: HALF_SESSION_ID,
      scheduled_on: TWO_DAYS_AGO,
      state: 'skipped',
      status: 'in_progress',
      block_count: 2,
      blocks_done: 1,
      done_block_ids: [blockIdsOf(HALF_SESSION_ID)[0]],
      percent: 50,
    },
    {
      // A real `pending` row, not an absent one: the server sends this for a future session, and
      // 0 of 2 done must still leave both rows unmarked.
      planned_session_id: FUTURE_SESSION_ID,
      scheduled_on: IN_TWO_DAYS,
      state: 'pending',
      status: 'planned',
      block_count: 2,
      blocks_done: 0,
      done_block_ids: [],
      percent: 0,
    },
  ],
};

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

function urlOf(input: unknown): string {
  if (typeof input === 'string') return input;
  if (input instanceof URL) return input.href;
  return input instanceof Request ? input.url : '';
}

function stubFetch() {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: unknown) => {
      const path = new URL(urlOf(input), 'http://localhost').pathname;
      if (path === '/api/vocabulary') return Promise.resolve(json(VOCABULARY));
      if (path === '/api/profile') return Promise.resolve(json(PLANNABLE));
      if (path === '/api/library') return Promise.resolve(json(LIBRARY));
      if (path === '/api/plans/active') return Promise.resolve(json({ plan: PLAN }));
      if (path === '/api/sessions/completion') return Promise.resolve(json(COMPLETION));
      return Promise.reject(new Error(`unexpected request: ${path}`));
    }),
  );
}

async function settle(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

function renderPlan() {
  const auth = createAuth();
  auth.session.set('user-token', 'user');
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
}

/** The badge inside a disclosure's OWN summary, i.e. never one belonging to a nested card. */
function badgeOf(disclosure: Element): HTMLElement | null {
  return disclosure.querySelector<HTMLElement>(':scope > summary > .ct-app__completion');
}

/** One card's block rows, in render order. */
function partsOf(disclosure: Element): HTMLElement[] {
  return [...disclosure.querySelectorAll<HTMLElement>(':scope > ul.ct-app__terms > li')];
}

/** The session card whose own summary carries `title`. */
function cardTitled(title: string): Element {
  const found = [...document.querySelectorAll(SESSION)].find((card) =>
    card.querySelector(':scope > summary')?.textContent?.includes(title),
  );
  expect(found, `no session card titled ${title}`).toBeDefined();
  return found as Element;
}

const PHASE = '.ct-app__disclosure--phase';
const SESSION = '.ct-app__disclosure:not(.ct-app__disclosure--phase)';

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

beforeEach(() => {
  localStorage.removeItem(PHASE_STORAGE_KEY);
  stubFetch();
});

it('gives a 100% session badge its OWN full band inside a 75% phase', async () => {
  renderPlan();
  expect(await screen.findByRole('button', { name: 'Build a different plan' })).toBeInTheDocument();
  await settle();

  // The fixture really is the shape the bug needs: an amber phase around a green session.
  const phase = document.querySelector(PHASE);
  expect(phase).not.toBeNull();
  const phaseBadge = badgeOf(phase as Element);
  expect(phaseBadge?.textContent).toBe('75% done');
  expect(phaseBadge?.dataset.completion).toBe('partial');

  const sessions = [...document.querySelectorAll(SESSION)].filter((card) => badgeOf(card) !== null);
  expect(sessions).toHaveLength(2);
  // Both session cards are DESCENDANTS of the amber phase — the ancestor relationship that
  // caused the bug is present, so a pass here is not the absence of the condition.
  for (const card of sessions) expect(phase?.contains(card)).toBe(true);

  const bands = sessions.map((card) => [
    badgeOf(card)?.textContent,
    badgeOf(card)?.dataset.completion,
  ]);
  // ⚠️ THE REGRESSION: the completed session reads `full` on its own element. Before the fix
  // this attribute did not exist at all and the colour came from the phase above it.
  expect(bands).toEqual([
    ['Completed', 'full'],
    ['50% done', 'partial'],
  ]);
});

it('leaves every completion badge self-describing, so no ancestor is consulted', async () => {
  renderPlan();
  expect(await screen.findByRole('button', { name: 'Build a different plan' })).toBeInTheDocument();
  await settle();

  const badges = [...document.querySelectorAll<HTMLElement>('.ct-app__completion')];
  expect(badges.length).toBeGreaterThanOrEqual(3);
  // Every badge on the screen, not only the interesting one: a band read from an ancestor is
  // exactly a badge with no band of its own.
  expect(badges.filter((badge) => badge.dataset.completion === undefined)).toEqual([]);
  expect(new Set(badges.map((badge) => badge.dataset.completion))).toEqual(
    new Set(['full', 'partial']),
  );
});

it('marks every block of a PAST session done or missed, in words as well as colour', async () => {
  renderPlan();
  expect(await screen.findByRole('button', { name: 'Build a different plan' })).toBeInTheDocument();
  await settle();

  // Kilian: "i can see that thursday i did 33% done, but i cant see which part of it i missed".
  const half = partsOf(cardTitled('Core tension'));
  expect(half).toHaveLength(2);
  expect(half.map((part) => part.dataset.done)).toEqual(['done', 'missed']);
  // ⚠️ The WORD, on the row itself — a colourblind or screenreader user gets the same fact.
  expect(half.map((part) => part.querySelector('.ct-app__mark')?.textContent)).toEqual([
    'Done',
    'Missed',
  ]);
  // Self-describing on BOTH elements, so nothing above a row decides its colour.
  for (const part of half) {
    expect(part.querySelector<HTMLElement>('.ct-app__mark')?.dataset.done).toBe(part.dataset.done);
  }
  // …and a 100% session inside the same phase marks both of its own rows done.
  expect(partsOf(cardTitled('Finger strength')).map((part) => part.dataset.done)).toEqual([
    'done',
    'done',
  ]);
});

it('leaves a FUTURE session unmarked: nobody has missed a block they cannot have done', async () => {
  renderPlan();
  expect(await screen.findByRole('button', { name: 'Build a different plan' })).toBeInTheDocument();
  await settle();

  const future = cardTitled('Power endurance');
  expect(badgeOf(future)).toBeNull();
  const parts = partsOf(future);
  // The rows are really there — this is an absent MARK, not an absent session.
  expect(parts).toHaveLength(2);
  expect(parts.map((part) => part.dataset.done)).toEqual([undefined, undefined]);
  expect(future.querySelectorAll('.ct-app__mark')).toHaveLength(0);
});
