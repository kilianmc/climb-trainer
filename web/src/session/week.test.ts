import { describe, expect, it } from 'vitest';

import type { LoggedSetInput, PlanSession, SessionCompletion } from '../api/types';
import type { CompletionBadge } from '../plan/completion';

import { makeBlock, makeLibrary, makeSession, makeSet } from './fixtures';
import { compileProtocol } from './protocol';
import type { RunRecord } from './runStore';
import { createRun } from './runStore';
import {
  offerView,
  pendingSessions,
  sessionClosed,
  sessionReport,
  sessionsAround,
  weekDays,
  weekView,
} from './week';

/* The week strip's model (#82). Four things fail silently here: the Monday–Sunday window at a
   month or timezone edge, which session is owed, which day is today, and when an offer closes. */

const MONDAY = '2026-08-31';
const WEEK = [
  '2026-08-31',
  '2026-09-01',
  '2026-09-02',
  '2026-09-03',
  '2026-09-04',
  '2026-09-05',
  '2026-09-06',
];

/** `weekday` is Monday-first, as `planned_session.weekday` is; the date is what everything reads. */
function session(id: number, scheduledOn: string, aspects: readonly string[]): PlanSession {
  return {
    activity_kind: 'climbing',
    // Given OUT of `order_index` order, so a pass cannot come from the input order.
    blocks: aspects
      .map((key, index) => ({
        ...makeBlock({ order_index: index, sets: [makeSet()] }),
        aspect_key: key,
      }))
      .reverse(),
    estimated_minutes: 60,
    id,
    scheduled_on: scheduledOn,
    shortfalls: [],
    status: 'planned',
    title: `Session ${String(id)}`,
    weekday: WEEK.indexOf(scheduledOn),
  };
}

/** Three blocks, `percent` of them done. ⚠️ `blocks_done` is derived from the percentage rather
 *  than passed: it is what says whether anything was LOGGED, so the two may never disagree. */
function row(
  plannedSessionId: number,
  percent: number | null,
  state: SessionCompletion['state'] = 'skipped',
): SessionCompletion {
  const blocksDone = percent === null ? 0 : Math.round((percent * 3) / 100);
  return {
    block_count: 3,
    blocks_done: blocksDone,
    done_block_ids: BLOCK_IDS.slice(0, blocksDone),
    percent,
    planned_session_id: plannedSessionId,
    scheduled_on: MONDAY,
    state,
    status: 'planned',
  };
}

/** `session_block.id`s, which is what `done_block_ids` joins on — not the blocks' order. */
const BLOCK_IDS = [71, 72, 73];

const completion = (...rows: SessionCompletion[]) =>
  new Map(rows.map((entry) => [entry.planned_session_id, entry] as const));

/** The gate the screen builds, with NO run record: the server row is the only reading here.
 *  `offerView`'s own suite below covers the record beating a stale badge. */
const gate = (rows: ReadonlyMap<number, SessionCompletion>, todayIso = '2026-09-02') =>
  sessionClosed(rows, todayIso, null, 0);

describe('weekDays', () => {
  it('starts on Monday and ends on Sunday, from a Wednesday inside the week', () => {
    expect(weekDays(new Date(2026, 8, 2, 9, 0))).toEqual(WEEK);
  });

  it('returns the SAME week from its own Monday and from its own Sunday', () => {
    expect(weekDays(new Date(2026, 7, 31, 0, 1))).toEqual(WEEK);
    expect(weekDays(new Date(2026, 8, 6, 23, 59))).toEqual(WEEK);
  });

  it('crosses a month boundary, and a Sunday is not read as the start of the next week', () => {
    expect(weekDays(new Date(2026, 8, 6, 12, 0))[0]).toBe('2026-08-31');
    expect(weekDays(new Date(2026, 1, 26, 12, 0))).toEqual([
      '2026-02-23',
      '2026-02-24',
      '2026-02-25',
      '2026-02-26',
      '2026-02-27',
      '2026-02-28',
      '2026-03-01',
    ]);
  });

  it('crosses a YEAR boundary in both directions', () => {
    expect(weekDays(new Date(2027, 0, 1, 12, 0))).toEqual([
      '2026-12-28',
      '2026-12-29',
      '2026-12-30',
      '2026-12-31',
      '2027-01-01',
      '2027-01-02',
      '2027-01-03',
    ]);
  });

  it('reads the LOCAL day late in the evening, where toISOString already says tomorrow', () => {
    // 23:30 on Sunday 6 September: UTC has rolled into Monday, and a UTC-derived week would
    // return the NEXT one — the whole strip would move a week ahead for half the world.
    expect(weekDays(new Date(2026, 8, 6, 23, 30))).toEqual(WEEK);
  });
});

