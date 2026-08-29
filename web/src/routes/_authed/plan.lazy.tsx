import { Link, createLazyFileRoute } from '@tanstack/react-router';
import { useEffect, useRef, useState } from 'react';

import type {
  LibraryExercise,
  PlanMesocycle,
  PlanMicrocycle,
  PlanShortfall,
  PlanTree,
  Profile,
  Vocabulary,
} from '../../api/types';
import { ApiError } from '../../api/client';
import { useAuth } from '../../auth/AuthProvider';
import { useLibrary } from '../../library/api';
import { humanise } from '../../library/browse';
import { useAbandonPlan, useActivePlanView, useCreatePlan, usePlanPreview } from '../../plan/api';
import {
  exerciseLabel,
  exercisesByKey,
  formatDay,
  previewBlocker,
  sessionSummary,
  setsLine,
  weekdayName,
} from '../../plan/blueprint';
import { useProfileScreen } from '../../profile/api';
import { compareToGoal } from '../../profile/grades';

/**
 * `/plan` — the plan this climber is on, or the one we would build, phase by phase and week by
 * week. Also a write surface: `POST /api/plans` persists a preview activated, and
 * `POST /api/plans/{id}/abandon` stands it down.
 *
 * ⚠️ **ONE RENDERER, because a preview and a persisted plan are the SAME SHAPE.** `PlanBody`
 * takes a `PlanTree` without caring which route produced it; the only difference is which
 * nullable fields are filled (a preview is not a row, so every `id`, plus a block's
 * `exercise_id`, a session's `status` and the plan's `activated_at`, is `null`). **Do not fork
 * this into a preview renderer and an active-plan renderer.** What the plan *is* — offered or
 * running — is said once, above the body, by the affordances.
 *
 * **Four reads, and the order between two of them is a compute decision.** `useProfileScreen`
 * gives the profile and the vocabulary; `useLibrary` turns a block's `exercise_key` into a name;
 * `useActivePlanView` says what the climber has. `usePlanPreview` is **held off** until the
 * active read says there is nothing running or the climber asks for an alternative — generating
 * 32 weeks is the most expensive read in the app. See `plan/api.ts`.
 *
 * ⚠️ **`ProfileFallback` is deliberately NOT reused.** Its props name two reads; this screen has
 * four, and each of the extra two failing means something else ("we could not name your
 * exercises", "we could not check whether you already have a plan") — a different sentence and a
 * different retry. Widening its props to a list would make it say less on both screens.
 *
 * **Performance is a real constraint**, so the exercise index is built **once** and passed down,
 * a block renders one line for all its sets (`setsLine`), and nothing sorts or filters inside a
 * loop. No virtualisation and no pagination — but nothing here is per-set either.
 */
