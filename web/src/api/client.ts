/**
 * API client.
 *
 * Two hard-won rules encoded here:
 *
 * 1. **Resolve the base from `import.meta.url`, not a relative path.** When this app
 *    runs as a module-federation remote inside kilianmc.com, a relative `/api/...`
 *    hits the *shell's* SPA rewrite and returns `200 text/html`. `res.ok` is then
 *    true and `res.json()` throws somewhere unrelated. This already bit the fund
 *    dashboard once (`navService.js` exists for exactly this reason).
 * 2. **Guard the content-type.** Even same-origin, a misconfigured rewrite can hand
 *    back the SPA shell with a 200. Trusting `res.ok` alone is not enough — spike S0
 *    exists partly to prove `/api/*` returns JSON.
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

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    // The refresh cookie is httpOnly and same-site; it only travels when asked for.
    credentials: 'include',
    headers: { accept: 'application/json', ...init?.headers },
  });

  const contentType = res.headers.get('content-type') ?? '';
  if (!contentType.includes('application/json')) {
    throw new NotJsonError(res.status, contentType || '(none)');
  }

  const body = (await res.json()) as T & { detail?: string };
  if (!res.ok) {
    throw new ApiError(body.detail ?? `Request failed with ${res.status}`, res.status);
  }
  return body;
}