describe('pendingSessions', () => {
  const monday = session(1, '2026-08-31', ['power']);
  const tuesday = session(2, '2026-09-01', ['endurance']);
  const wednesday = session(3, '2026-09-02', ['technique']);
  const nextWeek = session(4, '2026-09-07', ['power']);
  const lastWeek = session(5, '2026-08-28', ['power']);

  it('lists every session of this week before today under 100%, OLDEST FIRST', () => {
    const rows = completion(row(1, 66, 'completed'), row(2, 0), row(5, 0));
    const owed = pendingSessions(
      [lastWeek, monday, tuesday, wednesday, nextWeek],
      rows,
      '2026-09-02',
      WEEK,
      gate(rows),
    );

    expect(owed.map((entry) => entry.session.id)).toEqual([1, 2]);
    expect(owed.map((entry) => entry.badge.label)).toEqual(['66% done', 'Skipped']);
    expect(owed.map((entry) => entry.badge.band)).toEqual(['partial', 'low']);
  });

  it('counts 0% and does NOT count a session with no blocks at all', () => {
    const rows = completion(row(1, null), row(2, 0));
    const owed = pendingSessions([monday, tuesday], rows, '2026-09-02', WEEK, gate(rows));

    expect(owed.map((entry) => entry.session.id)).toEqual([2]);
  });

  it('does not count a finished session, today, or a day still ahead', () => {
    const rows = completion(
      row(1, 100, 'completed'),
      row(2, 100, 'completed'),
      row(3, 0),
      row(4, 0),
    );
    const owed = pendingSessions(
      [monday, tuesday, wednesday, nextWeek],
      rows,
      '2026-09-02',
      WEEK,
      gate(rows),
    );

    expect(owed).toEqual([]);
  });

  it('⚠️ does not count a day the SERVER still calls pending, whatever our own clock says', () => {
    const rows = completion(row(1, 0, 'pending'));
    const owed = pendingSessions([monday], rows, '2026-09-02', WEEK, gate(rows));

    expect(owed).toEqual([]);
  });

  it('counts a session from another microcycle or phase — the week is the only window', () => {
    // The tree is flattened before this, so a phase boundary mid-week is not expressible here;
    // what matters is that nothing but the date decides, which a plan-wide id range shows.
    const earlier = session(9001, '2026-08-31', ['mobility']);
    const rows = completion(row(9001, 33, 'completed'));
    const owed = pendingSessions([earlier], rows, '2026-09-02', WEEK, gate(rows));

    expect(owed.map((entry) => entry.session.id)).toEqual([9001]);
  });

  it('has nothing to say about a session with no id — a preview has no completion row', () => {
    const preview = { ...session(1, '2026-08-31', ['power']), id: null };

    const rows = completion(row(1, 0));

    expect(pendingSessions([preview], rows, '2026-09-02', WEEK, gate(rows))).toEqual([]);
  });
});

