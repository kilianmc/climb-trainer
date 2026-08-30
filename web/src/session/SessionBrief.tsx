import type { LibraryExercise, PlanSession, PlanTree, Vocabulary } from '../api/types';
import { PhaseGuideNote, PlanFacts, phaseGuides, phaseLabel } from '../plan/PhaseGuide';
import { exerciseLabel, formatDay, sessionSummary } from '../plan/blueprint';
import { phaseInPlan, sessionBlock, sessionBlockFacts } from '../plan/explain';

import { ItemRow } from './ItemRow';
import type { RunRecord } from './runStore';
import { sessionCompletion } from './runStore';
import type { SessionChoice } from './today';
import { loggableSets, totalSets } from './today';
import type { ItemView, SessionRun } from './useSessionRun';

/** ⚠️ `onStart` is called STRAIGHT out of the click: `useSessionRun.start` builds the
 *  `AudioContext` in it, and one built elsewhere starts suspended and never resumes on iOS. */
export function SessionBrief({
  choice,
  plan,
  vocabulary,
  exercises,
  run,
  readOnly,
  stale,
  done,
  onStart,
}: {
  choice: SessionChoice;
  /** `null` is "no plan yet", which `NothingToday` already covers — the reminder stays absent. */
  plan: PlanTree | null;
  /** ⚠️ `undefined` until `GET /api/vocabulary` lands, and the brief NEVER waits for it: the
   *  phase reminder is absent while it is missing. See `routes/_authed/session.lazy.tsx`. */
  vocabulary: Vocabulary | undefined;
  exercises: ReadonlyMap<string, LibraryExercise>;
  run: SessionRun;
  readOnly: boolean;
  /** A finished run from another day that never reached the server, or `null`. */
  stale: RunRecord | null;
  /** This session has already been finished today. **There is no way back into it.** */
  done: boolean;
  onStart: () => void;
}) {
  const session = choice.session;
  if (session === null) return <NothingToday reason={choice.reason} />;

  return (
    <>
      <h1>Session</h1>
      {choice.restDay ? <RestDayNotice scheduledOn={choice.scheduledOn} /> : null}
      {stale === null ? null : <UnsavedRun stale={stale} run={run} />}
      <SessionCard
        session={session}
        plan={plan}
        vocabulary={vocabulary}
        exercises={exercises}
        done={done}
        run={run}
      />
      {readOnly ? (
        <p className="ct-app__notice" role="note">
          <span>
            The player runs in full on the demo account — timer, cues and all — and nothing is
            written down. In your own account this session would land in your diary.
          </span>
        </p>
      ) : null}
      {done ? <SessionDone /> : null}
      <div className="ct-app__actions">
        {/* ⚠️ Absent, not disabled, once the session is done: a finished session cannot be
            started again, and a greyed-out Start invites the press anyway. */}
        {done ? null : (
          <button
            type="button"
            className="ct-app__button ct-app__button--primary"
            onClick={onStart}
          >
            {choice.restDay ? 'Start it anyway' : 'Start session'}
          </button>
        )}
      </div>
    </>
  );
}

/** The session is over and stays over. Said plainly rather than by a missing button, which on
 *  its own reads as a bug. */
function SessionDone() {
  return (
    <p className="ct-app__notice" role="note">
      <span>
        You have already finished this session — it is in your diary. Whatever you do now is a new
        session, and today’s plan is done.
      </span>
    </p>
  );
}

/** ⚠️ Coaching copy, so CLAUDE.md's "never recommends losing weight" rule binds its tone: this
 *  says what recovery is FOR, never prices it, and never mentions weight or body composition. */
function RestDayNotice({ scheduledOn }: { scheduledOn: string | null }) {
  return (
    <p className="ct-app__notice" role="note">
      <span>
        Today is a rest day — your plan calls for recovery. That is where the training actually
        lands: the adaptation from your last session happens on the days between sessions, not
        during them, so taking it is the plan working as intended.
        {scheduledOn === null
          ? ''
          : ` Your next session is ${formatDay(scheduledOn)}, and it is below if you would rather do it today.`}
      </span>
    </p>
  );
}

/** The plan ran out, or there is no plan. Neither is an error and neither offers a retry. */
function NothingToday({ reason }: { reason: SessionChoice['reason'] }) {
  return (
    <>
      <h1>Session</h1>
      <p className="ct-app__lede">
        {reason === 'plan_over'
          ? 'Your plan has no sessions left. Build the next one from the Plan screen whenever you are ready.'
          : 'There is nothing to follow along with yet. Start a plan and today’s session shows up here.'}
      </p>
    </>
  );
}

/** A finished run whose sets never reached the server, offered BEFORE Start: starting mints a
 *  new run under the same key, and saying so plainly beats discovering it afterwards. */