function Plan() {
  const { profile, vocabulary, profileFailed, vocabularyFailed, retry } = useProfileScreen();
  const library = useLibrary();
  const active = useActivePlanView();
  // Whether the climber has asked to see an alternative to the plan they are already on. Off by
  // default, because that is what keeps the expensive read unmade — see `usePlanPreview`.
  const [replacing, setReplacing] = useState(false);
  // ⚠️ A committed Start ENDS the replacement flow: `shown` prefers the proposal while
  // `replacing` is true, so without this the screen would keep offering "Start this instead" for
  // the plan that had just become the running one. Attached to the mutation, not to
  // `mutate(vars, {…})` — see `plan/api.ts`.
  const create = useCreatePlan({
    onSuccess: () => {
      setReplacing(false);
    },
  });
  const abandon = useAbandonPlan();
  // ⚠️ Issue #65's rule, and why `readOnly` is threaded rather than turned into a `disabled`
  // prop: **in demo scope the UI never OFFERS an action the principal cannot perform**, so the
  // write affordances below are absent from the tree, not greyed out. Both POSTs 403 for a demo
  // token; `GET /api/plans/active` does not, so the demo mount still reads a whole plan.
  const readOnly = useAuth().scope === 'demo';

  // ⚠️ `active.plan` here is the OVERLAID value, so an abandon in flight starts generating the
  // plan we will offer next — the climber who just abandoned wants a replacement. Cost of being
  // wrong is bounded: one wasted generation if the abandon then fails.
  const preview = usePlanPreview(profile, active.plan === null || replacing);

  const exercises = library.data?.exercises;

  // ⚠️ Gated on "there is nothing to show", NEVER on `isError`: query-core's error reducer sets
  // `status: "error"` even with data present, so a failed background refetch must not replace a
  // rendered plan. `isLoadingError` is `isError && !hasData` — see `profile/api.ts:174-189`.
  // ⚠️ `active.plan === undefined` is the first read not having landed, and nothing can be decided
  // without it. `active.plan === null` is NOT here: that is "no plan yet", a normal screen with a
  // Start button, and a 200 from the server.
  if (
    profile === undefined ||
    vocabulary === undefined ||
    exercises === undefined ||
    active.plan === undefined
  ) {
    const failed =
      profileFailed || vocabularyFailed || library.isLoadingError || active.isLoadingError;
    return (
      <>
        <h1>Plan</h1>
        {failed ? (
          <>
            <p className="ct-app__status ct-app__status--error" role="alert">
              {/* Four reads, four sentences: naming the wrong one sends the reader looking in
                  the wrong place. */}
              {profileFailed
                ? 'Your profile could not be loaded, so there is nothing to build a plan from.'
                : vocabularyFailed
                  ? 'The grade lists could not be loaded.'
                  : library.isLoadingError
                    ? 'The exercise library could not be loaded, so the plan has no exercises to name.'
                    : 'We could not check whether you already have a plan running, so nothing is shown rather than the wrong thing.'}
            </p>
            <div className="ct-app__actions">
              <button
                type="button"
                className="ct-app__button ct-app__button--primary"
                onClick={() => {
                  // Only what failed. Each of the four is cached, so refetching a healthy one
                  // because its neighbour broke is a wasted Neon wake.
                  retry();
                  if (library.isLoadingError) void library.refetch();
                  if (active.isLoadingError) active.retry();
                }}
              >
                Try again
              </button>
            </div>
          </>
        ) : (
          <p className="ct-app__status">Loading your plan…</p>
        )}
      </>
    );
  }

  const blocker = previewBlocker(profile);
  const running = active.plan;

  // ⚠️ The precedence: a plan the climber HAS outranks a preview, and while they are looking at
  // an alternative the alternative outranks the plan. The last `?? preview.data` is the empty
  // state. Note what does NOT happen — asking for an alternative never takes the running plan off
  // the screen, because `shown` falls back to `running` while the generator works or fails.
  const proposed = replacing ? preview.data : undefined;
  const shown = proposed ?? running ?? preview.data;
  // Identity, not a flag: `shown` is one of two objects and this asks which.
  const isRunning = shown !== undefined && shown === running;

  return (
    <>
      <h1>Plan</h1>
      <GoalLine profile={profile} vocabulary={vocabulary} plan={shown} />

      {/* Skipped entirely when a plan is running: the answers behind a plan can drift after it is
          built, and a plan does not stop existing because the profile moved. Regenerating is what
          needs a plannable profile, and `PlanActions` gates on the same `blocker`. */}
      {blocker !== null && running === null ? (
        readOnly ? (
          <DemoUnplannable />
        ) : (
          // Never a disabled control: the sentence says what is missing and the link goes to the
          // step that fixes it. `previewBlocker` is also what keeps the query disabled, so this
          // branch costs no request.
          <>
            <p className="ct-app__notice" role="note">
              <span>{blocker.message}</span>
            </p>
            <div className="ct-app__actions">
              {blocker.fix === '/profile' ? (
                <Link className="ct-app__button ct-app__button--primary" to="/profile">
                  Edit your profile
                </Link>
              ) : (
                <Link className="ct-app__button ct-app__button--primary" to="/onboarding">
                  Continue setup
                </Link>
              )}
            </div>
          </>
        )
      ) : shown === undefined ? (
        <PreviewPending preview={preview} readOnly={readOnly} />
      ) : (
        <>
          <PlanActions
            plan={shown}
            isRunning={isRunning}
            hasRunningPlan={running !== null}
            replacing={replacing}
            canReplace={blocker === null}
            onReplace={() => {
              setReplacing(true);
            }}
            onKeep={() => {
              setReplacing(false);
            }}
            preview={preview}
            create={create}
            abandon={abandon}
            readOnly={readOnly}
          />
          {/* ONE renderer, for both — see the top of the file. */}
          <PlanBody plan={shown} exercises={exercises} />
        </>
      )}
    </>
  );
}

