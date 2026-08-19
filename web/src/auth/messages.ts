import { ApiError, NotJsonError } from '../api/client';

/**
 * Turns an auth failure into something a person can act on.
 *
 * The server's own `detail` strings are correct but written for an API consumer, and three
 * of the statuses need real copy rather than a passthrough:
 *
 * - **409** on register is deliberate and not anti-enumeration hedging (there is no email
 *   verification step to hide behind), so it should say what to do about it.
 * - **422** is Pydantic's, so its `detail` is an array of `{loc, msg}` — readable now that
 *   `apiFetch` joins them, but "String should have at least 12 characters" is not the
 *   sentence to show someone. It deliberately names **no field**: this function is shared by
 *   `/login` and `/register`, which have different fields, and a 422 can come from the email,
 *   the password or the invite code. Copy that sent someone to check the two fields that are
 *   already fine was worse than copy that sends them to check all of them.
 * - **429** is the tight `register` bucket: **3 per hour per IP**. Two typos and one real
 *   attempt exhausts it, and behind a shared address it can trip without the visitor having
 *   done anything at all. Never imply the account exists or that they are blocked.
 *
 * **400 is deliberately NOT in the switch.** It is the invite gate, and the server's own
 * `_INVITE_REJECTED` is already the right sentence — including the "log in instead" half that
 * a returning invitee needs. Overriding it here would put "That invite code is not valid" on
 * the `/login` form, which has no invite field, because this function cannot see which route
 * called it. The `default` branch surfaces the detail; `messages.test.ts` pins that.
 */
export function authMessage(error: unknown): string {
  if (error instanceof NotJsonError) return error.message;

  if (error instanceof ApiError) {
    switch (error.status) {
      case 401:
        return 'Incorrect email or password.';
      case 403:
        // The demo write-ban. Reaching this means a demo token survived into a credential
        // call, which `authClient.ts` exists to prevent — so say something true rather than
        // echoing "demo mode is read-only" at someone trying to sign in.
        return 'That did not go through. Please reload the page and try again.';
      case 409:
        return 'That email is already registered — try logging in instead.';
      case 422:
        return 'Check the details you entered and try again.';
      case 429:
        return 'Too many attempts from this network. Please wait a little and try again.';
      default:
        return error.message;
    }
  }

  // A dropped connection, a CORS rejection, an aborted request: `fetch` rejects with a
  // TypeError whose message is browser-specific and useless to a visitor.
  return 'Could not reach the server. Check your connection and try again.';
}
