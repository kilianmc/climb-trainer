// @vitest-environment node
// Reads `node_modules` off disk, so it needs no DOM — same reason `distContract.test.ts` gives.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

/**
 * `plan/api.ts` and `profile/api.ts` assert TanStack behaviours that CLAUDE.md requires be READ
 * from the installed source, never reasoned about. Those citations used to be line numbers, which
 * rot on every dependency bump — #73 falsified six of nine with the whole suite green — so a
 * citation is now the CONSTRUCT it refers to, and this asserts each one is still there.
 *
 * ⚠️ **A construct that still exists proves the STRING is there, never that the logic around it
 * still behaves the same way.** A red here means re-read the comment that cites it against the
 * installed source; a green here is not a re-reading, and no test can be.
 */

interface Citation {
  /** Module under `build/modern/`, resolved across query-core then react-query. */
  file: string;
  /** A literal substring of that module, so a human can grep for it too. */
  construct: string;
  /** The claim the citing comment rests on. */
  why: string;
}

const CITATIONS: readonly Citation[] = [
  {
    file: 'mutation.js',
    construct: 'retry: this.options.retry ?? 0',
    why: 'A mutation does not retry, so a 409 reaches `mutationFn`’s `catch` exactly once.',
  },
  {
    file: 'mutation.js',
    construct: 'type: "pending",',
    why: '`execute()` dispatches it synchronously, before `onMutate` and before the retryer, so the derived overlay lands on the click.',
  },
  {
    file: 'mutation.js',
    construct: 'canRun: () => this.#mutationCache.canRun(this)',
    why: 'The `scope` gate is handed to the RETRYER, so `scope` serialises the network call and NOT `onMutate` — which is why a snapshot could see another write’s guess.',
  },
  {
    file: 'mutation.js',
    construct: 'await retryer.start()',
    why: 'The request is awaited inside `execute()`, between the `pending` dispatch and the success callbacks.',
  },
  {
    file: 'mutation.js',
    construct: 'await this.options.onSuccess?.(data,',
    why: '`onSuccess` is AWAITED before the `success` dispatch, so the cache is written before the mutation leaves `pending` and the bar cannot flicker backwards.',
  },
  {
    file: 'mutation.js',
    construct: 'this.options.onSuccess',
    why: 'Called on the mutation itself with no observer involved, which is why handlers are attached to the mutation rather than to `mutate(vars, {…})`.',
  },
  {
    file: 'mutation.js',
    construct: 'this.options.onError',
    why: 'Same reason as `this.options.onSuccess`: a superseded mutation’s per-call callback would report to nobody.',
  },
  {
    file: 'mutation.js',
    construct: 'this.#mutationCache.runNext(this);',
    why: '`execute()`’s `finally` continues the scope’s next mutation, which is what makes same-scope `onSuccess` fire in commit order.',
  },
  {
    file: 'mutationCache.js',
    construct: 'find((m) => m.state.status === "pending")',
    why: '`canRun` is true only for a scope’s FIRST pending mutation, so one scope serialises the requests — a create and an abandon are never on the wire at once.',
  },
  {
    file: 'queryClient.js',
    construct: 'if (data === void 0) return;',
    why: '`setQueryData` writes nothing when the updater yields `undefined`, which is how `useAbandonPlan` says “leave the cache alone”.',
  },
  {
    file: 'queryClient.js',
    construct: 'revert: true,',
    why: '`cancelQueries` defaults to reverting, so `cancelStaleRead` REMOVES a writer rather than adding one.',
  },
  {
    file: 'queryObserver.js',
    construct: 'isLoadingError: isError && !hasData',
    why: 'The “nothing to show” question every screen gates on. Gating on `isError` instead destroyed a user’s unsaved draft.',
  },
  {
    file: 'queryObserver.js',
    construct: 'resolveQueryBoolean(options.enabled, query) !== false',
    why: 'Every fetch decision gates on `enabled`, which is what stops a cleared cache refetching after logout — a 401, a refresh POST, and a Postgres write.',
  },
  {
    file: 'queryObserver.js',
    construct: 'refetchOnWindowFocus',
    why: 'The option this app disables globally, which is why every retry in these files has to be explicit.',
  },
  {
    file: 'query.js',
    construct: 'error.revert) this.setState({',
    why: 'A reverted `CancelledError` restores `#revertState`, so a cancelled in-flight read writes nothing at all.',
  },
  {
    file: 'notifyManager.js',
    construct: 'systemSetTimeoutZero',
    why: 'The scheduler behind the overlay landing on the NEXT tick rather than in the click handler.',
  },
  {
    file: 'useMutationState.js',
    construct: 'notifyManager.schedule',
    why: 'react-query delivers `useMutationState` through the same scheduler a `setQueryData` went through, which is the measured tick above.',
  },
  {
    file: 'useMutationState.js',
    construct: 'mutationCache.findAll',
    why: 'Re-run on every cache notification and passed through `replaceEqualDeep`, which is why the derived overlay array is referentially stable.',
  },
];