/**
 * Everything the climber can DO about the plan on screen, and the sentences that say what each
 * action means before it is taken.
 *
 * ⚠️ **Demo scope: hidden, not disabled** (issue #65). `readOnly` returns `null` for the whole
 * component, plus one sentence saying why — a Start button that is merely absent looks like a
 * missing feature, and a `disabled` one reads as broken software rather than as a demo.
 *
 * Three states: nothing running (Start); a plan running (Abandon behind a confirmation, plus an
 * offer to build something else, with the consequence of the *second* click stated before the
 * first); and a plan running with an alternative on screen (Start, which replaces, or keep). The
 * replacement is one server transaction, so there is no window where the climber has no plan.
 */
function PlanActions({
  plan,
  isRunning,
  hasRunningPlan,
  replacing,
  canReplace,
  onReplace,
  onKeep,
  preview,
  create,
  abandon,
  readOnly,
}: {
  plan: PlanTree;
  isRunning: boolean;
  hasRunningPlan: boolean;
  replacing: boolean;
  canReplace: boolean;
  onReplace: () => void;
  onKeep: () => void;
  preview: ReturnType<typeof usePlanPreview>;
  create: ReturnType<typeof useCreatePlan>;
  abandon: ReturnType<typeof useAbandonPlan>;
  readOnly: boolean;
}) {
  if (readOnly) {
    return (
      <p className="ct-app__notice" role="note">
        <span>
          This is a real plan, built from the demo climber&apos;s answers, and you can read all of
          it. The demo account is read-only, so it cannot be started — in your own account this is
          where you&apos;d begin it.
        </span>
      </p>
    );
  }

  if (isRunning) {
    // Non-null on every persisted plan — the point of `POST /api/plans` returning the tree with
    // ids. No id means no button, rather than a request to `/api/plans/null/abandon`.
    const planId = plan.id;
    return (
      <>
        <p className="ct-app__lede">
          <span className="ct-app__badge">Your plan</span> This is the plan you&apos;re on. Sessions
          and weeks are yours to follow — nothing here expires.
        </p>
        {replacing ? <ReplacementPending preview={preview} onKeep={onKeep} /> : null}
        {!replacing && canReplace ? (
          <>
            <p className="ct-app__notice" role="note">
              <span>
                Building a different plan doesn&apos;t touch this one. Starting the new one does:
                that stands this plan down in the same step, and the weeks you&apos;ve already
                logged stay in your diary either way.
              </span>
            </p>
            <div className="ct-app__actions">
              <button type="button" className="ct-app__button" onClick={onReplace}>
                Build a different plan
              </button>
            </div>
          </>
        ) : null}
        {planId === null || planId === undefined ? null : (
          <AbandonAction planId={planId} abandon={abandon} />
        )}
      </>
    );
  }

  return (
    <>
      {hasRunningPlan ? (
        <p className="ct-app__notice" role="note">
          <span>
            This is a new plan, and nothing has been saved. Starting it stands your current plan
            down in the same step — one action, and you are never left without a plan.
          </span>
        </p>
      ) : (
        <p className="ct-app__lede">
          You don&apos;t have a plan running yet. This is the one we&apos;d build for you — start it
          and it becomes yours, week by week.
        </p>
      )}
      {create.isError ? <CreateFailure error={create.error} /> : null}
      <div className="ct-app__actions">
        <button
          type="button"
          className="ct-app__button ct-app__button--primary"
          // Busy, not optimistic: fabricating a plan tree is what the "cache holds server
          // responses only" rule forbids. See `plan/api.ts::useActivePlanView`.
          disabled={create.isPending}
          onClick={() => {
            // ⚠️ The plan's OWN `start_date`, not today's Monday recomputed. Both routes
            // normalise identically, so echoing what the preview showed is what guarantees the
            // saved plan starts on the day on screen — a tab left open across midnight would
            // otherwise persist a plan a week out.
            create.mutate(plan.start_date);
          }}
        >
          {create.isPending
            ? 'Starting…'
            : hasRunningPlan
              ? 'Start this instead'
              : 'Start this plan'}
        </button>
        {hasRunningPlan ? (
          <button type="button" className="ct-app__button" onClick={onKeep}>
            Keep my current plan
          </button>
        ) : null}
      </div>
    </>
  );
}

