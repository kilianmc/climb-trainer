import { Link, createLazyFileRoute, useNavigate } from '@tanstack/react-router';
import { useEffect, useMemo, useRef, useState } from 'react';

import type {
  LibraryExercise,
  PlanMicrocycle,
  PlanShortfall,
  PlanTree,
  Profile,
  SessionCompletion,
  Vocabulary,
} from '../../api/types';
import { ApiError } from '../../api/client';
import { useAuth } from '../../auth/AuthProvider';
import { useLibrary } from '../../library/api';
import { humanise } from '../../library/browse';
import { IconCollapseAll, IconExpandAll } from '../../ui/icons';
import type { PhaseGuides } from '../../plan/PhaseGuide';
import { PhaseGuideNote, phaseGuides, phaseLabel } from '../../plan/PhaseGuide';
import { PhaseWeekTable } from '../../plan/PhaseWeekTable';
import { PlanTimeline } from '../../plan/PlanTimeline';
import { useActivePlanView, useCreatePlan, usePlanPreview } from '../../plan/api';
import {
  BLOCK_MARK_LABEL,
  blockOutcome,
  completionBadge,
  completionBySession,
  doneBlocks,
  phaseCompletionBadge,
  useSessionCompletion,
} from '../../plan/completion';
import {
  allPhases,
  defaultOpenPhases,
  planKey,
  readOpenPhases,
  samePhases,
  writeOpenPhases,
} from '../../plan/phaseToggles';
import {
  exerciseLabel,
  exercisesByKey,
  formatDay,
  previewBlocker,
  sessionSummary,
  setsLine,
  weekdayName,
} from '../../plan/blueprint';
import { phaseInPlan } from '../../plan/explain';
import { useProfileReset, useProfileScreen } from '../../profile/api';
import { localIsoDate } from '../../session/today';
import { compareToGoal } from '../../profile/grades';

/**
 * `/plan` — the plan this climber is on, or the one we would build, phase by phase and week by
 * week. Also a write surface: `POST /api/plans` persists a preview activated, and
 * `POST /api/profile/reset`, behind a confirmation, is "build a different plan".
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
  const create = useCreatePlan();
  // ⚠️ Issue #65's rule, and why `readOnly` is threaded rather than turned into a `disabled`
  // prop: **in demo scope the UI never OFFERS an action the principal cannot perform**, so the
  // write affordances below are absent from the tree, not greyed out. Both POSTs 403 for a demo
  // token; `GET /api/plans/active` does not, so the demo mount still reads a whole plan.
  const readOnly = useAuth().scope === 'demo';

  const preview = usePlanPreview(profile, active.plan === null);
  // Beside the plan read, never inside it (#85): only this screen wants these numbers, and
  // `GET /api/plans/active` is already the heaviest payload in the app.
  const completion = useSessionCompletion(active.plan ?? null);
  const completionBySessionId = useMemo(
    () => completionBySession(completion.data),
    [completion.data],
  );

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

  // ⚠️ The precedence: a plan the climber HAS outranks a preview, and `?? preview.data` is the
  // empty state. Nothing here offers an alternative to a running plan, so a preview is only ever
  // the *only* thing there is.
  const shown = running ?? preview.data;
  // Identity, not a flag: `shown` is one of two objects and this asks which.
  const isRunning = shown !== undefined && shown === running;

  return (
    <>
      <h1>Plan</h1>
      <GoalLine profile={profile} vocabulary={vocabulary} plan={shown} />

      {/* Skipped entirely when a plan is running: the answers behind a plan can drift after it is
          built, and a plan does not stop existing because the profile moved. */}
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
          <PlanActions plan={shown} isRunning={isRunning} create={create} readOnly={readOnly} />
          {/* ONE renderer, for both — see the top of the file. `key` is what makes the phase
              toggles below start from their own default when the plan on screen changes. */}
          <PlanBody
            key={planKey(shown)}
            plan={shown}
            exercises={exercises}
            vocabulary={vocabulary}
            completion={completionBySessionId}
          />
        </>
      )}
    </>
  );
}

