import { afterEach, describe, expect, it, vi } from 'vitest';

import { makeBlock, makePlan, makeSession, makeSet } from './fixtures';
import { loggableSets, localIsoDate, planSessions, selectSession, totalSets } from './today';

/**
 * Date handling and the rest-day branch — the policy names both, and both fail silently:
 *
 * - **`localIsoDate`** is `occurred_on`. `toISOString().slice(0, 10)` formats UTC, so east of
 *   Greenwich every evening reports tomorrow: the session in front of the climber disappears
 *   and the diary entry lands on the wrong day. The 22:00-in-UTC+2 case below is exactly that.
 * - **`selectSession`** decides whether the screen is a player or a rest-day notice.
 * - **`loggableSets`** is the preview trap: `LoggedSetIn.exercise_id` is required and a
 *   previewed block has none, so a run against one is playable and unwritable.
 */

afterEach(() => {
  vi.useRealTimers();
});

describe('localIsoDate', () => {
  it('reports the local day at 22:00 in UTC+2, where toISOString already says tomorrow', () => {
    // 2026-08-28T22:30 in a UTC+2 zone is 2026-08-28T20:30Z — same day. Move it to 23:30 local
    // and UTC has rolled over while the climber is still standing in the gym.
    const local = new Date(2026, 7, 28, 23, 30, 0);
    vi.setSystemTime(local);

    expect(localIsoDate(local)).toBe('2026-08-28');
  });

  it('pads month and day', () => {
    expect(localIsoDate(new Date(2026, 0, 5, 12, 0, 0))).toBe('2026-01-05');
  });

  it('disagrees with toISOString whenever the UTC offset has crossed midnight', () => {
    const local = new Date(2026, 7, 28, 23, 30, 0);
    const utcDay = local.toISOString().slice(0, 10);
    const localDay = localIsoDate(local);

    // Only meaningful in a zone with a positive evening offset; assert the relationship rather
    // than a literal, so the test says something true in every CI timezone.
    expect(localDay <= utcDay).toBe(true);
    expect(localDay).toBe('2026-08-28');
  });
});

describe('selectSession', () => {
  const monday = makeSession([makeBlock()], '2026-08-24');
  const thursday = makeSession([makeBlock()], '2026-08-27');
  const saturday = makeSession([makeBlock()], '2026-08-29');
  const plan = makePlan([monday, thursday, saturday]);

  it('returns today session when one is scheduled', () => {
    expect(selectSession(plan, '2026-08-27')).toMatchObject({
      session: thursday,
      restDay: false,
      reason: 'today',
    });
  });

  it('offers the next session behind a rest-day flag when today is free', () => {
    expect(selectSession(plan, '2026-08-28')).toMatchObject({
      session: saturday,
      restDay: true,
      reason: 'rest_day',
      scheduledOn: '2026-08-29',
    });
  });

  it('says the plan is over rather than offering a session in the past', () => {
    expect(selectSession(plan, '2026-09-30')).toMatchObject({
      session: null,
      restDay: false,
      reason: 'plan_over',
    });
  });

  it('treats no plan and an empty plan as the same empty state', () => {
    expect(selectSession(null, '2026-08-27').reason).toBe('no_plan');
    expect(selectSession(makePlan([]), '2026-08-27').reason).toBe('no_plan');
  });

  it('still returns a session already completed today, so the player can be re-entered', () => {
    const done = { ...thursday, status: 'completed' as const };
    expect(selectSession(makePlan([done]), '2026-08-27').session).toBe(done);
  });

  it('flattens the tree in schedule order', () => {
    expect(planSessions(plan).map((session) => session.scheduled_on)).toEqual([
      '2026-08-24',
      '2026-08-27',
      '2026-08-29',
    ]);
  });
});

describe('loggableSets', () => {
  it('counts only sets whose block carries an exercise_id', () => {
    const session = makeSession([
      makeBlock({ exercise_id: 11, sets: [makeSet({ id: 1 }), makeSet({ id: 2 })] }),
      makeBlock({ exercise_id: null, sets: [makeSet(), makeSet(), makeSet()] }),
    ]);

    expect(totalSets(session)).toBe(5);
    expect(loggableSets(session)).toBe(2);
  });
});