/**
 * Why a Start did not land — and it must not claim that nothing was saved.
 *
 * ⚠️ **Never say "nothing was saved".** That copy shipped and was false in the expensive case:
 * `create_plan` serialises before `commit()`, so it holds for almost every failure but not for
 * one at or after the commit (a dropped socket, or the function killed mid-response). Then the
 * new plan IS active and the old one IS abandoned, and the sentence asserted the opposite for up
 * to `ACTIVE_PLAN_STALE_TIME_MS` with `refetchOnWindowFocus` off app-wide.
 *
 * ⚠️ **The fix is the copy, NOT the data flow.** An `onError` refetch here is precisely the PR #9
 * bug this file refuses to reintroduce, and it buys nothing a reload does not. So this says what
 * is known (the write did not confirm), never what is not (whether it landed).
 *
 * **The 422 is a stale TAB and gets its own sentence.** `_START_DATE_BACKDATE_DAYS` is 7 and the
 * client sends the `start_date` the preview showed, so a page open longer than that posts a date
 * the server refuses. No auto-reload: a plan screen that reloads itself under someone reading it
 * is worse than a sentence.
 */
function CreateFailure({ error }: { error: unknown }) {
  const stale = error instanceof ApiError && error.status === 422;
  return (
    <p className="ct-app__error" role="alert">
      {stale
        ? 'This page has been open too long to start the plan it is showing. Reload it and start the fresh one.'
        : 'Something interrupted that, and we can’t tell whether it saved. Reload the page to see which plan you’re on.'}
    </p>
  );
}

/**
 * An alternative was asked for and has not arrived. The running plan is still below this — see
 * `shown` in `Plan`. Gated on `isLoadingError`, not `isError`: a failed generation must not take
 * a plan the climber is reading off the screen.
 */
function ReplacementPending({
  preview,
  onKeep,
}: {
  preview: ReturnType<typeof usePlanPreview>;
  onKeep: () => void;
}) {
  const failed = preview.isLoadingError;
  return (
    <>
      <p
        className={failed ? 'ct-app__error' : 'ct-app__status'}
        role={failed ? 'alert' : undefined}
      >
        {failed
          ? 'A different plan could not be built just now. Your current plan is untouched.'
          : 'Building a different plan…'}
      </p>
      <div className="ct-app__actions">
        {failed ? (
          <button
            type="button"
            className="ct-app__button ct-app__button--primary"
            onClick={() => void preview.refetch()}
          >
            Try again
          </button>
        ) : null}
        <button type="button" className="ct-app__button" onClick={onKeep}>
          Keep my current plan
        </button>
      </div>
    </>
  );
}