/**
 * Everything the climber can DO about the plan on screen.
 *
 * ⚠️ **Demo scope: hidden, not disabled** (issue #65). `readOnly` returns `null` for the whole
 * component — a `disabled` control reads as broken software rather than as a demo, and this
 * screen's rule is absence rather than the wizard's disabled-and-explained.
 *
 * Two states: nothing running, so the plan on screen is a preview and Start persists it; and a
 * plan running, which gets one control and no prose.
 */
function PlanActions({
  plan,
  isRunning,
  create,
  readOnly,
}: {
  plan: PlanTree;
  isRunning: boolean;
  create: ReturnType<typeof useCreatePlan>;
  readOnly: boolean;
}) {
  if (readOnly) return null;

  if (isRunning) return <StartOverAction />;

  return (
    <>
      <p className="ct-app__lede">
        You don&apos;t have a plan running yet. This is the one we&apos;d build for you — start it
        and it becomes yours, week by week.
      </p>
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
          {create.isPending ? 'Starting…' : 'Start this plan'}
        </button>
      </div>
    </>
  );
}

/** ⚠️ Confirmed, awaited, and inline rather than a modal: the reset has no undo, the wizard
 *  reads the profile to pick its step, and `position: fixed` resolves against the SHELL. */
function StartOverAction() {
  const navigate = useNavigate();
  const [confirming, setConfirming] = useState(false);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  // "Has this panel ever been open?", so the first render does not steal focus from wherever the
  // router put it.
  const opened = useRef(false);
  const [failed, setFailed] = useState(false);
  const reset = useProfileReset({
    onError: () => {
      setFailed(true);
    },
    onSuccess: () => {
      setFailed(false);
    },
  });

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

  // Clears the failure with it: nothing was written, so there is no state left to report once
  // the question is off the screen.
  const dismiss = () => {
    setConfirming(false);
    setFailed(false);
  };
  const onKeyDown = (event: { key: string }) => {
    if (event.key === 'Escape') dismiss();
  };

  async function startOver() {
    try {
      await reset.mutateAsync();
    } catch {
      return;
    }
    void navigate({ to: '/onboarding' });
  }

  if (!confirming) {
    return (
      <div className="ct-app__actions">
        <button
          ref={triggerRef}
          type="button"
          className="ct-app__button"
          onClick={() => {
            setConfirming(true);
          }}
        >
          Build a different plan
        </button>
      </div>
    );
  }

  return (
    <div className="ct-app__card ct-app__card--danger" role="group" aria-labelledby="ct-startover">
      <h3 id="ct-startover">Build a different plan?</h3>
      <p>
        This clears your setup answers — the grade you climb now, the grade you&apos;re aiming at,
        your training days, your strength and weakness, and anything you&apos;ve flagged as hurting
        — and walks you through setup again from step one. There is no undo.
      </p>
      <p>
        This plan keeps running until you start the new one, and everything you&apos;ve already
        logged stays in your diary either way.
      </p>
      {/* ⚠️ Inside the panel: closing it to show a message would make them walk the
          confirmation again for a write that never happened. */}
      {failed ? (
        <p className="ct-app__error" role="alert">
          Your setup answers could not be cleared, so nothing has changed: your plan and your
          profile are both exactly as they were. Try again.
        </p>
      ) : null}
      <div className="ct-app__actions">
        <button
          ref={confirmRef}
          type="button"
          className="ct-app__button"
          disabled={reset.isPending}
          onKeyDown={onKeyDown}
          onClick={() => void startOver()}
        >
          {reset.isPending ? 'Clearing…' : 'Yes, set up again'}
        </button>
        <button
          type="button"
          className="ct-app__button ct-app__button--primary"
          onKeyDown={onKeyDown}
          onClick={dismiss}
        >
          Keep my answers
        </button>
      </div>
    </div>
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

/** One id scheme, so the timeline and the phase sections cannot disagree about a target. */
function phaseAnchorId(startWeek: number): string {
  return `ct-phase-${String(startWeek)}`;
}

function PlanBody({
  plan,
  exercises,
  vocabulary,
  completion,
}: {
  plan: PlanTree;
  exercises: readonly LibraryExercise[];
  vocabulary: Vocabulary;
  completion: ReadonlyMap<number, SessionCompletion>;
}) {
  // ONCE, for the whole plan — both of them. A 32-week plan is sixteen mesocycles over seven
  // phases, so the guide is indexed rather than searched per section.
  const index = exercisesByKey(exercises);
  const guides = phaseGuides(vocabulary);

  const storageKey = planKey(plan);
  // ONE clock read for the whole body, so the phase badges and the default-open block agree.
  const todayIso = localIsoDate(new Date());

  // The stored preference first, then the block the climber is standing in. Read once: this
  // component is keyed by `planKey`, so another plan is another mount.
  const [open, setOpen] = useState<readonly number[]>(
    () => readOpenPhases(storageKey) ?? defaultOpenPhases(plan, todayIso),
  );

  // Persisted on the change, not in an effect — one writer, and nothing to run on mount. The
  // no-op guard is what absorbs the `toggle` event React fires when it sets `open` itself.
  const commit = (next: readonly number[]) => {
    if (samePhases(open, next)) return;
    setOpen(next);
    writeOpenPhases(storageKey, next);
  };

  // ⚠️ EXPAND BEFORE SCROLL, and a FRESH OBJECT per click so the same phase can be jumped to
  // twice — CLAUDE.md "The plan timeline is measured in DAYS" carries the order and its reason.
  const [jump, setJump] = useState<{ readonly startWeek: number } | null>(null);

  const showPhase = (startWeek: number) => {
    commit([...new Set([...open, startWeek])]);
    setJump({ startWeek });
  };

  useEffect(() => {
    if (jump === null) return;
    const node = document.getElementById(phaseAnchorId(jump.startWeek));
    if (node === null) return;
    // Reduced motion covers programmatic scrolling too, exactly as `profile.lazy.tsx` has it.
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    node.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'start' });
    // Focus LAST, and with `preventScroll`: scrolling alone leaves a keyboard user behind, and
    // focusing without it would undo the scroll just asked for.
    node.querySelector('summary')?.focus({ preventScroll: true });
  }, [jump]);

  return (
    <>
      {plan.notes.map((note) => (
        <p className="ct-app__notice" role="note" key={note.kind}>
          <span>{note.message}</span>
        </p>
      ))}

      <PlanTimeline plan={plan} guides={guides} todayIso={todayIso} onSelect={showPhase} />

      {/* Fourteen sections at 28 weeks, so both directions are one tap rather than fourteen.
          ⚠️ Icons at EVERY width, so the nav's container-range machinery does not apply here. */}
      <div className="ct-app__actions">
        <button
          type="button"
          className="ct-app__button ct-app__button--icon"
          aria-label="Expand all phases"
          title="Expand all phases"
          onClick={() => {
            commit(allPhases(plan));
          }}
        >
          <IconExpandAll />
        </button>
        <button
          type="button"
          className="ct-app__button ct-app__button--icon"
          aria-label="Collapse all phases"
          title="Collapse all phases"
          onClick={() => {
            commit([]);
          }}
        >
          <IconCollapseAll />
        </button>
      </div>

      {plan.mesocycles.map((mesocycle) => {
        const guide = guides.get(mesocycle.phase);
        const phaseBadge = phaseCompletionBadge(mesocycle, completion, todayIso);
        return (
          <section key={mesocycle.start_week} id={phaseAnchorId(mesocycle.start_week)}>
            {/* `<details>`, not a custom toggle: keyboard, focus and the expanded state come
                from the element. The heading stays the control's own label. */}
            <details
              className="ct-app__disclosure ct-app__disclosure--phase"
              data-completion={phaseBadge?.band}
              open={open.includes(mesocycle.start_week)}
              onToggle={(event) => {
                const isOpen = event.currentTarget.open;
                commit(
                  isOpen
                    ? [...new Set([...open, mesocycle.start_week])]
                    : open.filter((week) => week !== mesocycle.start_week),
                );
              }}
            >
              <summary>
                <h2 className="ct-app__titlerow">
                  {phaseLabel(guides, mesocycle.phase)}{' '}
                  <span className="ct-app__badge">
                    {mesocycle.start_week === mesocycle.end_week
                      ? `Week ${String(mesocycle.start_week)}`
                      : `Weeks ${String(mesocycle.start_week)}–${String(mesocycle.end_week)}`}
                  </span>
                </h2>
                {/* In the SUMMARY, so a COLLAPSED phase still carries its own result (#92). A
                    sibling of the heading, not inside it: the summary is the flex row. */}
                {phaseBadge === null ? null : (
                  /* Band AND `--phase` live on the BADGE: a phase and a session are both
                     `ct-app__disclosure`, and only dark's PHASE badge gets a pill. */
                  <span
                    className="ct-app__completion ct-app__completion--phase"
                    data-completion={phaseBadge.band}
                  >
                    {phaseBadge.label}
                  </span>
                )}
              </summary>
              <PhaseGuideNote guide={guide} inPlan={phaseInPlan(plan, mesocycle.phase)} />
              <PhaseWeekTable mesocycle={mesocycle} />
              <ul className="ct-app__stack">
                {mesocycle.microcycles.map((microcycle) => (
                  <WeekCard
                    key={microcycle.week_no}
                    microcycle={microcycle}
                    index={index}
                    guides={guides}
                    completion={completion}
                  />
                ))}
              </ul>
            </details>
          </section>
        );
      })}

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

/**
 * One week: its sessions, each behind a disclosure so a 32-week plan is readable without scrolling
 * past a few thousand prescribed sets. `week_no` is plan-global (1..`week_count`), not per
 * mesocycle, so it is unique across the screen and is the key.
 */
function WeekCard({
  microcycle,
  index,
  guides,
  completion,
}: {
  microcycle: PlanMicrocycle;
  index: ReadonlyMap<string, LibraryExercise>;
  guides: PhaseGuides;
  completion: ReadonlyMap<number, SessionCompletion>;
}) {
  return (
    <li className="ct-app__card">
      <h3 className="ct-app__titlerow">
        Week {String(microcycle.week_no)}{' '}
        <span className="ct-app__badge">{phaseLabel(guides, microcycle.phase)}</span>
      </h3>
      <p className="ct-app__muted">Starts {formatDay(microcycle.start_date)}</p>

      {microcycle.sessions.map((session) => {
        // Nothing for a preview (no row, so no id) and nothing for a session still to come.
        const done = session.id == null ? undefined : completion.get(session.id);
        const badge = completionBadge(done);
        // `null` for a preview and for a session still to come, which leaves its rows unmarked.
        const marks = doneBlocks(done);
        return (
          <details
            className="ct-app__disclosure"
            key={session.weekday}
            data-completion={badge?.band}
          >
            <summary>
              {weekdayName(session.weekday)} — {session.title}
              {/* The percentage in WORDS beside the colour, never the colour alone — and the
                  band on the badge itself, so no enclosing phase can repaint it. */}
              {badge === null ? null : (
                <span className="ct-app__completion" data-completion={badge.band}>
                  {badge.label}
                </span>
              )}
            </summary>
            <p className="ct-app__muted">{sessionSummary(session)}</p>

            {session.blocks.length > 0 && (
              <ul className="ct-app__terms">
                {session.blocks.map((block) => {
                  // Which PART got done (#95). Both the word and the row's edge are keyed on the
                  // row's OWN `data-done`, so no enclosing phase or session can repaint it.
                  const outcome = blockOutcome(marks, block.id);
                  return (
                    <li
                      className="ct-app__part"
                      data-done={outcome ?? undefined}
                      key={block.order_index}
                    >
                      {outcome === null ? null : (
                        <span className="ct-app__mark" data-done={outcome}>
                          {BLOCK_MARK_LABEL[outcome]}
                        </span>
                      )}
                      <strong>{exerciseLabel(block.exercise_key, index)}</strong>{' '}
                      {humanise(block.aspect_key)} · {setsLine(block, microcycle.phase)}
                      {block.shortfall !== null && <ShortfallNotice shortfall={block.shortfall} />}
                    </li>
                  );
                })}
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
        );
      })}
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
