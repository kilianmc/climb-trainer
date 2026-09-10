import { QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider, createMemoryHistory } from '@tanstack/react-router';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Journal, JournalEntry, JournalPlan, Profile, Vocabulary } from './api/types';
import { AuthProvider, createAuth } from './auth/AuthProvider';
import { createAppRouter, createQueryClient } from './router';
import { forbiddenCopyHits } from './test/forbiddenCopy';

/** `/diary`, through the real router, query client and API client — `planPersist`'s harness. */
const ACTIVE_PLAN_ID = 7;
const OLD_PLAN_ID = 2;
const UUID_ONE = '11111111-1111-4111-8111-111111111111';
const UUID_TWO = '22222222-2222-4222-8222-222222222222';
const UUID_ORPHAN = '33333333-3333-4333-8333-333333333333';

const VOCABULARY: Vocabulary = {
  grade_systems: [],
  grades: [],
  climbing_aspects: [],
  equipment: [],
  injury_areas: [],
  plan_goal: '',
  phase_guide: [
    {
      phase: 'strength',
      label: 'Max strength',
      summary: 'Heavy and brief.',
      how_to_train: 'Load hard.',
      links: [],
    },
  ],
  enums: {
    disciplines: ['boulder', 'sport'],
    activity_kinds: ['climbing'],
    ascent_styles: ['redpoint'],
    protocol_kinds: ['max_hang'],
    phases: ['base', 'strength'],
    session_statuses: ['planned'],
  },
};

const PROFILE: Profile = {
  email: 'a@example.com',
  display_name: null,
  target_grade_id: null,
  current_grade_id: null,
  primary_discipline: 'boulder',
  sessions_per_week: 3,
  available_weekdays: 0b0010101,
  strength_aspect_id: null,
  weakness_aspect_id: null,
  show_body_metrics: true,
  injuries_reviewed_at: null,
  aspect_ratings: [],
  injuries: [],
};

function entry(overrides: Partial<JournalEntry> = {}): JournalEntry {
  return {
    id: 1,
    client_uuid: UUID_ONE,
    entry_date: '2026-05-12',
    body: 'crimps felt sharp',
    feel: 4,
    sleep_quality: 3,
    skin: 2,
    body_weight_kg: '71.4',
    logged_session_id: 909,
    plan: { plan_id: ACTIVE_PLAN_ID, phase: 'strength', week_no: 3 },
    ...overrides,
  };
}

/** The chart's x axis is the PLAN's span, so the entries sit well inside it, not at the edges. */
const PLAN_START = '2026-05-01';

/** ⚠️ The axis is ruled in weeks off `microcycles[].start_date` — the plan's OWN boundaries. The
 *  stub carries them because a `start_date` divided by seven is exactly what must not happen. */
const ACTIVE_PLAN = {
  id: ACTIVE_PLAN_ID,
  name: 'Road to 6B',
  start_date: PLAN_START,
  week_count: 8,
  mesocycles: [
    {
      phase: 'strength',
      start_week: 1,
      end_week: 8,
      microcycles: Array.from({ length: 8 }, (_unused, index) => ({
        week_no: index + 1,
        phase: 'strength',
        is_deload: false,
        sessions: [],
        start_date: new Date(Date.UTC(2026, 4, 1) + index * 7 * 86_400_000)
          .toISOString()
          .slice(0, 10),
      })),
    },
  ],
};

/** Seven points, because the server only sends the mean once it has a full window. */
function trend(base: number): { entry_date: string; value: number }[] {
  return Array.from({ length: 7 }, (_unused, index) => ({
    entry_date: `2026-05-${String(index + 1).padStart(2, '0')}`,
    value: base + index * 0.1,
  }));
}

/** ⚠️ The `plans` lookup: one row per plan the entries reference, carrying that plan's NAME
 *  once and its STORED week starts — which is every old plan's only ruler. */
function weekRows(startUtc: number, count: number) {
  return Array.from({ length: count }, (_unused, index) => ({
    week_no: index + 1,
    start_date: new Date(startUtc + index * 7 * 86_400_000).toISOString().slice(0, 10),
  }));
}

const ACTIVE_PLAN_ROW: JournalPlan = {
  plan_id: ACTIVE_PLAN_ID,
  name: 'Road to 6B',
  weeks: weekRows(Date.UTC(2026, 4, 1), 8),
};

const OLD_PLAN_ROW: JournalPlan = {
  plan_id: OLD_PLAN_ID,
  name: 'Winter base',
  weeks: weekRows(Date.UTC(2025, 10, 2), 4),
};

const SCOPED: Journal = {
  entries: [entry(), entry({ id: 2, client_uuid: UUID_TWO, entry_date: '2026-05-04' })],
  plans: [ACTIVE_PLAN_ROW],
  trends: { body_weight_kg: trend(71), body_weight_direction: 'up' },
  truncated: false,
  has_entries_outside_plan: true,
};

const UNSCOPED: Journal = {
  entries: [
    ...SCOPED.entries,
    entry({
      id: 3,
      client_uuid: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      entry_date: '2025-11-02',
      plan: { plan_id: OLD_PLAN_ID, phase: 'base', week_no: 1 },
    }),
    entry({ id: 4, client_uuid: UUID_ORPHAN, entry_date: '2025-01-01', plan: null }),
  ],
  plans: [ACTIVE_PLAN_ROW, OLD_PLAN_ROW],
  trends: SCOPED.trends,
  truncated: true,
  has_entries_outside_plan: false,
};

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

