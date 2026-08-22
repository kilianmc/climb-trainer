/**
 * What the wizard and the editor render when there is **nothing to show yet**.
 *
 * ⚠️ Reached only when the profile or the vocabulary is `undefined` — never merely because a
 * query is in an error state. `query.js`'s error reducer sets `status: "error"`
 * unconditionally, even with data present, so a failed BACKGROUND refetch used to bring this
 * screen up in place of a half-filled wizard and take the user's unsaved draft with it (the
 * draft is `useState` inside the wizard). See `ProfileView.isLoadingError`.
 *
 * The retry button is not decoration: `refetchOnWindowFocus` is off for the whole app, so
 * without it a failed first load is terminal until a manual reload.
 */
export interface ProfileFallbackProps {
  title: string;
  profileFailed: boolean;
  vocabularyFailed: boolean;
  retry: () => void;
}

export function ProfileFallback({
  title,
  profileFailed,
  vocabularyFailed,
  retry,
}: ProfileFallbackProps) {
  return (
    <>
      <h1>{title}</h1>
      {profileFailed || vocabularyFailed ? (
        <>
          <p className="ct-app__status ct-app__status--error" role="alert">
            {/* Two reads, two failures, two sentences. Saying "your profile" when it was the
                grade ladder that failed sends the reader looking in the wrong place. */}
            {profileFailed
              ? 'Your profile could not be loaded.'
              : 'The grade and aspect lists could not be loaded.'}
          </p>
          <div className="ct-app__actions">
            <button
              type="button"
              className="ct-app__button ct-app__button--primary"
              onClick={retry}
            >
              Try again
            </button>
          </div>
        </>
      ) : (
        <p className="ct-app__status">Loading your profile…</p>
      )}
    </>
  );
}
