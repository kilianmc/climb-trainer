import { Link, createLazyFileRoute } from '@tanstack/react-router';

import type {
  LibraryExercise,
  PlanMesocycle,
  PlanMicrocycle,
  PlanPreview,
  PlanShortfall,
  Profile,
  Vocabulary,
} from '../../api/types';
import { ApiError } from '../../api/client';
import { useAuth } from '../../auth/AuthProvider';
import { useLibrary } from '../../library/api';
import { humanise } from '../../library/browse';
import { usePlanPreview } from '../../plan/api';
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
 * `/plan` — the plan the generator would build for this climber, phase by phase and week by
 * week. Nothing on this screen writes: `POST /api/plans/preview` persists no row, and issue #62
 * / PR #11b is what turns a preview into a plan.
 *
 * **Four reads, three of them shared with screens that already existed.** `useProfileScreen`
 * gives the profile (which decides whether a plan can be asked for at all) and the vocabulary
 * (grade labels, and `compareToGoal` for the goal line); `useLibrary` turns a block's
 * `exercise_key` into a name. Only `usePlanPreview` is new. All three reads are
 * `enabled: isAuthenticated` and cached, so arriving here costs at most one request each per
 * session.
 *
 * **⚠️ `ProfileFallback` is deliberately NOT reused, and this is not an oversight to tidy up
 * later.** Its props are `profileFailed` / `vocabularyFailed` and its copy names two reads; this
 * screen has three, and the third failing means "we could not name your exercises", which is a
 * different sentence and a different retry. Widening those props to a list would make the
 * component say less on both screens than each says now. If you are here to "simplify" this into
 * `ProfileFallback`, that is the argument you have to beat.
 *
 * **Performance is a real constraint here, measured rather than assumed.** The worst-case
 * response is 583 KiB of JSON carrying 2,421 prescribed sets across 32 weeks (the demo's
 * 16-week plan is 124.6 KiB / 507). So the exercise index is built **once** and passed down, a
 * block renders **one line for all of its sets** (`setsLine`), and nothing sorts or filters
 * inside a loop. There is deliberately no virtualisation and no pagination — that is not this
 * PR — but nothing here is per-set either.
 */
function Plan() {
  const { profile, vocabulary, profileFailed, vocabularyFailed, retry } = useProfileScreen();
  const library = useLibrary();
  const preview = usePlanPreview(profile);
  // A demo token is read-only at the database level, so every "go and finish your profile"
  // affordance on this screen is a lie in demo scope. Same idiom as `onboarding.lazy.tsx`.
  const readOnly = useAuth().scope === 'demo';

  const exercises = library.data?.exercises;

  // ⚠️ Gated on "there is nothing to show", NEVER on `isError`: query-core's error reducer sets
  // `status: "error"` even with data present, so a failed background refetch must not replace a
  // rendered plan. `isLoadingError` is `isError && !hasData`, which is exactly this condition —
  // see `profile/api.ts:174-189` for the bug that taught us.
  if (profile === undefined || vocabulary === undefined || exercises === undefined) {
    const failed = profileFailed || vocabularyFailed || library.isLoadingError;
    return (
      <>
        <h1>Plan</h1>
        {failed ? (
          <>
            <p className="ct-app__status ct-app__status--error" role="alert">
              {/* Three reads, three failures, three sentences: naming the wrong one sends the
                  reader looking in the wrong place. */}
              {profileFailed
                ? 'Your profile could not be loaded, so there is nothing to build a plan from.'
                : vocabularyFailed
                  ? 'The grade lists could not be loaded.'
                  : 'The exercise library could not be loaded, so the plan has no exercises to name.'}
            </p>
            <div className="ct-app__actions">
              <button
                type="button"
                className="ct-app__button ct-app__button--primary"
                onClick={() => {
                  // Only what failed. Each of the three is cached reference-grade data, so
                  // refetching a healthy one because its neighbour broke is a wasted Neon wake.
                  retry();
                  if (library.isLoadingError) void library.refetch();
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
  const plan = preview.data;

  return (
    <>
      <h1>Plan</h1>
      <GoalLine profile={profile} vocabulary={vocabulary} plan={plan} />

      {blocker !== null ? (
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
      ) : plan === undefined ? (
        <PreviewPending preview={preview} readOnly={readOnly} />
      ) : (
        <PlanBody plan={plan} exercises={exercises} />
      )}
    </>
  );
}

/**
 * Current grade against the goal, from the profile rather than from the plan, so it is on screen
 * before the preview lands. `compareToGoal` returns `null` when the question cannot be asked
 * (one grade missing, or the two on different ladders), and then the line is simply absent.
 */
function GoalLine({
  profile,
  vocabulary,
  plan,
}: {
  profile: Profile;
  vocabulary: Vocabulary;
  plan: PlanPreview | undefined;
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

  // A 422 is the server's own refusal sentence for stored state the client could not see —
  // today that is only cross-discipline grades. Rendered verbatim, alone, because it already
  // says what to do. Anything else is a fault and reads as one.
  const error = preview.error;
  const refusal = error instanceof ApiError && error.status === 422 ? error.message : null;

  // A refusal names an answer only a real account can change, and it cannot come back
  // differently on a retry here — so in demo scope it gets the non-actionable explanation
  // instead of the sentence and a button. A genuine fault below still offers "Try again".
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
 * Every refusal, in demo scope. A demo principal is read-only at the database level
 * (`get_request_session` issues `SET LOCAL transaction_read_only`), so the profile editor the
 * other arm links to is a dead end — the fields render and nothing can be saved. So: no link, no
 * button, and deliberately no disabled control either, which reads as broken rather than as a
 * demo. The invariant is that this screen never offers the demo mount an action it cannot take.
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

function PlanBody({
  plan,
  exercises,
}: {
  plan: PlanPreview;
  exercises: readonly LibraryExercise[];
}) {
  // ONCE, for the whole plan. See the note at the top of the file.
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

/**
 * The phases in order, with the weeks each covers. One badge per mesocycle — there are `2n` of
 * them (a phase block plus its deload, and a taper last), so a 32-week plan draws sixteen.
 */
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
 * One week: its sessions, each behind a disclosure so a 32-week plan is readable without
 * scrolling past 2,421 prescribed sets.
 *
 * `week_no` is plan-global (1..`week_count`), not per mesocycle, so it is unique across the
 * whole screen and is the key.
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

          {/* A session-level shortfall is the honest empty session: zero blocks, and this is
              the sentence that says why. */}
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
 * ⚠️ **The server's wording, verbatim.** It is assembled from the equipment and aspect display
 * names by `server/domain/planner/selection.py::shortfall_message`, and it is guarded there
 * against suggesting an improvised finger edge. Re-wording it client-side would put that guard
 * behind a second copy nothing checks. It never disables anything and never opens a modal: a
 * shortfall is a note, and the plan around it is complete.
 */
function ShortfallNotice({ shortfall }: { shortfall: PlanShortfall }) {
  return (
    <p className="ct-app__notice" role="note">
      <span>{shortfall.message}</span>
    </p>
  );
}

export const Route = createLazyFileRoute('/_authed/plan')({ component: Plan });