/** The two files whose comments carry the citations. */
const CITING = ['../plan/api.ts', '../profile/api.ts'] as const;

const PACKAGES = ['@tanstack/query-core', '@tanstack/react-query'] as const;

// A backticked quote this long that appears verbatim in an installed module IS a construct
// citation, so it must have a row above — enforced by the last arm.
const CONSTRUCT_MIN_LENGTH = 20;

function read(url: string): string {
  return readFileSync(fileURLToPath(new URL(url, import.meta.url)), 'utf8');
}

/** The installed module, or a loud failure naming the bump that must have moved it. */
function installedModule(file: string): string {
  for (const pkg of PACKAGES) {
    try {
      return read(`../../node_modules/${pkg}/build/modern/${file}`);
    } catch {
      continue;
    }
  }
  throw new Error(
    `${file} is in neither ${PACKAGES.join(' nor ')} under build/modern/. A dependency bump ` +
      `moved or removed the module, so every comment in plan/api.ts and profile/api.ts citing ` +
      `it is unverified — re-read them against the installed source.`,
  );
}

function citingSource(): string {
  return CITING.map(read).join('\n');
}

/** Every backticked quote long enough to be code, paired with the modules holding it verbatim. */
function detectedCitations(): Map<string, string[]> {
  const modules = [...new Set(CITATIONS.map((citation) => citation.file))];
  const found = new Map<string, string[]>();
  for (const quote of new Set(citingSource().match(/`[^`\n]+`/g) ?? [])) {
    const construct = quote.slice(1, -1);
    if (construct.length < CONSTRUCT_MIN_LENGTH) continue;
    const holders = modules.filter((file) => installedModule(file).includes(construct));
    if (holders.length > 0) found.set(construct, holders);
  }
  return found;
}

describe('library citations', () => {
  it('every cited construct is still in the installed source', () => {
    const gone = CITATIONS.filter(
      (citation) => !installedModule(citation.file).includes(citation.construct),
    );
    expect(
      gone.map((citation) => `${citation.file} — ${citation.construct} — ${citation.why}`),
      'A dependency bump has removed a construct that a comment in plan/api.ts or ' +
        'profile/api.ts asserts. The behaviour it stands for may be GONE: re-read the installed ' +
        'source and the comment together, and do not just re-point the citation.',
    ).toEqual([]);
  });

  it('is not vacuous: the table is populated and every module really was read', () => {
    expect(CITATIONS.length).toBeGreaterThanOrEqual(9);
    for (const file of new Set(CITATIONS.map((citation) => citation.file))) {
      expect(
        installedModule(file).length,
        `${file} read as an empty or truncated module`,
      ).toBeGreaterThan(500);
    }
    // The matcher must be able to fail, or a green arm above means nothing.
    expect(installedModule('mutation.js').includes('retry: this.options.retry ?? 42')).toBe(false);
    expect(citingSource().length).toBeGreaterThan(10_000);
  });

  it('every construct in the table is quoted by a comment that rests on it', () => {
    const source = citingSource();
    const unquoted = CITATIONS.filter((citation) => !source.includes(citation.construct));
    expect(
      unquoted.map((citation) => `${citation.file} — ${citation.construct}`),
      'A row here cites something plan/api.ts and profile/api.ts no longer quote. Either the ' +
        'comment was reworded — requote the construct — or the claim is gone and so is the row.',
    ).toEqual([]);
  });

  it('every construct those comments quote has a row in the table', () => {
    const known = new Set(CITATIONS.map((citation) => citation.construct));
    const unlisted = [...detectedCitations()]
      .filter(([construct]) => !known.has(construct))
      .map(([construct, holders]) => `${holders.join('/')} — ${construct}`);
    expect(
      unlisted,
      'These comments quote library source that no row in CITATIONS covers, so nothing would ' +
        'notice if a bump removed it. Add a row with the reason the claim rests on.',
    ).toEqual([]);
  });
});
