import { useState, type FormEvent } from 'react';

import type { Credentials } from '../auth/authClient';

/**
 * The one email/password form, shared by `/login` and `/register`.
 *
 * `minLength={12}` mirrors `_MIN_PASSWORD_LENGTH` in `server/auth/routes.py`. The server is
 * still the authority — this exists because the `register` rate limit is **3 per hour per
 * IP**, so a 422 the browser could have caught costs a third of someone's whole budget.
 * Login sends no minimum (`LoginRequest` has none either, deliberately: enforcing the
 * registration floor there would leak the policy from a 422 and lock out anyone whose
 * password predates a future change).
 *
 * Not unit-tested, per the testing policy: it renders the props it was given. The behaviour
 * worth testing — that submitting drops a demo token, and where a success navigates to —
 * lives in `auth/` and in the guard tests.
 *
 * The form IS the card (no wrapper element), and the submit sits in `ct-app__actionbar` — which
 * GROUPS it at the end of the form behind a hairline rule and stretches it to the card's full
 * width. It does **not** anchor it to the bottom of the viewport: that needs `position: fixed` or
 * a full-height container, and both resolve against kilianmc.com's viewport in the federated
 * mount. See `styles/_chrome.scss` for the measurement and for why real bottom-anchoring waits
 * for the session player.
 */
export interface CredentialsFormProps {
  submitLabel: string;
  pendingLabel: string;
  passwordAutoComplete: 'current-password' | 'new-password';
  minPasswordLength?: number;
  pending: boolean;
  error: string | null;
  onSubmit: (credentials: Credentials) => void;
}

export function CredentialsForm({
  submitLabel,
  pendingLabel,
  passwordAutoComplete,
  minPasswordLength,
  pending,
  error,
  onSubmit,
}: CredentialsFormProps) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  function submit(event: FormEvent<HTMLFormElement>) {
    // The form must never actually navigate: the document CSP sets `form-action 'none'`,
    // and in the federated mount a real submit would unload the whole portfolio.
    event.preventDefault();
    onSubmit({ email, password });
  }

  return (
    <form className="ct-app__card ct-app__form" onSubmit={submit} noValidate={false}>
      <label className="ct-app__field" htmlFor="credentials-email">
        Email
        <input
          id="credentials-email"
          className="ct-app__input"
          type="email"
          name="email"
          autoComplete="email"
          inputMode="email"
          required
          maxLength={254}
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
      </label>

      <label className="ct-app__field" htmlFor="credentials-password">
        Password
        <input
          id="credentials-password"
          className="ct-app__input"
          type="password"
          name="password"
          autoComplete={passwordAutoComplete}
          required
          maxLength={128}
          {...(minPasswordLength === undefined ? {} : { minLength: minPasswordLength })}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
      </label>
      {minPasswordLength !== undefined && (
        <p className="ct-app__muted">At least {minPasswordLength} characters.</p>
      )}

      {error !== null && (
        <p className="ct-app__error" role="alert">
          {error}
        </p>
      )}

      <div className="ct-app__actionbar">
        <button type="submit" className="ct-app__button ct-app__button--primary" disabled={pending}>
          {pending ? pendingLabel : submitLabel}
        </button>
      </div>
    </form>
  );
}
