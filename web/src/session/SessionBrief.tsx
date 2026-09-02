import type { LibraryExercise, PlanSession, PlanTree, Vocabulary } from '../api/types';
import type { BlockMarks, CompletionBadge } from '../plan/completion';
import { BLOCK_MARK_LABEL, blockOutcome } from '../plan/completion';
import { PhaseGuideNote, PlanFacts, phaseGuides, phaseLabel } from '../plan/PhaseGuide';
import { exerciseLabel, formatDay, sessionSummary } from '../plan/blueprint';
import { phaseInPlan, sessionBlock, sessionBlockFacts } from '../plan/explain';

import { ItemRow } from './ItemRow';
import { SessionWeek } from './SessionWeek';
import type { RunRecord } from './runStore';
import { sessionCompletion } from './runStore';
import type { SelectionReason } from './today';
import { loggableSets, totalSets } from './today';
import type { ItemView, SessionRun } from './useSessionRun';
import type { PendingSession, SessionReport, WeekView } from './week';
import { offerView } from './week';

/* The brief, in Kilian's order (#82): this week's calendar, then what is still owed from earlier
   in it, then today, then the next session. ⚠️ AN OFFER CLOSES ONLY AT 100% — see `offerView`. */

/** ⚠️ `onStart` is called STRAIGHT out of the click: `useSessionRun.start` builds the
 *  `AudioContext` in it, and one built elsewhere starts suspended and never resumes on iOS. */
export function SessionBrief({
  week,
  pending,
  todaySession,
  todayReport,
  next,
  nextReport,
  plan,
  vocabulary,
  exercises,
  run,
  readOnly,
  stale,
  finished,
  onStart,
}: {
  week: WeekView;
  /** Owed from earlier THIS week, oldest first. Rendered only when there are any. */
  pending: readonly PendingSession[];
  /** `null` on a rest day, which is the one case the Today section carries a notice instead. */
  todaySession: PlanSession | null;
  /** ⚠️ What the SERVER holds for today, and the only thing that survives a reload: without it
   *  a session completed earlier today would offer Start again and show none of its parts done. */
  todayReport: SessionReport;
  /** The next session after today, startable on every day — tomorrow may be pulled forward. */
  next: PlanSession | null;
  /** The same reading for the next session: it may already have been pulled forward and done. */
  nextReport: SessionReport;
  /** `null` is "no plan yet", which the route's own empty state covers. */
  plan: PlanTree | null;
  /** ⚠️ `undefined` until `GET /api/vocabulary` lands, and the brief NEVER waits for it: the
   *  phase reminder is absent while it is missing. See `routes/_authed/session.lazy.tsx`. */
  vocabulary: Vocabulary | undefined;
  exercises: ReadonlyMap<string, LibraryExercise>;
  run: SessionRun;
  readOnly: boolean;
  /** A finished run holding sets that never reached the server, or `null`. Whichever session it
   *  belongs to reads `unsaved` and offers no Start, because starting replaces the record. */
  stale: RunRecord | null;
  /** A run finished today, whichever session it was — see `offerView`. */
  finished: RunRecord | null;
  onStart: (session: PlanSession, marks: BlockMarks | null) => void;
}) {
  const offer = { plan, vocabulary, exercises, run, finished, onStart };

  return (
    <div className="ct-app__brief">
      <h1>Session</h1>
      {readOnly ? <DemoNotice /> : null}
      {stale === null ? null : (
        <section>
          <UnsavedRun stale={stale} run={run} />
        </section>
      )}
      <section>
        <SessionWeek week={week} />
      </section>
      {pending.length === 0 ? null : (
        <section>
          <h2>Pending from previous days</h2>
          {pending.map((owed) => (
            <SessionOffer
              key={owed.session.id ?? owed.session.scheduled_on}
              session={owed.session}
              badge={owed.badge}
              marks={owed.marks}
              startLabel="Start it now"
              primary={false}
              {...offer}
            />
          ))}
        </section>
      )}
      <section>
        <h2>Today</h2>
        {todaySession === null ? (
          <RestDayNotice scheduledOn={next?.scheduled_on ?? null} />
        ) : (
          <SessionOffer
            session={todaySession}
            badge={todayReport.badge}
            marks={todayReport.marks}
            startLabel="Start session"
            primary
            {...offer}
          />
        )}
      </section>
      {next === null ? null : (
        <section>
          <h2>Next session</h2>
          {/* Primary only when nothing is due today: on a training day today's session is the
              one the plan asks for, and two primary buttons name no first choice. */}
          <SessionOffer
            session={next}
            badge={nextReport.badge}
            marks={nextReport.marks}
            startLabel="Start it anyway"
            primary={todaySession === null}
            {...offer}
          />
        </section>
      )}
    </div>
  );
}