describe('sessionReport', () => {
  const monday = session(1, '2026-08-31', ['power']);
  const wednesday = session(3, '2026-09-02', ['technique']);
  const saturday = session(6, '2026-09-05', ['power']);
  const TODAY = '2026-09-02';

  it('marks a settled day’s unreached blocks MISSED, and reports its 0% as a result', () => {
    const report = sessionReport(monday, completion(row(1, 0, 'skipped')), TODAY);

    expect(report.badge).toEqual({ label: 'Skipped', band: 'low' });
    expect(report.marks).toEqual({ done: new Set(), marksMisses: true });
  });

  it('⚠️ marks NOTHING missed today or later — an unreached block is not a missed one', () => {
    for (const session_ of [wednesday, saturday]) {
      const report = sessionReport(
        session_,
        completion(row(session_.id ?? 0, 33, 'pending')),
        TODAY,
      );

      expect(report.badge).toEqual({ label: '33% done', band: 'low' });
      expect(report.marks).toEqual({ done: new Set([BLOCK_IDS[0]]), marksMisses: false });
    }
  });

  it('⚠️ says nothing at all about an UNTOUCHED day still in reach, however it is stated', () => {
    // No badge and no marks means no word, no tint and no edge: 0% on a day nobody has
    // reached yet would read as a failure one day early, whether or not Finish was pressed.
    for (const state of ['pending', 'completed'] as const) {
      expect(sessionReport(wednesday, completion(row(3, 0, state)), TODAY)).toEqual({
        badge: null,
        marks: null,
      });
    }
  });

  it('has nothing to report for a rest day or for a preview with no id', () => {
    const nothing = { badge: null, marks: null };

    expect(sessionReport(null, completion(row(3, 100, 'completed')), TODAY)).toEqual(nothing);
    expect(sessionReport({ ...wednesday, id: null }, completion(row(3, 100)), TODAY)).toEqual(
      nothing,
    );
  });
});

describe('weekView', () => {
  const monday = session(1, '2026-08-31', ['finger_strength', 'power', 'endurance']);
  const wednesday = session(3, '2026-09-02', ['technique']);
  const view = weekView(
    [monday, wednesday],
    completion(row(1, 66, 'completed'), row(3, 0, 'pending')),
    '2026-09-02',
    WEEK,
  );

  it('is seven Monday-first days, each with its own date', () => {
    expect(view.days.map((day) => day.label)).toEqual([
      'Mon',
      'Tue',
      'Wed',
      'Thu',
      'Fri',
      'Sat',
      'Sun',
    ]);
    expect(view.days.map((day) => day.dayOfMonth)).toEqual(['31', '1', '2', '3', '4', '5', '6']);
  });

  it('names the day’s aspects in order_index order, with their codes', () => {
    expect(view.days[0]?.aspects.map((entry) => entry.code)).toEqual(['FS', 'P', 'E']);
    expect(view.days[0]?.aspects.map((entry) => entry.name)).toEqual([
      'Finger strength',
      'Power',
      'Endurance',
    ]);
  });

  it('leaves a rest day with no aspects at all, which is what the cell says Rest for', () => {
    expect(view.days[1]?.aspects).toEqual([]);
    expect(view.days[1]?.mark).toBeNull();
  });

  it('marks exactly one day as today', () => {
    expect(view.days.filter((day) => day.isToday).map((day) => day.iso)).toEqual(['2026-09-02']);
  });

  it('carries the completion band and BOTH its words on a past day, and none on today', () => {
    expect(view.days[0]?.mark).toEqual({ label: '66% done', short: '66%', band: 'partial' });
    expect(view.days[2]?.mark).toBeNull();
  });

  /** ⚠️ THE #82 DEFECT, in the channel Kilian read it in: "what was wrong was the week showing
   *  completed instead of what it really was" — a session merely FINISHED, its parts unlogged. */
  it('⚠️ says NOTHING about a day still in reach that was FINISHED with nothing logged', () => {
    const finishedEmpty = weekView(
      [session(3, '2026-09-02', ['technique']), session(6, '2026-09-05', ['power'])],
      completion(row(3, 0, 'completed'), row(6, 0, 'completed')),
      '2026-09-02',
      WEEK,
    );

    expect(finishedEmpty.days[2]?.mark).toBeNull();
    expect(finishedEmpty.days[5]?.mark).toBeNull();
  });

  it('reports what a day still in reach has LOGGED, which is what survives a reload', () => {
    const logged = weekView(
      [session(3, '2026-09-02', ['technique']), session(6, '2026-09-05', ['power'])],
      completion(row(3, 100, 'completed'), row(6, 66, 'pending')),
      '2026-09-02',
      WEEK,
    );

    expect(logged.days[2]?.mark).toEqual({ label: 'Completed', short: '100%', band: 'full' });
    expect(logged.days[5]?.mark).toEqual({ label: '66% done', short: '66%', band: 'partial' });
  });

  it('⚠️ still calls a PAST day at 0% skipped — a day that is over is a real result', () => {
    const over = weekView(
      [session(1, '2026-08-31', ['power'])],
      completion(row(1, 0, 'completed')),
      '2026-09-02',
      WEEK,
    );

    expect(over.days[0]?.mark).toEqual({ label: 'Skipped', short: '0%', band: 'low' });
  });

  it('legends only the aspects this week uses, in the canonical order', () => {
    expect(view.legend.map((entry) => entry.key)).toEqual([
      'finger_strength',
      'power',
      'endurance',
      'technique',
    ]);
  });
});

