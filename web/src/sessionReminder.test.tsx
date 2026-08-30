import { QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider, createMemoryHistory } from '@tanstack/react-router';
import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

import type { ExerciseLibrary, PlanSession, PlanTree, Vocabulary } from './api/types';
import { AuthProvider, createAuth } from './auth/AuthProvider';
import { createAppRouter, createQueryClient } from './router';
import { makeBlock, makeSession, makeSet, makeVocabulary } from './session/fixtures';
import { localIsoDate } from './session/today';

/** The brief's phase reminder (#87), in the two places only a rendered test can look: a REST DAY,
 *  where it must describe the NEXT session's block, and a vocabulary still in flight. */
const TODAY = localIsoDate(new Date());
const DAY_MS = 86_400_000;
const LIBRARY: ExerciseLibrary = { exercises: [] };

const isoAt = (offsetDays: number) =>
  new Date(new Date(`${TODAY}T12:00:00Z`).getTime() + offsetDays * DAY_MS)
    .toISOString()
    .slice(0, 10);

function sessionInWeek(weekNo: number, scheduledOn: string): PlanSession {
  const block = makeBlock({ sets: [makeSet({ id: 500 + weekNo, target_work_seconds: 10 })] });
  return { ...makeSession([block], scheduledOn), id: weekNo, title: `Week ${String(weekNo)}` };
}

/** Deload at week 4 then strength at 5–7, inside a 28-week plan: the owner's real shape.
 *  `anchorWeek`'s session lands `offsetDays` from today, so one fixture serves both days. */
function makeTree(anchorWeek: number, offsetDays: number): PlanTree {
  const dateOf = (weekNo: number) => isoAt((weekNo - anchorWeek) * 7 + offsetDays);
  const weekOf = (weekNo: number, phase: 'deload' | 'strength') => ({
    id: weekNo,
    is_deload: phase === 'deload',
    phase,
    sessions: [sessionInWeek(weekNo, dateOf(weekNo))],
    start_date: dateOf(weekNo),
    week_no: weekNo,
  });

  return {
    activated_at: '2026-09-01T10:00:00Z',
    climbing_band: null,
    current_grade_id: null,
    discipline: 'sport',
    generator_input: {},
    generator_version: '1.0.0',
    grade_gap: 5,
    id: 7,
    mesocycles: [
      { id: 91, phase: 'deload', start_week: 4, end_week: 4, microcycles: [weekOf(4, 'deload')] },
      {
        id: 92,
        phase: 'strength',
        start_week: 5,
        end_week: 7,
        microcycles: [5, 6, 7].map((weekNo) => weekOf(weekNo, 'strength')),
      },
    ],
    name: 'Road to 7b',
    notes: [],
    shortfalls: [],
    start_date: '2026-09-07',
    target_grade_id: null,
    week_count: 28,
  };
}

/** `null` for the vocabulary means a request that never settles — the loading case. */
function stubFetch(plan: PlanTree, vocabulary: Vocabulary | null) {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: unknown) => {
      const path = new URL(typeof input === 'string' ? input : String(input), 'http://localhost')
        .pathname;
      if (path === '/api/library') return Promise.resolve(json(LIBRARY));
      if (path === '/api/plans/active') return Promise.resolve(json({ plan }));
      if (path === '/api/vocabulary') {
        return vocabulary === null
          ? new Promise(() => undefined)
          : Promise.resolve(json(vocabulary));
      }
      return Promise.reject(new Error(`unexpected request: ${path}`));
    }),
  );
}

const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });

function renderSession() {
  const auth = createAuth();
  auth.session.set('user-token', 'user');
  const queryClient = createQueryClient();
  const router = createAppRouter(createMemoryHistory({ initialEntries: ['/session'] }), {
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

/** The badges, as one string per badge, so an assertion reads like the screen. `span`, because
 *  the paragraph wrapping them matches the pattern too. */
const badges = () =>
  screen.queryAllByText(/^(Week|Block): /, { selector: 'span' }).map((node) => node.textContent);

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

it('names the week and the block of today’s session, with the phase copy disclosed', async () => {
  stubFetch(makeTree(6, 0), makeVocabulary());
  renderSession();

  expect(await screen.findByRole('heading', { name: /Week 6/ })).toBeTruthy();
  expect(badges()).toEqual(['Week: 6 of 28', 'Block: Max strength · wk 5–7']);
  expect(screen.getByText('Why this phase')).toBeTruthy();
  expect(screen.getByText('what max strength is')).toBeTruthy();
  // Collapsed: 600 characters of prose do not belong above the Start button.
  expect(screen.getByText('Why this phase').closest('details')?.open).toBe(false);
});

it('⚠️ on a rest day describes the NEXT session’s block, not the deload week today is in', async () => {
  // Nothing today; week 5's session is in two days, and today sits in the week-4 deload.
  stubFetch(makeTree(5, 2), makeVocabulary());
  renderSession();

  expect(await screen.findByText(/Today is a rest day/)).toBeTruthy();
  expect(badges()).toEqual(['Week: 5 of 28', 'Block: Max strength · wk 5–7']);
  expect(screen.queryByText('what a deload is')).toBeNull();
});

it('renders the whole brief with no reminder while the vocabulary is still in flight', async () => {
  stubFetch(makeTree(6, 0), null);
  renderSession();

  expect(await screen.findByRole('button', { name: 'Start session' })).toBeTruthy();
  expect(screen.getByRole('heading', { name: /Week 6/ })).toBeTruthy();
  expect(badges()).toEqual([]);
  expect(screen.queryByText('Why this phase')).toBeNull();
});
