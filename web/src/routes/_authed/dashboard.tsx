import { createFileRoute, Link } from '@tanstack/react-router';

import { useAuth } from '../../auth/AuthProvider';
import { useProfileView } from '../../profile/api';
import {
  STEP_TITLES,
  completionPercent,
  remainingSteps,
  stepCompletion,
} from '../../profile/completion';
import { ProfileProgress } from '../../profile/ProfileProgress';

/**
 * Dashboard placeholder — PR #8 onward fills it in. Eager, not lazy: it is where every
 * successful login lands, so there is nothing to gain from a second round trip.
 *
 * The `/api/health` probe that lived here until PR #6 is gone. Its only job was to exercise
 * `apiFetch` resolving its base from `import.meta.url` in a real browser; the auth calls now
 * do that on the path a visitor actually takes.
 */
function Dashboard() {
  const { scope } = useAuth();

  return (
    <>
      <h1>Dashboard</h1>
      <div className="ct-app__card">
        <p>
          {scope === 'demo'
            ? 'You are exploring the demo. Everything is read-only.'
            : 'Your training plan and today’s session will appear here.'}
        </p>
        {/* The ONLY way into the exercise library, deliberately. A sixth nav destination would
            invalidate `_chrome.scss`'s measured threshold table — its tightest regime is
            budgeted at 311px of content and clears a 365px phone by ~6px — and issue #60 is
            already open about the nav overflowing on mobile. */}
        <div className="ct-app__actions">
          <Link className="ct-app__button" to="/library">
            Browse the exercise library
          </Link>
        </div>
      </div>
      {scope !== 'demo' && <UnfinishedProfile />}
    </>
  );
}

/**
 * The open loop, closed on the screen the user actually lands on.
 *
 * The plan's Zeigarnik point in one card: an unfinished profile is stated as a percentage
 * and a count of what is left, with a link straight back into the step that is next. It
 * **renders nothing at all** once every step is done — a nag that never goes away
 * stops being information — and nothing while the query is in flight or failed, because
 * "0 sections left" and "we could not ask" must never look alike.
 *
 * Not shown in demo mode: a demo token cannot write, so there is nothing to finish.
 */
function UnfinishedProfile() {
  const { profile } = useProfileView();
  // Nothing while the load is in flight or failed: "0 sections left" and "we could not ask"
  // must never look alike.
  if (profile === undefined) return null;

  const completion = stepCompletion(profile);
  const open = remainingSteps(completion);
  const [next] = open;
  if (next === undefined) return null;

  return (
    <section className="ct-app__card">
      <h2>Finish your profile</h2>
      <ProfileProgress percent={completionPercent(completion)} label="Profile completion" />
      <p className="ct-app__muted">
        {open.length === 1 ? '1 step left' : `${String(open.length)} steps left`} — next up,{' '}
        {STEP_TITLES[next].toLowerCase()}. The plan generator needs it before it can build anything.
      </p>
      <div className="ct-app__actions">
        <Link className="ct-app__button ct-app__button--primary" to="/onboarding">
          Continue setup
        </Link>
      </div>
    </section>
  );
}

export const Route = createFileRoute('/_authed/dashboard')({ component: Dashboard });
