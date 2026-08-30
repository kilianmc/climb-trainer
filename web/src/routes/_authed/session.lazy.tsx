import { createLazyFileRoute } from '@tanstack/react-router';

import { useAuth } from '../../auth/AuthProvider';
import { useLibrary } from '../../library/api';
import { useActivePlanView } from '../../plan/api';
import { exercisesByKey } from '../../plan/blueprint';
import { useVocabulary } from '../../profile/api';
import { SessionBrief } from '../../session/SessionBrief';
import { SessionPlayer } from '../../session/SessionPlayer';
import { SessionSummary } from '../../session/SessionSummary';
import { localIsoDate, selectSession } from '../../session/today';
import { useSessionRun } from '../../session/useSessionRun';

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
 * ⚠️ **A finished session cannot be re-STARTED, though it can be re-OPENED from the summary —
 * and WHICH SCREEN SHOWS IS READ OFF THE RECORD.** `summaryClosedAtEpochMs` is persisted because
 * this component unmounts on every navigation; as a `useState` flag it re-asked the RPE.
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
  const today = localIsoDate(new Date());
  const choice = selectSession(plan, today);
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

  const session = choice.session;
  // Matched on the planned session, not merely on the day: a rest-day brief offers a session
  // scheduled for later in the week, and finishing today's does not close that one.
  const done =
    finished !== null &&
    finished.occurredOn === today &&
    session !== null &&
    finished.plannedSessionId === (session.id ?? null);

  return (
    <SessionBrief
      choice={choice}
      plan={plan}
      vocabulary={vocabulary.data}
      exercises={index}
      run={run}
      readOnly={readOnly}
      stale={finished !== null && run.unsentCount > 0 ? finished : null}
      done={done}
      onStart={() => {
        if (session === null || plan === null || done) return;
        run.start({ session, exercises: index, discipline: plan.discipline });
      }}
    />
  );
}

export const Route = createLazyFileRoute('/_authed/session')({ component: Session });