/**
 * Abandon, behind a real confirmation.
 *
 * **Not `window.confirm`**: unstyleable, blocks the main thread, suppressible, and its text
 * cannot say that the logged work survives — which is the sentence this confirmation exists for.
 *
 * **An inline panel rather than a modal**, because a modal needs a focus trap, a scroll lock and
 * an inert background, and `position: fixed` and `inert` resolve against kilianmc.com's document
 * in the federated mount. An inline panel also keeps the plan being abandoned visible behind the
 * question.
 *
 * The accessible pattern, deliberately not skipped:
 *
 * - `role="group"` + `aria-labelledby` on the panel's own heading, so the question is its
 *   accessible name.
 * - **Focus moves to the confirming button** on open and back to the trigger on close. The
 *   trigger is remounted by the same render that unmounts the panel, and effects run after
 *   commit, so its ref is populated by the time the effect reads it.
 * - **Escape dismisses**, with the handler on the two buttons rather than the panel: focus can
 *   only be on one of them, and a `keydown` on a non-interactive container is what
 *   `jsx-a11y/no-noninteractive-element-interactions` exists to refuse.
 * - The safe choice carries the visual weight (`--primary`); the destructive one does not.
 */
function AbandonAction({
  planId,
  abandon,
}: {
  planId: number;
  abandon: ReturnType<typeof useAbandonPlan>;
}) {
  const [confirming, setConfirming] = useState(false);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  // "Has this panel ever been open?", so the first render does not steal focus from wherever the
  // router put it.
  const opened = useRef(false);

  useEffect(() => {
    if (confirming) {
      opened.current = true;
      confirmRef.current?.focus();
      return;
    }
    if (opened.current) {
      opened.current = false;
      triggerRef.current?.focus();
    }
  }, [confirming]);

  const dismiss = () => {
    setConfirming(false);
  };
  const onKeyDown = (event: { key: string }) => {
    if (event.key === 'Escape') dismiss();
  };

  if (!confirming) {
    return (
      <>
        {abandon.isError ? (
          <p className="ct-app__error" role="alert">
            Your plan could not be stood down, so it has not been: it is still yours and still
            active. Try again.
          </p>
        ) : null}
        <div className="ct-app__actions">
          <button
            ref={triggerRef}
            type="button"
            className="ct-app__button"
            onClick={() => {
              setConfirming(true);
            }}
          >
            Abandon this plan
          </button>
        </div>
      </>
    );
  }

  return (
    <div
      className="ct-app__card ct-app__card--danger"
      role="group"
      aria-labelledby="ct-abandon-question"
    >
      <h3 id="ct-abandon-question">Abandon this plan?</h3>
      <p>
        It stops being your plan and you&apos;ll have none until you start another. Everything
        you&apos;ve already logged against it stays in your diary — abandoning marks the plan, it
        never deletes it.
      </p>
      <div className="ct-app__actions">
        <button
          ref={confirmRef}
          type="button"
          className="ct-app__button"
          onKeyDown={onKeyDown}
          onClick={() => {
            abandon.mutate(planId);
          }}
        >
          Yes, abandon it
        </button>
        <button
          type="button"
          className="ct-app__button ct-app__button--primary"
          onKeyDown={onKeyDown}
          onClick={dismiss}
        >
          Keep this plan
        </button>
      </div>
    </div>
  );
}

/**
 * Current grade against the goal, from the profile rather than the plan, so it is on screen before
 * the preview lands. `compareToGoal` returns `null` when the question cannot be asked (one grade
 * missing, or the two on different ladders), and then the line is simply absent.
 */