/** The plan ran out, or there is no plan. Neither is an error and neither offers a retry. */
export function NothingToday({ reason }: { reason: SelectionReason }) {
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

/** One session on offer: what it is, how much of it is still owed, and the control — if any —
 *  that starts it. `offerView` gates all three, and whether there is a card at all. */
function SessionOffer({
  session,
  badge,
  marks,
  startLabel,
  primary,
  plan,
  vocabulary,
  exercises,
  run,
  finished,
  onStart,
}: {
  session: PlanSession;
  /** The band the card wears, word included — the SERVER's reading of this session, whichever
   *  day it sits on. `null` while it has nothing logged, which is what leaves a card untinted. */
  badge: CompletionBadge | null;
  /** Which of its parts the server holds as done. `null` leaves every part unmarked. */
  marks: BlockMarks | null;
  startLabel: string;
  primary: boolean;
  plan: PlanTree | null;
  vocabulary: Vocabulary | undefined;
  exercises: ReadonlyMap<string, LibraryExercise>;
  run: SessionRun;
  finished: RunRecord | null;
  onStart: (session: PlanSession, marks: BlockMarks | null) => void;
}) {
  // ⚠️ ONE reading for both the badge and the button — the `badge` prop is the SERVER's figure
  // and can be ten minutes behind the run that just ended.
  const offer = offerView(session, finished, badge, run.unsentCount);
  const state = offer.state;
  // ⚠️ Kilian, #82: a session with every item done "does not appear in past / current / next
  // session and does not let you restart". So the CARD goes too, and the note says to rest.
  if (state === 'done') return <SessionDone />;

  return (
    <div className="ct-app__offer">
      <SessionCard
        session={session}
        badge={offer.badge}
        marks={marks}
        record={offer.record}
        plan={plan}
        vocabulary={vocabulary}
        exercises={exercises}
        run={run}
      />
      {state === 'unfinished' || state === 'unsaved' ? (
        <SessionUnfinished unsaved={state === 'unsaved'} />
      ) : null}
      {/* ⚠️ Absent, not disabled: at `unsaved` a restart would replace the record holding sets
          the server never got. */}
      {state === 'open' || state === 'unfinished' ? (
        <div className="ct-app__actions">
          <button
            type="button"
            className={primary ? 'ct-app__button ct-app__button--primary' : 'ct-app__button'}
            onClick={() => {
              // ⚠️ `marks` travels with the press: the new run seeds the parts the server
              // already holds as completed, so a restart is not a session back at zero (#82).
              onStart(session, marks);
            }}
          >
            {state === 'unfinished' ? 'Start it again' : startLabel}
          </button>
        </div>
      ) : null}
    </div>
  );
}

/** Issue #65: the player runs in full on the demo account and no PUT is ever issued. */
function DemoNotice() {
  return (
    <p className="ct-app__notice" role="note">
      <span>
        The player runs in full on the demo account — timer, cues and all — and nothing is written
        down. In your own account this session would land in your diary.
      </span>
    </p>
  );
}

/** The session is over and stays over. ⚠️ It also says what to do INSTEAD, because the honest
 *  advice is to rest and keep to the planned dates rather than to train twice. */
function SessionDone() {
  return (
    <p className="ct-app__notice" role="note">
      <span>
        You have already finished this session — it is in your diary. The best thing you can do now
        is rest: the adaptation happens between sessions, so stick to the planned dates and come
        back for the next one.
      </span>
    </p>
  );
}

/** Finished, and NOT done: neither a congratulation nor a nag. It says the work is still owed
 *  and that what was logged already counts, because a restart appends rather than replaces. */
function SessionUnfinished({ unsaved }: { unsaved: boolean }) {
  return (
    <p className="ct-app__notice" role="note">
      <span>
        You finished this session with parts of it still unlogged, so it is not done yet.{' '}
        {unsaved
          ? 'Save those sets first — starting it again replaces them.'
          : 'Start it again whenever you are ready: what you logged already counts towards it.'}
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
  badge,
  marks,
  record,
  plan,
  vocabulary,
  exercises,
  run,
}: {
  session: PlanSession;
  badge: CompletionBadge | null;
  marks: BlockMarks | null;
  /** THIS session's run record, or `null` — see `offerView`. What happened beats what was
   *  planned, and with no record the parts fall back to the server's own marks. */
  record: RunRecord | null;
  plan: PlanTree | null;
  vocabulary: Vocabulary | undefined;
  exercises: ReadonlyMap<string, LibraryExercise>;
  run: SessionRun;
}) {
  const loggable = loggableSets(session);
  const total = totalSets(session);

  return (
    <section className="ct-app__card" data-completion={badge?.band}>
      <h2>
        {session.title} <span className="ct-app__badge">{formatDay(session.scheduled_on)}</span>
        {/* ⚠️ The band on the BADGE's own `data-completion`, never reached from the card's — see
            `styles/_profile.scss::&__completion` for the bug the descendant form shipped. */}
        {badge === null ? null : (
          <span className="ct-app__completion" data-completion={badge.band}>
            {badge.label}
          </span>
        )}
      </h2>
      <p className="ct-app__muted">{sessionSummary(session)}</p>
      {/* Inside the card on purpose: on a rest day the card is NEXT week's session, and a week
          number sitting above it would read as today's. */}
      <PhaseReminder plan={plan} session={session} vocabulary={vocabulary} />
      {/* Once it is over the card answers what HAPPENED instead of what was planned: the
          outcome list below already names every block and its set count. */}
      {record === null ? (
        <ul className="ct-app__terms">
          {session.blocks.map((block) => {
            // Which PART is logged, from the server's own `done_block_ids`, so a reload keeps
            // the day's work — and both channels are keyed on the row's OWN `data-done`.
            const outcome = blockOutcome(marks, block.id);
            return (
              <li className="ct-app__part" data-done={outcome ?? undefined} key={block.order_index}>
                {outcome === null ? null : (
                  <span className="ct-app__mark" data-done={outcome}>
                    {BLOCK_MARK_LABEL[outcome]}
                  </span>
                )}
                <strong>{exerciseLabel(block.exercise_key, exercises)}</strong> {block.sets.length}{' '}
                set{block.sets.length === 1 ? '' : 's'}
              </li>
            );
          })}
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
        {String(completion.blockCount)} part{completion.blockCount === 1 ? '' : 's'} fully logged.
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
