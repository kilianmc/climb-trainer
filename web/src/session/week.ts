import type { PlanSession, SessionCompletion } from '../api/types';
import type {
  BlockMarks,
  CompletionBadge,
  CompletionBand,
  CompletionScope,
} from '../plan/completion';
import { completionBadge, completionWord, doneBlocks } from '../plan/completion';
import type { PhaseWeekAspect } from '../plan/phaseWeek';
import {
  ASPECT_KEYS,
  WEEKDAY_COUNT,
  WEEKDAY_LABELS,
  aspect,
  sessionAspects,
} from '../plan/phaseWeek';

import type { RunRecord } from './runStore';
import { sessionCompletion } from './runStore';
import { localIsoDate } from './today';

/* This calendar week on the session screen: what each day asked for, how much of it got done,
   and which days are still owed. Pure — the date is passed in, exactly as `today.ts` is. */

/** The seven local ISO dates of the Monday–Sunday week `now` falls in. Local parts only, for
 *  the reason `today.ts::localIsoDate` gives: `toISOString()` is a silent timezone bug. */
export function weekDays(now: Date): readonly string[] {
  // `getDay()` counts from Sunday; this week does not. `new Date(y, m, d ± n)` normalises, so a
  // month or a year edge is the platform's arithmetic rather than ours.
  const back = (now.getDay() + 6) % WEEKDAY_COUNT;
  return Array.from({ length: WEEKDAY_COUNT }, (_, index) =>
    localIsoDate(new Date(now.getFullYear(), now.getMonth(), now.getDate() - back + index)),
  );
}

/** Today's session and the next one after it. Both `null` is "the plan has nothing left". */
export interface SessionsAround {
  readonly today: PlanSession | null;
  readonly next: PlanSession | null;
}

/** `sessions` is in schedule order, so the first match forward is the next one still OWED — one
 *  pulled forward and finished is over (#82). Today's is returned closed or not: it needs a word. */
export function sessionsAround(
  sessions: readonly PlanSession[],
  todayIso: string,
  closed: SessionClosed,
): SessionsAround {
  return {
    today: sessions.find((session) => session.scheduled_on === todayIso) ?? null,
    next: sessions.find((session) => session.scheduled_on > todayIso && !closed(session)) ?? null,
  };
}

/** A day BEFORE today is settled; today and every day after it can still be reached. */
function completionScope(scheduledOn: string, todayIso: string): CompletionScope {
  return scheduledOn < todayIso ? 'settled' : 'progress';
}

/** What the SERVER row alone says about a session: the word its card wears and the marks its
 *  parts wear — ONE reading, and the only one that survives a reload. */
export interface SessionReport {
  readonly badge: CompletionBadge | null;
  readonly marks: BlockMarks | null;
}

/** A `null` session is a rest day, which has nothing to report. */
export function sessionReport(
  session: PlanSession | null,
  completion: ReadonlyMap<number, SessionCompletion>,
  todayIso: string,
): SessionReport {
  if (session === null) return { badge: null, marks: null };
  const row = session.id == null ? undefined : completion.get(session.id);
  const scope = completionScope(session.scheduled_on, todayIso);
  return { badge: completionBadge(row, scope), marks: doneBlocks(row, scope) };
}

/** One session of this week that is still owed, with the word and band its card carries. */
export interface PendingSession {
  readonly session: PlanSession;
  readonly badge: CompletionBadge;
  readonly marks: BlockMarks | null;
}

/** The sessions of THIS week scheduled before today that never reached 100%, oldest first.
 *  ⚠️ `status` is not consulted: a session ended at 66% is still owed. */
export function pendingSessions(
  sessions: readonly PlanSession[],
  completion: ReadonlyMap<number, SessionCompletion>,
  todayIso: string,
  week: readonly string[],
  closed: SessionClosed,
): readonly PendingSession[] {
  const monday = week[0];
  if (monday === undefined) return [];

  const owed: PendingSession[] = [];
  for (const session of sessions) {
    if (session.scheduled_on < monday || session.scheduled_on >= todayIso) continue;
    // `null` while the SERVER still calls the day pending — the client never marks a day past on
    // a clock of its own — and also when the day had no blocks to do. A closed one is not owed.
    const { badge, marks } = sessionReport(session, completion, todayIso);
    if (badge === null || closed(session)) continue;
    owed.push({ session, badge, marks });
  }
  return owed.sort((a, b) => a.session.scheduled_on.localeCompare(b.session.scheduled_on));
}

/** What an offer's control may still do. ⚠️ `done` is the ONLY closed state: an offer stays
 *  startable while anything is left to do, however many attempts that takes. */
export type OfferState = 'open' | 'unfinished' | 'unsaved' | 'done';