function GoalLine({
  profile,
  vocabulary,
  plan,
}: {
  profile: Profile;
  vocabulary: Vocabulary;
  plan: PlanTree | undefined;
}) {
  const label = (id: number | null) =>
    id === null ? null : (vocabulary.grades.find((grade) => grade.id === id)?.label ?? null);
  const current = label(profile.current_grade_id);
  const target = label(profile.target_grade_id);
  const standing = compareToGoal(vocabulary, profile.current_grade_id, profile.target_grade_id);

  if (current === null || target === null || standing === null) return null;

  return (
    <p className="ct-app__lede">
      {current} now, {target} the goal
      {standing === 'above'
        ? ' — already past it, so this is a consolidation block.'
        : standing === 'equal'
          ? ' — you are there, so this consolidates it.'
          : '.'}
      {plan === undefined
        ? ''
        : ` ${String(plan.week_count)} weeks from ${formatDay(plan.start_date)}.`}
    </p>
  );
}

/** Waiting for, or refused by, the endpoint. The header above it is already on screen. */
function PreviewPending({
  preview,
  readOnly,
}: {
  preview: ReturnType<typeof usePlanPreview>;
  readOnly: boolean;
}) {
  if (!preview.isLoadingError) return <p className="ct-app__status">Building your plan…</p>;

  // A 422 is the server's own refusal sentence for stored state the client could not see (today,
  // only cross-discipline grades). Rendered verbatim because it already says what to do.
  const error = preview.error;
  const refusal = error instanceof ApiError && error.status === 422 ? error.message : null;

  // A refusal names an answer only a real account can change, so a retry cannot help: in demo
  // scope it gets the explanation instead of a button. A genuine fault below still offers a retry.
  if (refusal !== null && readOnly) return <DemoUnplannable />;

  return (
    <>
      <p className="ct-app__status ct-app__status--error" role="alert">
        {refusal ?? 'Your plan could not be built just now. Nothing has been saved either way.'}
      </p>
      <div className="ct-app__actions">
        <button
          type="button"
          className="ct-app__button ct-app__button--primary"
          onClick={() => void preview.refetch()}
        >
          Try again
        </button>
      </div>
    </>
  );
}

/**
 * Every refusal, in demo scope. A demo principal is read-only at the database level, so the
 * profile editor the other arm links to is a dead end. No link, no button, and deliberately no
 * disabled control either: this screen never offers the demo mount an action it cannot take.
 */
function DemoUnplannable() {
  return (
    <p className="ct-app__notice" role="note">
      <span>
        The demo account is read-only, so the answers a plan is built from cannot be filled in here.
        In your own account this is where your grades and training days go, and the plan is built
        from them.
      </span>
    </p>
  );
}