function urlOf(input: unknown): string {
  if (typeof input === 'string') return input;
  if (input instanceof URL) return input.href;
  return input instanceof Request ? input.url : '';
}

/** Every diary read, and every PUT body, so what went on the wire is assertable. */
let reads: URL[] = [];
let puts: { path: string; body: unknown }[] = [];
let profile: Profile = PROFILE;
let scopedBody: Journal = SCOPED;
/** Every rename that reached the wire, and what the server answers it with. */
let renames: { path: string; body: unknown }[] = [];
let renameStatus = 200;
/** Held open, the UNSCOPED read stays in flight so the scope switch can be observed mid-flight
 *  rather than one already-resolved tick later. `null` is the default: resolve immediately. */
let unscopedGate: Promise<void> | null = null;

function stubFetch() {
  reads = [];
  puts = [];
  renames = [];
  renameStatus = 200;
  vi.stubGlobal(
    'fetch',
    vi.fn((input: unknown, init?: RequestInit) => {
      const url = new URL(urlOf(input), 'http://localhost');
      const path = url.pathname;
      if (path === '/api/vocabulary') return Promise.resolve(json(VOCABULARY));
      if (path === '/api/profile') return Promise.resolve(json(profile));
      if (path === '/api/plans/active') {
        return Promise.resolve(json({ plan: ACTIVE_PLAN }));
      }
      const renamed = /^\/api\/plans\/(\d+)\/name$/.exec(path);
      if (renamed !== null) {
        const sent = typeof init?.body === 'string' ? init.body : 'null';
        renames.push({ path, body: JSON.parse(sent) });
        if (renameStatus !== 200) return Promise.resolve(json({ detail: 'no' }, renameStatus));
        // ⚠️ The real server STRIPS and echoes what it STORED, which is the whole reason the
        // reply carries a name at all — `server/plans/routes.py::PlanNameResponse`.
        const typed = (JSON.parse(sent) as { name: string }).name;
        return Promise.resolve(json({ id: Number(renamed[1]), name: typed.trim() }));
      }
      if (path === '/api/journal') {
        reads.push(url);
        const planId = url.searchParams.get('plan_id');
        if (planId === null && unscopedGate !== null) {
          return unscopedGate.then(() => json(UNSCOPED));
        }
        return Promise.resolve(json(planId === null ? UNSCOPED : scopedBody));
      }
      if (path.startsWith('/api/journal/')) {
        const sent = typeof init?.body === 'string' ? init.body : 'null';
        puts.push({ path, body: JSON.parse(sent) });
        return Promise.resolve(
          json({
            id: 1,
            client_uuid: path.slice('/api/journal/'.length),
            entry_date: '2026-05-12',
            logged_session_id: 909,
          }),
        );
      }
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

function renderDiary(tokenScope: 'user' | 'demo' = 'user') {
  const auth = createAuth();
  auth.session.set(`${tokenScope}-token`, tokenScope);
  const queryClient = createQueryClient();
  const router = createAppRouter(createMemoryHistory({ initialEntries: ['/diary'] }), {
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

/** The list is loaded once this row is on screen. */
const FIRST_ROW = /12 May 2026/;

/** The sort control's accessible name says which order the list is IN and what pressing it does,
 *  so one button can carry the state the caption used to spell out. */
const SORT_NEWEST = 'Newest first — switch to oldest first';
const SORT_OLDEST = 'Oldest first — switch to newest first';

/** The PLAN order is a second control with a second job: which old section leads. */
const PLAN_SORT_NEWEST = 'Newest plan first — switch to oldest plan first';

afterEach(() => {
  vi.unstubAllGlobals();
  profile = PROFILE;
  scopedBody = SCOPED;
  unscopedGate = null;
  localStorage.clear();
});

beforeEach(() => {
  stubFetch();
});

describe('the entry list', () => {
  it('shows the plan, the phase and the week on the row, phase copy from the vocabulary', async () => {
    renderDiary();
    const row = await screen.findByRole('button', { name: FIRST_ROW });
    await settle();
    // "Max strength" is the GUIDE's label; "strength" is the enum value the server sent.
    expect(row.textContent).toContain('Road to 6B');
    expect(row.textContent).toContain('Max strength');
    expect(row.textContent).toContain('wk 3');
  });

  it('carries the entry’s own words, and a row with none is still an entry', async () => {
    scopedBody = {
      ...SCOPED,
      entries: [
        entry(),
        entry({ id: 2, client_uuid: UUID_TWO, entry_date: '2026-05-04', body: null }),
      ],
    };
    renderDiary();
    const written = await screen.findByRole('button', { name: FIRST_ROW });
    expect(written.querySelector('.ct-app__diarytext')?.textContent).toBe('crimps felt sharp');
    // ⚠️ NORMAL: an entry can be only a weigh-in or only scores, so the row offers no
    // words rather than reading as broken — and everything else about it is still there.
    const bare = await screen.findByRole('button', { name: /4 May 2026/ });
    expect(bare.querySelector('.ct-app__diarytext')).toBeNull();
    expect(bare.textContent).toContain('Road to 6B');
    expect(bare.querySelector('.ct-app__diaryweek')?.textContent).toBe('wk 3');
    expect(bare.textContent).not.toMatch(/error|unknown|missing/i);
  });

  it('names the phase by its short code, the full name CLIPPED rather than dropped', async () => {
    renderDiary();
    // The guide's own label is still the button's accessible name: the code is `aria-hidden`.
    const row = await screen.findByRole('button', { name: /12 May 2026.*Max strength/ });
    const phase = row.querySelector('.ct-app__diaryphase');
    expect(phase?.querySelector('.ct-app__full')?.textContent).toBe('Max strength');
    expect(phase?.querySelector('.ct-app__abbr')?.textContent).toBe('S');
    expect(phase?.querySelector('.ct-app__abbr')?.getAttribute('aria-hidden')).toBe('true');
  });

  it('reads honestly for an entry no plan can claim', async () => {
    renderDiary();
    await screen.findByRole('button', { name: FIRST_ROW });
    fireEvent.click(screen.getByRole('button', { name: 'Show old plans' }));
    const orphan = await screen.findByRole('button', { name: /1 Jan 2025/ });
    expect(orphan.textContent).toContain('Not part of a plan');
    expect(document.body.textContent).not.toMatch(/error|unknown|missing/i);
  });

  it('says so plainly when a read was cut short', async () => {
    renderDiary();
    await screen.findByRole('button', { name: FIRST_ROW });
    expect(document.body.textContent).not.toMatch(/as far back as one read goes/i);
    fireEvent.click(screen.getByRole('button', { name: 'Show old plans' }));
    // ⚠️ `findBy*` POLLS. `settle()` is one macrotask, and the whole-history read is a second
    // request that can land after it — a fixed tick makes this a coin toss under load.
    expect(await screen.findByText(/as far back as one read goes/i)).toBeTruthy();
  });
});

describe('sorting is client-side over what is already loaded', () => {
  it('reorders the rows without issuing a request', async () => {
    renderDiary();
    await screen.findByRole('button', { name: FIRST_ROW });
    await settle();
    const before = reads.length;
    const dates = () =>
      [...document.querySelectorAll('.ct-app__diarydate')].map((node) => node.textContent);
    expect(dates()).toEqual(['12 May 2026', '4 May 2026']);

    fireEvent.click(screen.getByRole('button', { name: SORT_NEWEST }));
    await settle();
    expect(dates()).toEqual(['4 May 2026', '12 May 2026']);
    // ⚠️ THE POINT: order is not part of the query key, so no read went out.
    expect(reads).toHaveLength(before);
  });

  it('announces which order is active rather than only colouring it', async () => {
    renderDiary();
    await screen.findByRole('button', { name: FIRST_ROW });
    // ⚠️ ONE control, so there is no unpressed twin whose accent fill could be the only cue:
    // the state is in the GLYPH for an eye and in the label for a reader who has neither.
    const sort = () => screen.getByRole('button', { name: /first$/ });
    expect(sort()).toHaveAccessibleName(SORT_NEWEST);
    expect(screen.getAllByRole('button', { name: /first$/ })).toHaveLength(1);

    fireEvent.click(sort());
    await settle();
    expect(sort()).toHaveAccessibleName(SORT_OLDEST);
    // The glyph flipped with it — the two sort icons are the only `path` pair on this control.
    fireEvent.click(sort());
    await settle();
    expect(sort()).toHaveAccessibleName(SORT_NEWEST);
  });
});

describe('the whole history is behind its own control and its own cache entry', () => {
  it('is absent when the server says there is nothing outside this plan', async () => {
    scopedBody = { ...SCOPED, has_entries_outside_plan: false };
    renderDiary();
    await screen.findByRole('button', { name: FIRST_ROW });
    await settle();
    expect(screen.queryByRole('button', { name: 'Show old plans' })).toBeNull();
  });

  it('keeps the diary mounted while the history loads, so the scroll cannot be clamped', async () => {
    let arrive = () => {};
    unscopedGate = new Promise<void>((resolve) => {
      arrive = resolve;
    });
    renderDiary();
    await screen.findByRole('button', { name: FIRST_ROW });
    await settle();

    fireEvent.click(screen.getByRole('button', { name: 'Show old plans' }));
    await settle();

    // ⚠️ STILL in flight, which is the point: without `keepPreviousData` the gate meets the empty
    // new key with its loading page, and that collapse is what clamps the reader to the top.
    expect(screen.queryByText('Loading your diary…')).toBeNull();
    expect(screen.getByRole('button', { name: FIRST_ROW })).toBeTruthy();

    arrive();
    await screen.findByRole('heading', { name: 'Winter base', level: 2 });
    expect(screen.getByRole('button', { name: FIRST_ROW })).toBeTruthy();
  });

  it('opens every plan grouped, newest plan first, and going back costs no read', async () => {
    renderDiary();
    await screen.findByRole('button', { name: FIRST_ROW });
    await settle();
    fireEvent.click(screen.getByRole('button', { name: 'Show old plans' }));
    // ⚠️ Same race as above, and this one lost it half the time: wait for the DOM, not a tick.
    await screen.findByRole('heading', { name: 'Winter base', level: 2 });

    const groups = [...document.querySelectorAll('.ct-app__diarygroup h2')].map(
      (node) => node.textContent,
    );
    expect(groups).toEqual(['Road to 6B', 'Winter base', 'Outside any plan']);
    // The unscoped read is a SECOND key, so the scoped one is still cached.
    expect(reads.map((url) => url.searchParams.get('plan_id'))).toEqual([
      String(ACTIVE_PLAN_ID),
      null,
    ]);

    const after = reads.length;
    fireEvent.click(screen.getByRole('button', { name: 'Only current plan' }));
    await settle();
    expect(screen.getByRole('button', { name: 'Show old plans' })).toBeTruthy();
    expect(reads).toHaveLength(after);
  });
});

/** The legend's stroke words, which are the swatches' accessible names — the swatch is a labelled
 *  image rather than decoration, because the stroke is the only identity a line has. */
const swatchNames = () =>
  [...document.querySelectorAll('.ct-app__chartlegend .ct-app__chartswatch')].map((node) =>
    node.getAttribute('aria-label'),
  );

describe('ONE chart, and nothing scored yet is a sentence rather than an empty frame', () => {
  it('draws a single plot and names all three series by their line style', async () => {
    renderDiary();
    await screen.findByRole('button', { name: FIRST_ROW });
    await settle();

    expect(document.querySelectorAll('.ct-app__chartplot')).toHaveLength(1);
    const legend = document.querySelector('.ct-app__chartlegend')?.textContent ?? '';
    expect(legend).toContain('Energy');
    expect(legend).toContain('Sleep');
    expect(legend).toContain('Skin');
    // ⚠️ Identity is the STYLE, and the word is still there for a reader who cannot see the
    // stroke — as the SWATCH's accessible name now, since the eye can already see the line.
    expect(legend).not.toMatch(/solid|dashed|dotted/);
    expect(swatchNames()).toEqual(['solid line', 'dashed line', 'dotted line']);
  });

  it('is LINES only — not one marker shape is left on the plot', async () => {
    renderDiary();
    await screen.findByRole('button', { name: FIRST_ROW });
    await settle();
    const plot = document.querySelector('.ct-app__chartplot');

    // Kilian: "i dont like the triangles or squares, just keep the lines."
    expect(plot?.querySelectorAll('circle, rect, polygon, polyline')).toHaveLength(0);
    expect(plot?.querySelectorAll('path')).toHaveLength(3);
  });

  it('rules the axis in the plan’s weeks and writes only some of them down', async () => {
    renderDiary();
    await screen.findByRole('button', { name: FIRST_ROW });
    await settle();
    const ticks = document.querySelectorAll('.ct-app__chartweek');
    const labels = [...document.querySelectorAll('.ct-app__chartplot text')]
      .map((node) => node.textContent ?? '')
      .filter((text) => text.startsWith('wk '));

    // Eight weeks on the wire, eight ticks — and the words are the app's own, not raw dates.
    expect(ticks).toHaveLength(8);
    expect(labels[0]).toBe('wk 1');
    // ⚠️ THE POINT: "you dont need to write down every week in the y axis."
    expect(labels.length).toBeLessThan(ticks.length);
  });

  it('says why and draws no plot when no entry carries a 1-5 reading', async () => {
    scopedBody = {
      ...SCOPED,
      entries: SCOPED.entries.map((one) => ({
        ...one,
        feel: null,
        sleep_quality: null,
        skin: null,
      })),
    };
    renderDiary();
    await screen.findByRole('button', { name: FIRST_ROW });
    await settle();

    expect(document.body.textContent).toMatch(/Nothing scored yet/);
    expect(document.querySelectorAll('.ct-app__chartplot')).toHaveLength(0);
  });
});

describe('the weigh-in is a COLUMN of the readings table, and the only weight anywhere', () => {
  /** ⚠️ The defect this guards is SILENCE: the column hangs off a profile read left outside the
   *  route's gate, and Kilian asked for every weigh-in rather than a summary of them. */
  it('lists EVERY weigh-in the payload holds, its day and its kilograms', async () => {
    scopedBody = {
      ...SCOPED,
      entries: [
        entry({ body_weight_kg: '71.4' }),
        entry({ id: 2, client_uuid: UUID_TWO, entry_date: '2026-05-08', body_weight_kg: '70.8' }),
        // ⚠️ THE TRAP: weighed and scored NOTHING. The rows were the scored entries alone, so
        // this is the weigh-in that moving the list into this table would have dropped.
        entry({
          id: 3,
          client_uuid: UUID_ORPHAN,
          entry_date: '2026-05-04',
          feel: null,
          sleep_quality: null,
          skin: null,
          body_weight_kg: '70.2',
        }),
      ],
    };
    renderDiary();
    fireEvent.click(await screen.findByText(/These readings, as numbers/));
    // ⚠️ The column waits on the PROFILE read, a second request one macrotask can miss.
    await screen.findByRole('columnheader', { name: 'Weight' });

    // Oldest first, one row per weigh-in the PAYLOAD holds — counted off the payload rather
    // than written as a literal, so a cap or a de-duplication could not pass this.
    const carried = scopedBody.entries.filter((one) => one.body_weight_kg !== null);
    const weighed = [...screen.getByRole('table').querySelectorAll('tbody tr')].map((row) => {
      const cells = [...row.querySelectorAll('td')];
      return [cells[0]?.textContent, cells.at(-1)?.textContent];
    });

    expect(weighed).toHaveLength(carried.length);
    expect(weighed).toEqual([
      ['04/05/26', '70.2kg'],
      ['08/05/26', '70.8kg'],
      ['12/05/26', '71.4kg'],
    ]);
  });

  it('is the only weight surface — the Body weight section is DELETED, not moved', async () => {
    renderDiary();
    await screen.findByRole('button', { name: FIRST_ROW });
    await settle();

    // Kilian: "the body weight section, just delete it all, leave the data inside the 'these
    // readings, as numbers'." No heading, no average, no last weigh-in, no direction word.
    expect(document.body.textContent).not.toMatch(/body weight|seven-day average|last weigh-in/i);
    expect(document.body.textContent).not.toMatch(/trending|holding steady/i);
    expect(document.body.textContent).not.toMatch(/71\.6|recorded, never scored/i);
  });
});

describe('the whole history is ONE chart per plan, each ruled in its own weeks', () => {
  async function openHistory() {
    renderDiary();
    await screen.findByRole('button', { name: FIRST_ROW });
    fireEvent.click(screen.getByRole('button', { name: 'Show old plans' }));
    // ⚠️ `findBy*` POLLS: the whole-history read is a SECOND request and `settle()` is one tick.
    await screen.findByRole('heading', { name: 'Winter base', level: 2 });
    return [...document.querySelectorAll('.ct-app__diarygroup')];
  }

  it('draws a plot in every group and rules each one in that plan’s stored weeks', async () => {
    const groups = await openHistory();

    expect(groups.map((one) => one.querySelectorAll('.ct-app__chartplot').length)).toEqual([
      1, 1, 1,
    ]);
    // ⚠️ THE POINT: eight stored weeks for the plan she is on, four for the old one — and the
    // unattributed group has none on the wire, so no ruler is invented for it.
    expect(groups.map((one) => one.querySelectorAll('.ct-app__chartweek').length)).toEqual([
      8, 4, 0,
    ]);
  });

  it('leaves no chart drawn ACROSS the plans', async () => {
    await openHistory();

    // Kilian: "when showing old plans 1 graph for each, not all in one like now."
    const loose = [...document.querySelectorAll('.ct-app__chartplot')].filter(
      (plot) => plot.closest('.ct-app__diarygroup') === null,
    );
    expect(loose).toEqual([]);
  });

  it('orders every section the same way: its chart, its numbers, then its entries', async () => {
    const groups = await openHistory();
    const first = groups[0];
    const marks = [
      ...(first?.querySelectorAll('.ct-app__chartplot, .ct-app__disclosure, .ct-app__diarylist') ??
        []),
    ];

    expect(marks.map((node) => node.getAttribute('class'))).toEqual([
      'ct-app__chartplot',
      'ct-app__disclosure',
      'ct-app__diarylist',
    ]);
    // ⚠️ The heading chain, no skip and no level spent on a wrapper: `h1` Diary, `h2` the plan,
    // `h3` its metrics. Every section is a PEER of the current plan's, not a child of it.
    const levels = [...(first?.querySelectorAll('h2, h3') ?? [])].map(
      (node) => `${node.tagName} ${node.textContent ?? ''}`,
    );
    expect(levels).toEqual(['H2 Road to 6B', 'H3 Health metrics']);
  });

  it('gives each section its OWN entry order, and the plan order its own control', async () => {
    const groups = await openHistory();
    const names = () =>
      [...document.querySelectorAll('.ct-app__diarygroup h2')].map((node) => node.textContent);
    const datesIn = (section: Element | undefined) =>
      [...(section?.querySelectorAll('.ct-app__diarydate') ?? [])].map((node) => node.textContent);
    const before = reads.length;

    expect(names()).toEqual(['Road to 6B', 'Winter base', 'Outside any plan']);
    expect(datesIn(groups[0])).toEqual(['12 May 2026', '4 May 2026']);

    // The CURRENT section's own control: its list flips and no other section moves.
    fireEvent.click(within(groups[0] as HTMLElement).getByRole('button', { name: SORT_NEWEST }));
    await settle();
    expect(datesIn(groups[0])).toEqual(['4 May 2026', '12 May 2026']);
    expect(names()).toEqual(['Road to 6B', 'Winter base', 'Outside any plan']);

    // ⚠️ A DIFFERENT control with a different job (Kilian): which OLD section leads, never a
    // second entry sort — and the plan she is on is not one of the sections it orders.
    fireEvent.click(screen.getByRole('button', { name: PLAN_SORT_NEWEST }));
    await settle();
    expect(names()).toEqual(['Road to 6B', 'Outside any plan', 'Winter base']);
    // Client-side, every press of it: not one of these is part of a query key.
    expect(reads).toHaveLength(before);
  });

  it('says plainly why the unclaimed group has no weeks, and ends at its last reading', async () => {
    const groups = await openHistory();
    const last = groups.at(-1);
    const ends = [...(last?.querySelectorAll('.ct-app__chartspan span') ?? [])].map(
      (node) => node.textContent,
    );

    // ⚠️ The FACT, not the sentence that used to carry it: an unclaimed group says so in its
    // own heading, and that is what makes the paragraph under the chart redundant.
    expect(last?.querySelector('h2')?.textContent).toBe('Outside any plan');
    expect(ends).toEqual(['1 Jan 2025', '1 Jan 2025']);
  });
});

describe('the legend’s checkbox is what takes a line off the plot', () => {
  const paths = () => document.querySelector('.ct-app__chartplot')?.querySelectorAll('path') ?? [];

  it('draws only the ticked lines, and still names all three by their style', async () => {
    renderDiary();
    await screen.findByRole('button', { name: FIRST_ROW });
    await settle();
    expect(paths()).toHaveLength(3);

    fireEvent.click(screen.getByRole('checkbox', { name: /Sleep/ }));
    // ⚠️ THE POINT: unticked is ABSENT from the plot, not merely faded — and the legend still
    // says which stroke belongs to it, because that is the only identity the lines have.
    expect(paths()).toHaveLength(2);
    const legend = document.querySelector('.ct-app__chartlegend')?.textContent ?? '';
    expect(legend).toContain('Sleep');
    expect(swatchNames()).toContain('dashed line');
  });

  it('shows ONE series on its own, which is what the checkboxes are for', async () => {
    renderDiary();
    await screen.findByRole('button', { name: FIRST_ROW });
    await settle();
    fireEvent.click(screen.getByRole('checkbox', { name: /Energy/ }));
    fireEvent.click(screen.getByRole('checkbox', { name: /Sleep/ }));

    // Kilian: "so the user can only see skin in the graph for example."
    expect(paths()).toHaveLength(1);
    const survivor = screen.getByRole('checkbox', { name: /Skin/ });
    // ⚠️ An empty frame is unreachable: the last ticked box is disabled rather than obeyed.
    expect(survivor).toBeDisabled();
    fireEvent.click(survivor);
    expect(paths()).toHaveLength(1);
  });

  it('keeps every value in the table, whatever the plot is showing', async () => {
    renderDiary();
    await screen.findByRole('button', { name: FIRST_ROW });
    await settle();
    fireEvent.click(screen.getByRole('checkbox', { name: /Sleep/ }));
    fireEvent.click(screen.getByText(/These readings, as numbers/));
    // ⚠️ The weigh-in column waits on the PROFILE read, which one macrotask can miss.
    await screen.findByRole('columnheader', { name: 'Weight' });

    // ⚠️ The CELLS, not the headers: a header row is spelled from `SERIES_NAMES` and stays put
    // even when every value under it has been dropped. Hiding a LINE must not hide a READING.
    const table = screen.getByRole('table');
    const headers = [...table.querySelectorAll('th')].map((cell) => cell.textContent);
    const cells = [...table.querySelectorAll('tbody tr')].map((row) =>
      [...row.querySelectorAll('td')].map((cell) => cell.textContent),
    );
    expect(headers).toEqual(['Day', 'Energy', 'Sleep', 'Skin', 'Weight']);
    expect(cells).toEqual([
      ['04/05/26', '4', '3', '2', '71.4kg'],
      ['12/05/26', '4', '3', '2', '71.4kg'],
    ]);
  });

  it('gives each plan’s legend its own state', async () => {
    renderDiary();
    await screen.findByRole('button', { name: FIRST_ROW });
    fireEvent.click(screen.getByRole('button', { name: 'Show old plans' }));
    await screen.findByRole('heading', { name: 'Winter base', level: 2 });
    const boxes = screen.getAllByRole('checkbox', { name: /Sleep/ });

    expect(boxes).toHaveLength(3);
    fireEvent.click(boxes[0] as HTMLElement);
    // ⚠️ One plan's toggles must not silently change another's.
    expect(boxes[0]).not.toBeChecked();
    expect(boxes[1]).toBeChecked();
    expect(boxes[2]).toBeChecked();
  });
});

describe('show_body_metrics off means NO weight number on this screen', () => {
  it('renders none in a chart, none in a row and none in the entry', async () => {
    profile = { ...PROFILE, show_body_metrics: false };
    scopedBody = { ...SCOPED, trends: { body_weight_kg: null, body_weight_direction: null } };
    renderDiary();
    const row = await screen.findByRole('button', { name: FIRST_ROW });
    await settle();
    // The payload still CARRIES it — that is deliberate, for the edit path.
    expect(SCOPED.entries[0]?.body_weight_kg).toBe('71.4');
    expect(document.body.innerHTML).not.toContain('71.4');
    expect(document.body.textContent).not.toMatch(/body weight|weigh-in|kg/i);
    // The 1-5 chart is untouched by the gate — it was never about the weight.
    expect(document.querySelectorAll('.ct-app__chartplot')).toHaveLength(1);

    fireEvent.click(row);
    await settle();
    const sheet = within(screen.getByRole('dialog'));
    expect(sheet.queryByLabelText(/weight today/i)).toBeNull();
    expect(screen.getByRole('dialog').innerHTML).not.toContain('71.4');
  });

  it('leaves the readings table with no weigh-in column, and no row that is only one', async () => {
    profile = { ...PROFILE, show_body_metrics: false };
    scopedBody = {
      ...SCOPED,
      entries: [
        entry(),
        // Weighed, scored nothing. With no column to put it in it is not a reading, so the row
        // it would owe under the flag must not appear here as a line of empty cells.
        entry({
          id: 3,
          client_uuid: UUID_ORPHAN,
          entry_date: '2026-05-04',
          feel: null,
          sleep_quality: null,
          skin: null,
          body_weight_kg: '70.2',
        }),
      ],
    };
    renderDiary();
    await screen.findByRole('button', { name: FIRST_ROW });
    await settle();
    fireEvent.click(screen.getByText(/These readings, as numbers/));
    await settle();

    const table = screen.getByRole('table');
    expect([...table.querySelectorAll('th')].map((cell) => cell.textContent)).toEqual([
      'Day',
      'Energy',
      'Sleep',
      'Skin',
    ]);
    expect(table.querySelectorAll('tbody tr')).toHaveLength(1);
    expect(document.body.innerHTML).not.toContain('70.2');
    expect(document.body.textContent).not.toMatch(/body weight|weigh-in|kg/i);
  });

  it('renders none in ANY plan’s group once the whole history is open', async () => {
    profile = { ...PROFILE, show_body_metrics: false };
    renderDiary();
    await screen.findByRole('button', { name: FIRST_ROW });
    fireEvent.click(screen.getByRole('button', { name: 'Show old plans' }));
    await screen.findByRole('heading', { name: 'Winter base', level: 2 });

    // ⚠️ The payload still carries every weigh-in AND the trend — the gate is what makes it
    // absent, now in three groups at once rather than in one card.
    expect(document.querySelectorAll('.ct-app__diarygroup')).toHaveLength(3);
    expect(document.body.innerHTML).not.toContain('71.4');
    expect(document.body.textContent).not.toMatch(/body weight|weigh-in|kg/i);
  });
});

describe('the demo mount reads the diary but is offered no edit', () => {
  it('hides the Edit control entirely rather than greying it out', async () => {
    renderDiary('demo');
    const row = await screen.findByRole('button', { name: FIRST_ROW });
    await settle();
    fireEvent.click(row);
    await settle();
    const sheet = within(screen.getByRole('dialog'));
    // Reading works; #65's rule is absence, not a disabled button.
    expect(sheet.getByText('crimps felt sharp')).toBeTruthy();
    expect(sheet.queryByRole('button', { name: 'Edit' })).toBeNull();
    expect(sheet.getByRole('button', { name: 'Close' })).toBeTruthy();
  });

  it('offers it for a real principal', async () => {
    renderDiary();
    const row = await screen.findByRole('button', { name: FIRST_ROW });
    await settle();
    fireEvent.click(row);
    await settle();
    expect(screen.getByRole('button', { name: 'Edit' })).toBeTruthy();
  });
});

describe('⚠️ the edit path, where the two ways to lose data are', () => {
  async function openAndEdit(uuidRow: RegExp) {
    renderDiary();
    const row = await screen.findByRole('button', { name: uuidRow });
    await settle();
    fireEvent.click(row);
    await settle();
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    await settle();
  }

  it('PUTs the entry’s OWN client_uuid, so one day keeps one row', async () => {
    // The SECOND row, so a uuid taken from anywhere but this entry is visible as a mismatch.
    await openAndEdit(/4 May 2026/);
    fireEvent.change(screen.getByLabelText(/how it went/i), { target: { value: 'edited' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save this entry' }));
    await settle();

    expect(puts.map((put) => put.path)).toEqual([`/api/journal/${UUID_TWO}`]);
  });

  it('resends the stored weigh-in when body metrics are OFF', async () => {
    profile = { ...PROFILE, show_body_metrics: false };
    scopedBody = { ...SCOPED, trends: { body_weight_kg: null, body_weight_direction: null } };
    await openAndEdit(FIRST_ROW);
    fireEvent.change(screen.getByLabelText(/how it went/i), {
      target: { value: 'edited blind to the weight' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save this entry' }));
    await settle();

    // ⚠️ THE GUARD. The PUT replaces whole, and nothing on screen showed this number.
    expect(puts).toHaveLength(1);
    expect(puts[0]?.body).toMatchObject({
      body: 'edited blind to the weight',
      body_weight_kg: '71.4',
      logged_session_id: 909,
      entry_date: '2026-05-12',
    });
  });

  it('re-reads the diary after a save, so the list and the charts cannot lie', async () => {
    await openAndEdit(FIRST_ROW);
    const before = reads.length;
    fireEvent.change(screen.getByLabelText(/how it went/i), { target: { value: 'edited' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save this entry' }));
    await settle();
    expect(reads.length).toBeGreaterThan(before);
  });
});

/** ⚠️ Matched against RENDERED markup, never the source. `session/journalBox.test.tsx` asserts the
 *  same absence over the WRITE box — two screens, one list, neither standing in for the other. */

describe('the app never recommends losing weight — including near this chart', () => {
  it.each([
    ['metrics on, a weight trend drawn', true],
    ['metrics off, no weight anywhere', false],
  ])('says nothing about reducing it: %s', async (_name, metrics) => {
    profile = { ...PROFILE, show_body_metrics: metrics };
    renderDiary();
    await screen.findByRole('button', { name: FIRST_ROW });
    await settle();
    const copy = document.body.innerHTML.toLowerCase();
    expect(forbiddenCopyHits(copy), 'the diary screen').toEqual([]);
  });

  it('would CATCH such a sentence — the wordlist is not vacuous', () => {
    const sample = 'Your goal weight is 65 kg — lose 6 kg to be a lighter climber; your BMI drops.';
    expect(forbiddenCopyHits(sample)).toEqual(['lose', 'lighter', 'goal weight', 'bmi']);
  });
});

/** ⚠️ TWO caches carry a plan's name — `/api/journal`'s `plans` lookup, under BOTH its keys, and
 *  `/api/plans/active` — so a rename that misses either makes this screen contradict itself. */

describe('renaming a plan, a finished one included', () => {
  const groupHeadings = () =>
    [...document.querySelectorAll('.ct-app__diarygroup h2')].map((node) => node.textContent);

  async function openHistory(): Promise<void> {
    renderDiary();
    await screen.findByRole('button', { name: FIRST_ROW });
    fireEvent.click(screen.getByRole('button', { name: 'Show old plans' }));
    // ⚠️ The whole-history read is a SECOND request; `findBy*` polls where `settle()` is one tick.
    await screen.findByRole('heading', { name: 'Winter base', level: 2 });
  }

  async function typeAndSave(planName: string, typed: string): Promise<void> {
    fireEvent.click(screen.getByRole('button', { name: `Rename ${planName}` }));
    fireEvent.change(await screen.findByLabelText('Plan name'), { target: { value: typed } });
    fireEvent.click(screen.getByRole('button', { name: 'Save this name' }));
  }

  it('renames a FINISHED plan, and installs the name the server STORED', async () => {
    await openHistory();
    await typeAndSave('Winter base', '  Spring block  ');
    await screen.findByRole('heading', { name: 'Spring block', level: 2 }, { timeout: 5000 });

    // ⚠️ `textContent`, not the accessible name: name computation collapses whitespace, so this
    // is the only assertion that can tell the stored value from the padded one that was typed.
    expect(groupHeadings()).toEqual(['Road to 6B', 'Spring block', 'Outside any plan']);
    expect(renames).toEqual([
      { path: `/api/plans/${String(OLD_PLAN_ID)}/name`, body: { name: '  Spring block  ' } },
    ]);
  });

  it('leaves NEITHER cache stale — the group heading, the rows and the active plan agree', async () => {
    await openHistory();
    await typeAndSave('Road to 6B', 'Spring block');
    await screen.findByRole('heading', { name: 'Spring block', level: 2 }, { timeout: 5000 });
    expect(groupHeadings()).toEqual(['Spring block', 'Winter base', 'Outside any plan']);

    const after = reads.length;
    fireEvent.click(screen.getByRole('button', { name: 'Only current plan' }));
    // The scoped key is still cached, so this view renders without a request either way — the
    // wait is for the switch, never for the thing under test.
    const row = await screen.findByRole('button', { name: FIRST_ROW });
    // ⚠️ THE GUARD, `/api/plans/active`'s half: this heading is that cache entry, and a rename
    // that installed only the journal's lookup would still read 'Road to 6B' here.
    const heading = document.querySelector('.ct-app__planhead > h2');
    expect(heading?.textContent).toEqual('Spring block');
    // And the SCOPED journal key's own `plans` lookup, which is a second entry under that
    // prefix: the rows read their plan name from whichever key the screen is showing.
    expect(row.textContent).toContain('Spring block');
    expect(row.textContent).not.toContain('Road to 6B');
    // Installed, never re-read: the reply carried the stored name, so nothing had to be fetched.
    expect(reads).toHaveLength(after);
  });

  it('is ABSENT for a demo principal rather than greyed out', async () => {
    renderDiary('demo');
    await screen.findByRole('button', { name: FIRST_ROW });
    await settle();
    expect(screen.queryByRole('button', { name: /^Rename / })).toBeNull();
    // Reading the plan's name still works — #65's rule is absence, not a disabled control.
    expect(screen.getByRole('heading', { name: 'Road to 6B', level: 2 })).toBeTruthy();
  });

  it('offers it for a real principal, on the plan she is on', async () => {
    renderDiary();
    await screen.findByRole('button', { name: FIRST_ROW });
    await settle();
    expect(screen.getByRole('button', { name: 'Rename Road to 6B' })).toBeTruthy();
  });

  it.each([
    ['nothing but whitespace', '   ', /a plan needs a name/i],
    ['more than the column holds', 'x'.repeat(81), /81 characters/],
  ])('refuses %s before any request goes out', async (_name, typed, said) => {
    renderDiary();
    await screen.findByRole('button', { name: FIRST_ROW });
    await settle();
    fireEvent.click(screen.getByRole('button', { name: 'Rename Road to 6B' }));
    fireEvent.change(await screen.findByLabelText('Plan name'), { target: { value: typed } });

    expect(screen.getByText(said)).toBeTruthy();
    // A control that could do nothing is not on screen (Kilian), so there is no press to refuse.
    expect(screen.queryByRole('button', { name: 'Save this name' })).toBeNull();
    expect(renames).toEqual([]);
  });

  it.each([
    [404, /not there any more/i],
    [422, /did not save/i],
  ])('reports a %i to the climber rather than swallowing it', async (status, said) => {
    renameStatus = status;
    renderDiary();
    await screen.findByRole('button', { name: FIRST_ROW });
    await settle();
    await typeAndSave('Road to 6B', 'Spring block');

    const alert = await screen.findByRole('alert', undefined, { timeout: 5000 });
    expect(alert.textContent).toMatch(said);
    // What was typed is still in the field, and the old name is still what the screen says.
    expect(screen.getByLabelText('Plan name')).toHaveProperty('value', 'Spring block');
    expect(screen.getByRole('heading', { name: 'Road to 6B', level: 2 })).toBeTruthy();
  });

  it('opens with focus in the field and leaves none stranded when it closes', async () => {
    renderDiary();
    await screen.findByRole('button', { name: FIRST_ROW });
    await settle();
    fireEvent.click(screen.getByRole('button', { name: 'Rename Road to 6B' }));
    expect(document.activeElement).toBe(await screen.findByLabelText('Plan name'));

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    // ⚠️ React drops focus on `<body>` after removing the control just pressed, so it is
    // rescued back to the opener rather than left there — `SessionJournal`'s rule.
    expect(document.activeElement).toBe(
      await screen.findByRole('button', { name: 'Rename Road to 6B' }),
    );
  });
});