function UnsavedRun({ stale, run }: { stale: RunRecord; run: SessionRun }) {
  return (
    <>
      <p className="ct-app__notice" role="note">
        <span>
          Your session from {formatDay(stale.occurredOn)} has {String(run.unsentCount)} set
          {run.unsentCount === 1 ? '' : 's'} that never reached the server. Save it now — starting a
          new session replaces it.
        </span>
      </p>
      <div className="ct-app__actions">
        <button
          type="button"
          className="ct-app__button"
          disabled={run.isSaving}
          onClick={run.retryFlush}
        >
          {run.isSaving ? 'Saving…' : 'Save it now'}
        </button>
        <button type="button" className="ct-app__button" onClick={run.abort}>
          Discard it
        </button>
      </div>
    </>
  );
}

/** What the session is, joined against the library — exercise names are not in the plan tree. */
function SessionCard({
  session,
  plan,
  vocabulary,
  exercises,
  done,
  run,
}: {
  session: PlanSession;
  plan: PlanTree | null;
  vocabulary: Vocabulary | undefined;
  exercises: ReadonlyMap<string, LibraryExercise>;
  /** Finished and closed. The card takes the item rows' completed tone; `SessionDone` below
   *  says the same thing in words, because colour is never the only channel. */
  done: boolean;
  run: SessionRun;
}) {
  const loggable = loggableSets(session);
  const total = totalSets(session);
  const record = done ? run.run : null;

  return (
    <section className="ct-app__card" data-state={done ? 'completed' : undefined}>
      <h2>
        {session.title} <span className="ct-app__badge">{formatDay(session.scheduled_on)}</span>
      </h2>
      <p className="ct-app__muted">{sessionSummary(session)}</p>
      {/* Inside the card on purpose: on a rest day the card is NEXT week's session, and a week
          number sitting above it would read as today's. */}
      <PhaseReminder plan={plan} session={session} vocabulary={vocabulary} />
      {/* Once it is over the card answers what HAPPENED instead of what was planned: the
          outcome list below already names every block and its set count. */}
      {record === null ? (
        <ul className="ct-app__terms">
          {session.blocks.map((block) => (
            <li key={block.order_index}>
              <strong>{exerciseLabel(block.exercise_key, exercises)}</strong> {block.sets.length}{' '}
              set{block.sets.length === 1 ? '' : 's'}
            </li>
          ))}
        </ul>
      ) : (
        <SessionOutcome record={record} items={run.items} />
      )}
      {/* `LoggedSetIn.exercise_id` is required, so a block without one is playable and
          unloggable. Said up front rather than discovered in the summary. */}
      {loggable < total ? (
        <p className="ct-app__notice" role="note">
          <span>
            {String(total - loggable)} of these {String(total)} sets cannot be written to your diary
            — the plan does not name an exercise for them. The timer still runs the whole session.
          </span>
        </p>
      ) : null}
    </section>
  );
}

/** What the session came to. The percentage is `sessionCompletion`, the SAME call the summary
 *  makes; the rows are the player's own, childless — read-only, and the state word stays. */
function SessionOutcome({ record, items }: { record: RunRecord; items: readonly ItemView[] }) {
  const completion = sessionCompletion(record);
  return (
    <>
      <p className="ct-app__lede">
        {String(completion.percent)}% of the session — {String(completion.blocksDone)} of{' '}
        {String(completion.blockCount)} part{completion.blockCount === 1 ? '' : 's'} logged at least
        one set.
      </p>
      <ol className="ct-app__items">
        {items.map((item) => (
          <ItemRow key={item.blockIndex} item={item} />
        ))}
      </ol>
    </>
  );
}

/* Which week and which block this session belongs to, plus the phase copy `/plan` discloses.
   ⚠️ Every figure comes from the session ON SCREEN, never from today — see `sessionBlock`. */
function PhaseReminder({
  plan,
  session,
  vocabulary,
}: {
  plan: PlanTree | null;
  session: PlanSession;
  vocabulary: Vocabulary | undefined;
}) {
  // Absent, not delayed, and not a loading line: a reminder is worth nothing next to the
  // session it reminds you about, and the vocabulary is a separate, uncoupled read.
  if (plan === null || vocabulary === undefined) return null;
  const block = sessionBlock(plan, session);
  if (block === null) return null;

  const guides = phaseGuides(vocabulary);
  return (
    <>
      <PlanFacts facts={sessionBlockFacts(plan, block, phaseLabel(guides, block.phase))} />
      <PhaseGuideNote guide={guides.get(block.phase)} inPlan={phaseInPlan(plan, block.phase)} />
    </>
  );
}