function PlanBody({ plan, exercises }: { plan: PlanTree; exercises: readonly LibraryExercise[] }) {
  // ONCE, for the whole plan.
  const index = exercisesByKey(exercises);

  return (
    <>
      <p className="ct-app__muted">
        {plan.name} · generator {plan.generator_version}
      </p>

      {plan.notes.map((note) => (
        <p className="ct-app__notice" role="note" key={note.kind}>
          <span>{note.message}</span>
        </p>
      ))}

      <PhaseTimeline mesocycles={plan.mesocycles} />

      {plan.mesocycles.map((mesocycle) => (
        <section key={mesocycle.start_week}>
          <h2>
            {humanise(mesocycle.phase)}{' '}
            <span className="ct-app__badge">
              {mesocycle.start_week === mesocycle.end_week
                ? `Week ${String(mesocycle.start_week)}`
                : `Weeks ${String(mesocycle.start_week)}–${String(mesocycle.end_week)}`}
            </span>
          </h2>
          <ul className="ct-app__stack">
            {mesocycle.microcycles.map((microcycle) => (
              <WeekCard key={microcycle.week_no} microcycle={microcycle} index={index} />
            ))}
          </ul>
        </section>
      ))}

      {plan.shortfalls.length > 0 && (
        <section>
          <h2>What you&apos;d need</h2>
          <p className="ct-app__muted">
            Every session above is complete. These are the qualities the plan could not train with
            what we assume you have — nothing here is blocking anything.
          </p>
          <ul className="ct-app__stack">
            {plan.shortfalls.map((shortfall) => (
              <li className="ct-app__card" key={`${shortfall.phase}:${shortfall.aspect_key}`}>
                <h3>
                  {humanise(shortfall.aspect_key)}{' '}
                  <span className="ct-app__badge">{humanise(shortfall.phase)}</span>
                </h3>
                <ShortfallNotice shortfall={shortfall} />
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}

/** The phases in order, one badge per mesocycle — a phase block plus its deload, taper last. */
function PhaseTimeline({ mesocycles }: { mesocycles: readonly PlanMesocycle[] }) {
  return (
    <p className="ct-app__tags">
      {mesocycles.map((mesocycle) => (
        <span className="ct-app__badge" key={mesocycle.start_week}>
          {humanise(mesocycle.phase)} · wk {String(mesocycle.start_week)}
          {mesocycle.start_week === mesocycle.end_week ? '' : `–${String(mesocycle.end_week)}`}
        </span>
      ))}
    </p>
  );
}

/**
 * One week: its sessions, each behind a disclosure so a 32-week plan is readable without scrolling
 * past a few thousand prescribed sets. `week_no` is plan-global (1..`week_count`), not per
 * mesocycle, so it is unique across the screen and is the key.
 */
function WeekCard({
  microcycle,
  index,
}: {
  microcycle: PlanMicrocycle;
  index: ReadonlyMap<string, LibraryExercise>;
}) {
  return (
    <li className="ct-app__card">
      <h3>
        Week {String(microcycle.week_no)}{' '}
        <span className="ct-app__badge">{humanise(microcycle.phase)}</span>
      </h3>
      <p className="ct-app__muted">Starts {formatDay(microcycle.start_date)}</p>

      {microcycle.sessions.map((session) => (
        <details className="ct-app__disclosure" key={session.weekday}>
          <summary>
            {weekdayName(session.weekday)} — {session.title}
          </summary>
          <p className="ct-app__muted">{sessionSummary(session)}</p>

          {session.blocks.length > 0 && (
            <ul className="ct-app__terms">
              {session.blocks.map((block) => (
                <li key={block.order_index}>
                  <strong>{exerciseLabel(block.exercise_key, index)}</strong>{' '}
                  {humanise(block.aspect_key)} · {setsLine(block, microcycle.phase)}
                  {block.shortfall !== null && <ShortfallNotice shortfall={block.shortfall} />}
                </li>
              ))}
            </ul>
          )}

          {/* A session-level shortfall is either the honest empty session or a session with
              no wall time in it (issue #84) — the plan is complete either way. */}
          {session.shortfalls.map((shortfall) => (
            <ShortfallNotice
              shortfall={shortfall}
              key={`${shortfall.phase}:${shortfall.aspect_key}`}
            />
          ))}
        </details>
      ))}
    </li>
  );
}

/**
 * ⚠️ **The server's wording, verbatim.** `server/domain/planner/selection.py::shortfall_message`
 * assembles it and is guarded there against suggesting an improvised finger edge; re-wording it
 * client-side would put that guard behind a second copy nothing checks. A shortfall is a note —
 * it never disables anything.
 *
 * ⚠️ **`shortfall.aspect_key` is the aspect the generator WANTED and could not fill; on a block it
 * is NOT the block's own `aspect_key`.** That is why this renders the message and nothing else.
 * Do not add `humanise(shortfall.aspect_key)` here.
 */
function ShortfallNotice({ shortfall }: { shortfall: PlanShortfall }) {
  return (
    <p className="ct-app__notice" role="note">
      <span>{shortfall.message}</span>
    </p>
  );
}

export const Route = createLazyFileRoute('/_authed/plan')({ component: Plan });
