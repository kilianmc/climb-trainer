import { createLazyFileRoute } from '@tanstack/react-router';

import { useAuth } from '../../auth/AuthProvider';
import { useLibrary } from '../../library/api';
import { useActivePlanView } from '../../plan/api';
import { exercisesByKey } from '../../plan/blueprint';
import { completionBySession, useSessionCompletion } from '../../plan/completion';
import { useVocabulary } from '../../profile/api';
import { NothingToday, SessionBrief } from '../../session/SessionBrief';
import { SessionPlayer } from '../../session/SessionPlayer';
import { SessionSummary } from '../../session/SessionSummary';
import { localIsoDate, planSessions } from '../../session/today';
import { useSessionRun } from '../../session/useSessionRun';
import {
  pendingSessions,
  sessionClosed,
  sessionReport,
  sessionsAround,
  weekDays,
  weekView,
} from '../../session/week';

/**
 * `/session` — follow today's session along, with a timer, a colour and a cue per phase.
 *
 * **Three screens, one route, and no search param.** Brief → player → summary is a run in
 * progress, not a place; the persisted run (`runStore.ts`) is what decides which one shows, so
 * closing the tab mid-set and coming back lands on the phase the wall clock says it should.
 * That is also why the nav link stays bare: a URL that named a phase would be a second,
 * disagreeing source of truth.
 *
 * ⚠️ **`run.start` is called STRAIGHT out of the click.** It builds the `AudioContext` inside the
 * gesture; one built in an effect starts suspended and on iOS never resumes. It starts no timer:
 * the session is a list of items and each one is entered on its own control.
 *
 * ⚠️ **Re-STARTABLE until its BLOCKS are 100%, and at 100% the offer is GONE, card and all
 * (#82)** — `week.ts::sessionClosed` gates all three sections, so Finish closes nothing. **WHICH
 * SCREEN SHOWS IS READ OFF THE RECORD**: as `useState`, `summaryClosedAtEpochMs` re-asked the RPE.
 *
 * ⚠️ **The run always ends on the summary, never on the last set** — peak-end, and it is the only
 * screen that can say honestly whether the sets reached the server.
 *
 * **Two GATING reads, gated on `isLoadingError` and never on `isError`** (the vocabulary is a
 * third, UNGATED one — see `useVocabulary` below): query-core's error reducer sets
 * `status: "error"` even with data present, so a failed background refetch must not take a
 * session off the screen mid-run. `useLibrary` plus `exercisesByKey` names the exercises, once.
 */
function Session() {
  const active = useActivePlanView();
  const library = useLibrary();
  // ⚠️ NOT in the gate below, and deliberately not retried here: this feeds the brief's phase
  // reminder, which is absent until it lands. Nothing about the session may wait on it.
  const vocabulary = useVocabulary();
  // #82: the same read `/plan` colours its calendar with, and the same cache entry — the week
  // strip and the pending list are that figure, not a second derivation of it.
  const completion = useSessionCompletion(active.plan ?? null);
  const run = useSessionRun();
  // Issue #65: in demo scope the player runs in full and no PUT is ever issued, so the save
  // affordances are ABSENT rather than greyed out. `useSessionRun` enforces the write half.
  const readOnly = useAuth().scope === 'demo';

  const exercises = library.data?.exercises;

  if (active.plan === undefined || exercises === undefined) {
    const failed = active.isLoadingError || library.isLoadingError;
    return (
      <>
        <h1>Session</h1>
        {failed ? (
          <>
            <p className="ct-app__status ct-app__status--error" role="alert">
              {active.isLoadingError
                ? 'We could not read your plan, so we cannot tell which session is on today.'
                : 'The exercise library could not be loaded, so the session has no exercises to name.'}
            </p>
            <div className="ct-app__actions">
              <button
                type="button"
                className="ct-app__button ct-app__button--primary"
                onClick={() => {
                  // Only what failed: each read is cached, and refetching a healthy one because
                  // its neighbour broke is a wasted Neon wake.
                  if (active.isLoadingError) active.retry();
                  if (library.isLoadingError) void library.refetch();
                }}
              >
                Try again
              </button>
            </div>
          </>
        ) : (
          <p className="ct-app__status">Loading today’s session…</p>
        )}
      </>
    );
  }

  const plan = active.plan;
  const now = new Date();
  const today = localIsoDate(now);
  const days = weekDays(now);
  const sessions = planSessions(plan);
  const rows = completionBySession(completion.data);
  const index = exercisesByKey(exercises);

  if (run.status === 'running') return <SessionPlayer run={run} readOnly={readOnly} />;

  const finished = run.status === 'finished' ? run.run : null;
  const showSummary =
    finished !== null && finished.summaryClosedAtEpochMs === null && finished.occurredOn === today;

  if (showSummary) {
    return (
      <SessionSummary
        run={run}
        readOnly={readOnly}
        // ⚠️ Never `abort()` here. Deleting the record would put Start back on the brief for a
        // session that is done; with sets still owed it would also throw them away.
        onClose={run.closeSummary}
        onResume={run.resume}
      />
    );
  }

  // Matched on the planned session, not merely on the day: finishing today's session does not
  // close the one owed from Monday, and either may be the run that is finished.
  const own = finished !== null && finished.occurredOn === today ? finished : null;
  // ⚠️ ONE gate for all three offer sections AND for Start: at 100% a session is closed for
  // good (#82), so the two behind today are skipped over rather than offered as closed cards.
  const closed = sessionClosed(rows, today, own, run.unsentCount);
  const around = sessionsAround(sessions, today, closed);
  const pending = pendingSessions(sessions, rows, today, days, closed);

  // Nothing today, nothing ahead and nothing owed. A session owed from earlier this week is
  // still worth a screen, so the empty state is the LAST branch rather than the first.
  if (around.today === null && around.next === null && pending.length === 0) {
    return <NothingToday reason={sessions.length === 0 ? 'no_plan' : 'plan_over'} />;
  }

  return (
    <SessionBrief
      week={weekView(sessions, rows, today, days)}
      pending={pending}
      todaySession={around.today}
      todayReport={sessionReport(around.today, rows, today)}
      next={around.next}
      nextReport={sessionReport(around.next, rows, today)}
      plan={plan}
      vocabulary={vocabulary.data}
      exercises={index}
      run={run}
      readOnly={readOnly}
      stale={finished !== null && run.unsentCount > 0 ? finished : null}
      finished={own}
      onStart={(session, marks) => {
        if (plan === null) return;
        run.start({ session, exercises: index, discipline: plan.discipline, marks });
      }}
    />
  );
}

export const Route = createLazyFileRoute('/_authed/session')({ component: Session });
