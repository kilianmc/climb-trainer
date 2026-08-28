import { elapsedMinutes } from './clock';
import type { RunRecord } from './runStore';
import { sessionCompletion } from './runStore';
import type { SessionRun } from './useSessionRun';

/** 1–10, the scale the server stores on `session.rpe`. **One-based, not zero-based** — a `0`
 * option would be a value the column's own bound refuses. */
const RPE_VALUES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10] as const;

/**
 * The last screen of every run, and the run always ends here — never on the final set.
 *
 * Peak-end: what a climber remembers of a session is its hardest moment and its last one, and
 * the last one should be "that is logged" rather than a countdown hitting zero. It is also the
 * only place that can tell the truth about the write, which is why the save state is a sentence
 * and not a spinner.
 */
export function SessionSummary({
  run,
  readOnly,
  onClose,
  onResume,
}: {
  run: SessionRun;
  readOnly: boolean;
  onClose: () => void;
  /** "Go back to the session" — reopens the run LOCALLY. See `useSessionRun.resume`. */
  onResume: () => void;
}) {
  const record = run.run;
  if (record === null) return null;

  const done = record.logged.length + record.pending.length;
  // Not `Date.now()`: a render must be pure, and a duration that kept growing on screen would
  // be a lie about a session that has ended. The fallback is unreachable — see the routing.
  const finishedAt = record.finishedAtEpochMs ?? record.startedAtEpochMs;
  const minutes = elapsedMinutes(record.startedAtEpochMs, finishedAt);
  const completion = sessionCompletion(record);

  return (
    <>
      <h1>Session done</h1>
      <p className="ct-app__lede">
        {String(done)} set{done === 1 ? '' : 's'} in {String(minutes)} minute
        {minutes === 1 ? '' : 's'} — {String(completion.percent)}% of the session.
      </p>
      {/* ⚠️ The SERVER's definition, so the plan screen reads the same number later: blocks with
          at least one logged set over total blocks. Finish is not completeness. */}
      <p className="ct-app__muted">
        {String(completion.blocksDone)} of {String(completion.blockCount)} part
        {completion.blockCount === 1 ? '' : 's'} logged at least one set. Pressing Finish is what
        ends a session; it does not mean everything got done.
      </p>

      <SessionRpe run={run} />
      <SaveState run={run} record={record} readOnly={readOnly} />

      {/* ⚠️ Kilian: "if i click session done by mistake i cannot go back … that way i can finish
          a session i had pending." Secondary, and beside Done rather than in place of it. */}
      <div className="ct-app__actions">
        <button type="button" className="ct-app__button" onClick={onResume}>
          Go back to the session
        </button>
        <button type="button" className="ct-app__button ct-app__button--primary" onClick={onClose}>
          Done
        </button>
      </div>
      {/* ⚠️ It resumes; it does not un-record. Saying "undo" here would be a lie the server
          cannot honour — `planned_session.status` never moves backwards. */}
      <p className="ct-app__muted">
        Pressed Finish too early? Going back opens the session again so you can carry on with what
        is left.
        {readOnly
          ? ' Nothing is written down either way on the demo account.'
          : ' It does not undo the finish — this session is already in your diary, and anything you do now is added to it.'}
      </p>
    </>
  );
}

/**
 * Its OWN PUT rather than part of Finish: pressing Finish has to persist even if the climber
 * walks away, which at the end of a session is the normal case rather than the edge one.
 *
 * A real `<select>` on the shared `ct-app__select` primitive (`_profile.scss`, and the same
 * markup `profile/steps.tsx` uses), not ten buttons: ten controls in a row is a wall on a phone,
 * and the wrapper is where the chevron is drawn once for the whole app.
 */
function SessionRpe({ run }: { run: SessionRun }) {
  const chosen = run.run?.sessionRpe ?? null;
  return (
    <section className="ct-app__card">
      <h2>How hard was that?</h2>
      <p className="ct-app__muted">
        1 is barely anything, 10 is everything you had. It is the whole session, not the hardest
        set.
      </p>
      <label className="ct-app__field" htmlFor="ct-session-rpe">
        Session RPE
        <span className="ct-app__select">
          <select
            id="ct-session-rpe"
            className="ct-app__input"
            value={chosen ?? ''}
            onChange={(event) => {
              const value = Number(event.target.value);
              if (Number.isFinite(value) && value > 0) run.setSessionRpe(value);
            }}
          >
            <option value="">Choose a number</option>
            {RPE_VALUES.map((value) => (
              <option key={value} value={value}>
                {String(value)}
              </option>
            ))}
          </select>
        </span>
      </label>
    </section>
  );
}

/** ⚠️ Four outcomes, four sentences — saved, still sending, a 5xx that goes out again, and a
 *  4xx that never will. Collapsed into one spinner, an unsaved session looks saved. */
function SaveState({
  run,
  record,
  readOnly,
}: {
  run: SessionRun;
  record: RunRecord;
  readOnly: boolean;
}) {
  if (readOnly) {
    return (
      <p className="ct-app__notice" role="note">
        <span>
          Nothing was written down — this is the demo account, and the player ran the whole session
          locally. In your own account this would already be in your diary.
        </span>
      </p>
    );
  }

  return (
    <>
      {run.quarantinedCount > 0 ? (
        <p className="ct-app__error" role="alert">
          {String(run.quarantinedCount)} set{run.quarantinedCount === 1 ? '' : 's'} the server
          refused, and {run.quarantinedCount === 1 ? 'it will' : 'they will'} not be sent again —
          sending {run.quarantinedCount === 1 ? 'it' : 'them'} once more could only be refused the
          same way. The rest of the session is unaffected.
        </p>
      ) : null}

      {run.unsentCount > 0 ? (
        <>
          <p className="ct-app__status ct-app__status--error" role="alert">
            {String(run.unsentCount)} set{run.unsentCount === 1 ? '' : 's'}{' '}
            {run.unsentCount === 1 ? 'has' : 'have'} not reached the server yet. They are saved on
            this device and go out on the next try.
          </p>
          <div className="ct-app__actions">
            <button
              type="button"
              className="ct-app__button ct-app__button--primary"
              disabled={run.isSaving}
              onClick={run.retryFlush}
            >
              {run.isSaving ? 'Saving…' : 'Retry'}
            </button>
          </div>
        </>
      ) : (
        <p className="ct-app__status">
          {record.savedAtEpochMs === null ? 'Saving…' : 'Saved to your diary.'}
        </p>
      )}
    </>
  );
}