describe('sessionsAround', () => {
  const sessions = [
    session(1, '2026-08-31', ['power']),
    session(3, '2026-09-02', ['technique']),
    session(4, '2026-09-04', ['endurance']),
    session(6, '2026-09-05', ['power']),
  ];
  /** Nothing done anywhere: the shape every case but the last two share. */
  const nothing = gate(completion());

  it('finds today’s session and the NEXT one after it', () => {
    expect(sessionsAround(sessions, '2026-09-02', nothing)).toEqual({
      today: sessions[1],
      next: sessions[2],
    });
  });

  it('has no session today on a rest day, and still offers the next one', () => {
    expect(sessionsAround(sessions, '2026-09-03', nothing)).toEqual({
      today: null,
      next: sessions[2],
    });
  });

  it('runs out of both once the plan is behind us', () => {
    expect(sessionsAround(sessions, '2026-09-09', nothing)).toEqual({ today: null, next: null });
  });

  /** ⚠️ Kilian, #82: a session done in full "does not appear in past / current / next session".
   *  Pulled forward and finished, it is over — so the one after it is what is offered. */
  it('SKIPS OVER a next session already completed, and offers the one after it', () => {
    const rows = completion({ ...row(4, 100, 'completed'), scheduled_on: '2026-09-04' });

    expect(sessionsAround(sessions, '2026-09-02', gate(rows))).toEqual({
      today: sessions[1],
      next: sessions[3],
    });
  });

  it('still returns TODAY’S session when it is completed — the screen owes a word for it', () => {
    const rows = completion({ ...row(3, 100, 'completed'), scheduled_on: '2026-09-02' });

    expect(sessionsAround(sessions, '2026-09-02', gate(rows))).toEqual({
      today: sessions[1],
      next: sessions[2],
    });
  });
});

