import { QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider, createMemoryHistory } from '@tanstack/react-router';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

import type {
  ExerciseLibrary,
  PlanBlock,
  PlanSession,
  PlanTree,
  Profile,
  Vocabulary,
} from './api/types';
import { AuthProvider, createAuth } from './auth/AuthProvider';
import { PHASE_STORAGE_KEY } from './plan/phaseToggles';
import { createAppRouter, createQueryClient } from './router';
import { localIsoDate } from './session/today';

/* Clicking a phase must EXPAND it, THEN scroll, THEN move focus (#93) — asserted against SCOPED
   elements. CLAUDE.md "The plan timeline is measured in DAYS" carries why the ORDER is load-bearing. */
const TARGET_GRADE_ID = 11;
const CURRENT_GRADE_ID = 10;
const FINGERS_ID = 1;
const PLAN_ID = 88;

/** The anchor spelled as an independent literal, never imported from the component under test. */
const SECOND_PHASE_ANCHOR = 'ct-phase-2';

function daysAgo(days: number): string {
  return localIsoDate(new Date(Date.now() - days * 86_400_000));
}

const TODAY = daysAgo(0);
const NEXT_WEEK = daysAgo(-7);

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
    phases: ['base', 'strength'],
    session_statuses: ['planned'],
  },
};

const PLANNABLE: Profile = {
  email: 'a@example.com',
  display_name: null,
  target_grade_id: TARGET_GRADE_ID,
  current_grade_id: CURRENT_GRADE_ID,
  primary_discipline: 'boulder',
  sessions_per_week: 1,
  available_weekdays: 0b1111111,
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

function block(id: number): PlanBlock {
  return {
    id,
    order_index: 0,
    exercise_key: 'weighted_max_hangs',
    exercise_id: 3,
    aspect_key: 'finger_strength',
    protocol_kind: 'max_hang',
    rest_after_seconds: 180,
    rest_between_sets_seconds: 120,
    shortfall: null,
    sets: [],
  };
}

/** Monday-first, as `planned_session.weekday` is. */
function weekdayOf(iso: string): number {
  const day = new Date(`${iso}T00:00:00`).getDay();
  return day === 0 ? 6 : day - 1;
}

function session(id: number, scheduledOn: string): PlanSession {
  return {
    id,
    weekday: weekdayOf(scheduledOn),
    scheduled_on: scheduledOn,
    title: 'Finger strength',
    activity_kind: 'climbing',
    estimated_minutes: 60,
    status: 'planned',
    shortfalls: [],
    blocks: [block(id * 10)],
  };
}

/** Week 1 is today's phase, so week 2's phase starts COLLAPSED — the state the jump needs. */
const PLAN: PlanTree = {
  id: PLAN_ID,
  climbing_band: null,
  name: 'Road to 6B',
  start_date: TODAY,
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
          start_date: TODAY,
          sessions: [session(901, TODAY)],
        },
      ],
    },
    {
      id: 102,
      phase: 'strength',
      start_week: 2,
      end_week: 2,
      microcycles: [
        {
          id: 202,
          week_no: 2,
          phase: 'strength',
          is_deload: false,
          start_date: NEXT_WEEK,
          sessions: [session(902, NEXT_WEEK)],
        },
      ],
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

/** jsdom has no `matchMedia`; `vi.unstubAllGlobals` removes it again after each test. */
function stubReducedMotion(reduce: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: reduce && query.includes('prefers-reduced-motion'),
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  }));
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
      if (path === '/api/sessions/completion')
        return Promise.resolve(json({ as_of: TODAY, sessions: [] }));
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

/** Every scroll and focus, in the order they happened: the ORDER is half the invariant. */
const moves: string[] = [];
let scrollIntoView: PropertyDescriptor | undefined;
let focus: PropertyDescriptor | undefined;