/** What one offer says and what its control may do, from ONE reading of one figure. */
export interface OfferView {
  readonly state: OfferState;
  /** The word and the band the card wears; `null` while nothing has a result to report. */
  readonly badge: CompletionBadge | null;
  /** THIS session's run record, or `null` — what the card describes instead of the plan. ⚠️ Its
   *  own, never merely "the finished run": Monday's would otherwise describe today's card. */
  readonly record: RunRecord | null;
}

/** How much of a session on offer is still owed — the ONE reading its completed tone, its badge
 *  and its Start button take, on every day alike. See CLAUDE.md, "Session player invariants". */
export function offerView(
  session: PlanSession,
  finished: RunRecord | null,
  badge: CompletionBadge | null,
  unsentCount: number,
): OfferView {
  const own =
    finished !== null && finished.plannedSessionId === (session.id ?? null) ? finished : null;
  // ⚠️ THE RUN RECORD BEATS THE SERVER BADGE: that badge is up to ten minutes stale between
  // Finish and the refetch, so a card would contradict the summary the climber just closed.
  const resolved = own === null ? badge : completionWord(sessionCompletion(own).percent);
  if (resolved?.band === 'full') return { state: 'done', badge: resolved, record: own };
  if (own === null) return { state: 'open', badge: resolved, record: null };
  // ⚠️ `unsaved` is not "done", it is "not through this control": `start` REPLACES this record,
  // so `UnsavedRun` owns the offer for as long as it holds sets the server never got.
  return { state: unsentCount > 0 ? 'unsaved' : 'unfinished', badge: resolved, record: own };
}

/** Whether a session is CLOSED FOR GOOD: 100% of its loggable items, no restart, and gone from
 *  the three offer sections (#82). ⚠️ NOT the week strip — that is the calendar. */
export type SessionClosed = (session: PlanSession) => boolean;

/** ⚠️ The run record is read AHEAD of the badge, as `offerView` does and for the same reason:
 *  the badge is up to ten minutes stale between Finish and the refetch. */
export function sessionClosed(
  completion: ReadonlyMap<number, SessionCompletion>,
  todayIso: string,
  finished: RunRecord | null,
  unsentCount: number,
): SessionClosed {
  return (session) =>
    offerView(session, finished, sessionReport(session, completion, todayIso).badge, unsentCount)
      .state === 'done';
}

/** A day's completion: the word at every width, the percentage where the cell is too narrow. */
export interface WeekDayMark {
  readonly label: string;
  readonly short: string;
  readonly band: CompletionBand;
}

export interface WeekDay {
  readonly iso: string;
  /** Monday-first, matching `phaseWeek.ts`'s columns and `planned_session.weekday`. */
  readonly weekday: number;
  readonly label: string;
  readonly dayOfMonth: string;
  readonly isToday: boolean;
  readonly aspects: readonly PhaseWeekAspect[];
  readonly mark: WeekDayMark | null;
}

export interface WeekView {
  readonly days: readonly WeekDay[];
  /** Only the aspects this week uses: the caption explains the codes and nothing else. */
  readonly legend: readonly PhaseWeekAspect[];
}

function dayOfMonth(iso: string): string {
  const day = iso.split('-')[2];
  return day === undefined ? iso : String(Number(day));
}

/** ⚠️ Every channel is the PERCENTAGE's — the word, the short form and the band the cell's edge
 *  is keyed on. Nothing here may come from `status` or `state`: that was the #82 defect. */
function dayMark(
  rows: readonly (SessionCompletion | undefined)[],
  scope: CompletionScope,
): WeekDayMark | null {
  for (const row of rows) {
    const badge = completionBadge(row, scope);
    if (badge === null || row?.percent == null) continue;
    return { label: badge.label, short: `${String(row.percent)}%`, band: badge.band };
  }
  return null;
}

/** One row of seven days: the plan's aspect codes per day, plus what each past day came to. */
export function weekView(
  sessions: readonly PlanSession[],
  completion: ReadonlyMap<number, SessionCompletion>,
  todayIso: string,
  week: readonly string[],
): WeekView {
  const days = week.map((iso, weekday): WeekDay => {
    const onDay = sessions.filter((session) => session.scheduled_on === iso);
    const rows = onDay.map((session) =>
      session.id == null ? undefined : completion.get(session.id),
    );
    return {
      iso,
      weekday,
      label: WEEKDAY_LABELS[weekday] ?? iso,
      dayOfMonth: dayOfMonth(iso),
      isToday: iso === todayIso,
      aspects: sessionAspects(onDay),
      mark: dayMark(rows, completionScope(iso, todayIso)),
    };
  });

  const used = new Set(days.flatMap((day) => day.aspects.map((entry) => entry.key)));
  return { days, legend: ASPECT_KEYS.filter((key) => used.has(key)).map((key) => aspect(key)) };
}