describe('offerView', () => {
  const START = Date.UTC(2026, 8, 2, 9, 0);
  const monday = session(1, '2026-08-31', ['power']);
  const wednesday = session(3, '2026-09-02', ['technique']);
  /** What the server said BEFORE the run below: `useSessionCompletion` holds it ten minutes. */
  const stale: CompletionBadge = { label: '66% done', band: 'partial' };

  function loggedSet(prescribedSetId: number): LoggedSetInput {
    return {
      client_uuid: `00000000-0000-4000-8000-000000000${String(prescribedSetId)}`,
      set_index: 1,
      exercise_id: 11,
      prescribed_set_id: prescribedSetId,
      actual_reps: null,
      actual_work_seconds: null,
      rpe: null,
      completed_at: new Date(START).toISOString(),
    };
  }

  /** A FINISHED run of three one-set blocks against `plannedSessionId`, `done` of them logged
   *  and `preDone` of them already on the SERVER at Start — so one block is a clean third. */
  function finishedRun(
    plannedSessionId: number | null,
    done: readonly number[],
    preDone: readonly number[] = [],
  ): RunRecord {
    const blocks = [501, 601, 701].map((id, index) =>
      makeBlock({
        order_index: index,
        exercise_key: `block_${String(index)}`,
        exercise_id: 11 + index,
        sets: [makeSet({ id, target_work_seconds: 10 })],
      }),
    );
    const record = createRun({
      occurredOn: '2026-09-02',
      discipline: 'sport',
      plannedSessionId,
      startedAtEpochMs: START,
      timeline: compileProtocol(makeSession(blocks, '2026-08-31'), makeLibrary()),
      preDoneBlockIndexes: preDone,
    });
    return { ...record, finishedAtEpochMs: START + 60_000, logged: done.map(loggedSet) };
  }

  it('leaves an offer open while no run of ITS OWN has finished, badge untouched', () => {
    // Matched on the session, not on the day: finishing Tuesday's closes nothing of Monday's,
    // and the RECORD it hands the card is its own or none — Tuesday's would describe Monday.
    expect(offerView(monday, finishedRun(2, [501]), stale, 0)).toEqual({
      state: 'open',
      badge: stale,
      record: null,
    });
    expect(offerView(monday, null, stale, 0)).toEqual({
      state: 'open',
      badge: stale,
      record: null,
    });
    expect(offerView(wednesday, null, null, 0)).toEqual({
      state: 'open',
      badge: null,
      record: null,
    });
  });

  it('⚠️ STAYS STARTABLE below 100%, and words the figure the run actually reached', () => {
    // Kilian: "a pending session lets you start again until it is 100%." One block of three.
    const run = finishedRun(1, [501]);
    expect(offerView(monday, run, stale, 0)).toEqual({
      state: 'unfinished',
      badge: { label: '33% done', band: 'low' },
      record: run,
    });
  });

  /** ⚠️ #82's last defect. `offerView` prefers the RECORD to the badge, so a record blind to
   *  what the server already held would keep a finished session on screen as unfinished. */
  it('counts the parts the SERVER already held, so a restart cannot understate its session', () => {
    const seeded = finishedRun(1, [], [0, 1]);
    expect(offerView(monday, seeded, stale, 0)).toEqual({
      state: 'unfinished',
      badge: { label: '67% done', band: 'partial' },
      record: seeded,
    });

    // The third part logged in THIS attempt closes it, with no set faked for the other two.
    const closed = finishedRun(1, [701], [0, 1]);
    expect(closed.logged).toHaveLength(1);
    expect(offerView(monday, closed, null, 0)).toEqual({
      state: 'done',
      badge: { label: 'Completed', band: 'full' },
      record: closed,
    });
  });

  it('closes only at 100% — the same test wherever the session sits on the screen', () => {
    for (const offered of [monday, wednesday]) {
      const run = finishedRun(offered.id ?? null, [501, 601, 701]);
      expect(offerView(offered, run, null, 0)).toEqual({
        state: 'done',
        badge: { label: 'Completed', band: 'full' },
        record: run,
      });
    }
  });

  it('⚠️ closes TODAY’S session on the SERVER badge alone, with no run record at all', () => {
    // The reload case: nothing local, and the session is done. Pressing Finish is not what
    // closed it — 100% of its blocks is — so the card offers no restart and no record.
    const full: CompletionBadge = { label: 'Completed', band: 'full' };
    expect(offerView(wednesday, null, full, 0)).toEqual({
      state: 'done',
      badge: full,
      record: null,
    });
  });

  it('⚠️ reads the RUN RECORD over a stale server badge, in BOTH directions', () => {
    // The badge is refetched after a save, so until it lands it reports the pre-run figure —
    // and a card that contradicts the summary the climber just closed is the whole defect.
    const full: CompletionBadge = { label: 'Completed', band: 'full' };
    const none: CompletionBadge = { label: 'Skipped', band: 'low' };
    expect(offerView(monday, finishedRun(1, [501]), full, 0).state).toBe('unfinished');
    expect(offerView(monday, finishedRun(1, [501, 601, 701]), none, 0).state).toBe('done');
  });

  it('⚠️ routes an offer holding UNSENT SETS to the unsaved-run path, not to a restart', () => {
    // Starting mints a run under a new key and REPLACES the record, so a Start offered here
    // would silently drop sets that never reached the server.
    expect(offerView(monday, finishedRun(1, [501]), stale, 1).state).toBe('unsaved');
    // …and `done` still wins over it: there is nothing left to start either way.
    expect(offerView(monday, finishedRun(1, [501, 601, 701]), stale, 1).state).toBe('done');
  });
});