beforeEach(() => {
  localStorage.removeItem(PHASE_STORAGE_KEY);
  stubFetch();
  stubReducedMotion(false);
  moves.length = 0;
  scrollIntoView = Object.getOwnPropertyDescriptor(Element.prototype, 'scrollIntoView');
  focus = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'focus');
  Object.defineProperty(Element.prototype, 'scrollIntoView', {
    configurable: true,
    writable: true,
    value: function record(this: Element, options?: ScrollIntoViewOptions) {
      moves.push(`scroll:${this.id || this.localName}:${String(options?.behavior)}`);
    },
  });
  Object.defineProperty(HTMLElement.prototype, 'focus', {
    configurable: true,
    writable: true,
    value: function record(this: HTMLElement, options?: FocusOptions) {
      moves.push(`focus:${this.localName}:${String(options?.preventScroll)}`);
    },
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
  if (scrollIntoView !== undefined)
    Object.defineProperty(Element.prototype, 'scrollIntoView', scrollIntoView);
  else delete (Element.prototype as unknown as Record<string, unknown>).scrollIntoView;
  if (focus !== undefined) Object.defineProperty(HTMLElement.prototype, 'focus', focus);
});

function phaseSection(anchor: string): HTMLElement {
  const section = document.getElementById(anchor);
  expect(section, `no phase section anchored at ${anchor}`).not.toBeNull();
  return section as HTMLElement;
}

function disclosureOf(section: HTMLElement): HTMLDetailsElement {
  const details = section.querySelector<HTMLDetailsElement>(':scope > details');
  expect(details).not.toBeNull();
  return details as HTMLDetailsElement;
}

it('expands the phase, THEN scrolls to it, THEN moves focus into it', async () => {
  renderPlan();
  expect(await screen.findByRole('button', { name: 'Build a different plan' })).toBeInTheDocument();
  await settle();

  const section = phaseSection(SECOND_PHASE_ANCHOR);
  // The precondition, which is what makes the ordering matter: week 2's phase is COLLAPSED,
  // because the default open set is the block the climber is standing in.
  expect(disclosureOf(section).open).toBe(false);
  expect(moves).toEqual([]);

  const callout = screen.getByRole('button', { name: /Strength, 1 week, week 2/ });
  fireEvent.click(callout);
  await settle();

  expect(disclosureOf(section).open).toBe(true);
  // Scrolled to the SECTION, and focus landed on that section's own summary with
  // `preventScroll` — in that order, so the scroll was measured against a laid-out phase.
  expect(moves).toEqual([`scroll:${SECOND_PHASE_ANCHOR}:smooth`, 'focus:summary:true']);
});

it('scrolls INSTANTLY when reduced motion is preferred', async () => {
  stubFetch();
  stubReducedMotion(true);
  renderPlan();
  expect(await screen.findByRole('button', { name: 'Build a different plan' })).toBeInTheDocument();
  await settle();

  fireEvent.click(screen.getByRole('button', { name: /Strength, 1 week, week 2/ }));
  await settle();

  // Reduced motion covers programmatic scrolling too — the movement still happens, instantly.
  expect(moves).toEqual([`scroll:${SECOND_PHASE_ANCHOR}:auto`, 'focus:summary:true']);
});

it('persists the newly opened phase under `ct:planPhases`, alongside the one already open', async () => {
  renderPlan();
  expect(await screen.findByRole('button', { name: 'Build a different plan' })).toBeInTheDocument();
  await settle();

  fireEvent.click(screen.getByRole('button', { name: /Strength, 1 week, week 2/ }));
  await settle();

  const stored: unknown = JSON.parse(localStorage.getItem(PHASE_STORAGE_KEY) ?? 'null');
  expect(stored).toEqual({ v: 1, plan: `plan:${String(PLAN_ID)}`, open: [1, 2] });
});

it('names the current phase in the callout, and only that one', async () => {
  renderPlan();
  expect(await screen.findByRole('button', { name: 'Build a different plan' })).toBeInTheDocument();
  await settle();

  const timeline = document.querySelector('.ct-app__timeline');
  expect(timeline).not.toBeNull();
  const named = [...(timeline?.querySelectorAll('button') ?? [])].map((button) =>
    button.getAttribute('aria-label'),
  );
  expect(named).toEqual([
    'Base, 1 week, week 1, the phase you are in now',
    'Strength, 1 week, week 2',
  ]);
});
