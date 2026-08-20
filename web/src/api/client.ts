/**
 * API client.
 *
 * Three hard-won rules encoded here:
 *
 * 1. **Resolve the base from `import.meta.url`, not a relative path.** When this app
 *    runs as a module-federation remote inside kilianmc.com, a relative `/api/...`
 *    hits the *shell's* SPA rewrite and returns `200 text/html`. `res.ok` is then
 *    true and `res.json()` throws somewhere unrelated. This already bit the fund
 *    dashboard once (`navService.js` exists for exactly this reason).
 * 2. **Guard the content-type.** Even same-origin, a misconfigured rewrite can hand
 *    back the SPA shell with a 200. Trusting `res.ok` alone is not enough — spike S0
 *    exists partly to prove `/api/*` returns JSON.
 * 3. **`headers` is a plain record, never a `Headers` instance.** It is spread into an
 *    object literal, and spreading a `Headers` yields `{}` — which would silently drop
 *    both `accept` and `authorization`. The narrow type makes that a compile error
 *    instead of a mystery 401.
 * 4. **A caller's `signal` is forwarded, and there is no default timeout here — on purpose.**
 *    Issue #28 weighed one and turned it down: a deadline in this function is inherited by
 *    every caller and every future one, and the right duration is a property of the call, not
 *    of the client. The auth path sets its own (`AUTH_TIMEOUT_MS` in `auth/refresh.ts`) because
 *    it gates the route guard and holds an origin-wide lock. Adding one here would silently
 *    re-scope that decision to the whole app.
 */

/** Origin this bundle was served from, which is the API origin in both mounts. */
function resolveApiBase(): string {
  try {
    // @vite-ignore — must stay unresolved at build time. Runtime resolution is the
    // whole point: it yields the origin this chunk was actually loaded from.
    return new URL(/* @vite-ignore */ '.', import.meta.url).origin;
  } catch {
    return globalThis.location?.origin ?? '';
  }
}

export const API_BASE = resolveApiBase();

export interface ApiRequestInit {
  method?: string;
  /**
   * Request body, JSON-encoded, with the `content-type` header FastAPI requires.
   * `strict_content_type` has been on by default since FastAPI 0.132: a POST carrying a
   * body without `content-type: application/json` is a 422, not a parse attempt.
   */
  json?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

/** Thrown when the API answers with HTML — i.e. a rewrite swallowed the request. */
export class NotJsonError extends ApiError {
  constructor(status: number, contentType: string) {
    super(
      `Expected JSON from the API but received "${contentType}". ` +
        'A rewrite is most likely serving the SPA shell for this path.',
      status,
    );
    this.name = 'NotJsonError';
  }
}

/**
 * FastAPI's `detail` is a **string** for our own `HTTPException`s and an **array of
 * `{loc, msg, type}` objects** for a Pydantic 422. Reading it as a string either way put
 * `[object Object]` in front of the user on every validation failure, which is exactly
 * the case the auth forms hit most often.
 */
function detailMessage(detail: unknown): string | null {
  if (typeof detail === 'string' && detail !== '') return detail;
  if (!Array.isArray(detail)) return null;

  const messages = detail.flatMap((entry: unknown) => {
    if (typeof entry !== 'object' || entry === null) return [];
    const { msg } = entry as { msg?: unknown };
    return typeof msg === 'string' ? [msg] : [];
  });
  return messages.length > 0 ? messages.join('; ') : null;
}

export async function apiFetch<T>(path: string, init?: ApiRequestInit): Promise<T> {
  const headers: Record<string, string> = { accept: 'application/json', ...init?.headers };
  const request: RequestInit = {
    // The refresh cookie is httpOnly and same-site; it only travels when asked for.
    credentials: 'include',
    headers,
  };

  if (init?.method !== undefined) request.method = init.method;
  if (init?.signal !== undefined) request.signal = init.signal;
  if (init !== undefined && 'json' in init) {
    headers['content-type'] = 'application/json';
    request.body = JSON.stringify(init.json);
    request.method = init.method ?? 'POST';
  }

  const res = await fetch(`${API_BASE}${path}`, request);

  const contentType = res.headers.get('content-type') ?? '';
  if (!contentType.includes('application/json')) {
    throw new NotJsonError(res.status, contentType || '(none)');
  }

  const body: unknown = await res.json();
  if (!res.ok) {
    const detail =
      typeof body === 'object' && body !== null ? (body as { detail?: unknown }).detail : undefined;
    throw new ApiError(detailMessage(detail) ?? `Request failed with ${res.status}`, res.status);
  }
  return body as T;
}
