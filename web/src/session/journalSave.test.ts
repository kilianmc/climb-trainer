import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook } from '@testing-library/react';
import { createElement } from 'react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

import { ApiError } from '../api/client';

import { makeBlock, makeLibrary, makeSession, makeSet } from './fixtures';
import { journalSaveOffer } from './journal';
import { compileProtocol } from './protocol';
import { RUN_STORAGE_KEY, parseRun, setRun } from './runStore';
import { createRun, getRun } from './runStore';
import { useSessionRun } from './useSessionRun';

/** What happens to the words when the write fails: a 5xx stays unsaved, a 4xx is refused, and
 *  either way the text is still in `localStorage`. The one rule this box may not break. */

const request = vi.fn();
let scope = 'user';

vi.mock('../auth/AuthProvider', () => ({
  useAuth: () => ({ request, scope }),
}));

const START = Date.UTC(2026, 7, 28, 17, 0, 0);

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });
  return createElement(QueryClientProvider, { client }, children);
}

function mount() {
  const session = makeSession([
    makeBlock({
      protocol_kind: 'max_hang',
      exercise_id: 11,
      sets: [makeSet({ id: 501, set_index: 1, target_work_seconds: 10 })],
    }),
  ]);
  setRun(
    createRun({
      occurredOn: '2026-08-28',
      discipline: 'boulder',
      plannedSessionId: 7,
      startedAtEpochMs: START,
      timeline: compileProtocol(session, makeLibrary()),
      preDoneBlockIndexes: [],
    }),
  );
  const view = renderHook(() => useSessionRun(), { wrapper });
  view.result.current.countdownRef.current = document.createElement('div');
  return view;
}

/** Press Save and let the mutation settle. `saveJournal` is fire-and-forget by design — the
 *  box does not await it either — so the test drains the queue rather than await a promise. */
async function pressSave(view: ReturnType<typeof mount>): Promise<void> {
  await act(async () => {
    view.result.current.saveJournal();
    await Promise.resolve();
  });
}

/** The one request the journal box makes, whatever else the run did. */
function journalCalls() {
  return request.mock.calls.filter(([path]) => String(path).startsWith('/api/journal/'));
}

beforeEach(() => {
  scope = 'user';
  request.mockReset();
  request.mockResolvedValue({ id: 900, client_uuid: 'x', sets: [] });
  window.localStorage.clear();
});

afterEach(() => {
  setRun(null);
  vi.restoreAllMocks();
});

it('sends the entry under the RUN’s own uuid, so a resubmission is one row', async () => {
  const view = mount();
  const clientUuid = getRun()?.clientUuid;
  act(() => {
    view.result.current.setJournalDraft({ body: 'fingers feel tweaky', feel: 2 });
  });
  await pressSave(view);

  expect(journalCalls()).toHaveLength(1);
  const [path, options] = journalCalls()[0] as [string, { method: string; json: unknown }];
  expect(path).toBe(`/api/journal/${String(clientUuid)}`);
  expect(options.method).toBe('PUT');
  expect(options.json).toMatchObject({ body: 'fingers feel tweaky', feel: 2 });

  // Saved, and the text STAYS on screen: the climber gets to see what they wrote.
  expect(view.result.current.journal.savedAtEpochMs).not.toBeNull();
  expect(view.result.current.journal.body).toBe('fingers feel tweaky');
});

it('KEEPS THE TEXT after a 5xx and leaves it unsaved so Save goes out again', async () => {
  const view = mount();
  act(() => {
    view.result.current.setJournalDraft({ body: 'felt strong today', skin: 4 });
  });
  request.mockRejectedValueOnce(new ApiError('boom', 500));
  await pressSave(view);

  const draft = view.result.current.journal;
  expect(draft.body).toBe('felt strong today');
  expect(draft.skin).toBe(4);
  expect(draft.savedAtEpochMs).toBeNull();
  // A 5xx is retryable, so it is NOT refused — the box offers Save, not a dead end.
  expect(draft.refusedAtEpochMs).toBeNull();
  // ⚠️ And it survives the tab: `localStorage` is what makes this a real answer.
  expect(parseRun(window.localStorage.getItem(RUN_STORAGE_KEY))?.journal.body).toBe(
    'felt strong today',
  );
});

it('KEEPS THE TEXT after a 4xx and marks it refused rather than retrying for ever', async () => {
  const view = mount();
  act(() => {
    view.result.current.setJournalDraft({ body: 'unlucky payload' });
  });
  request.mockRejectedValueOnce(new ApiError('refused', 422));
  await pressSave(view);

  expect(view.result.current.journal.body).toBe('unlucky payload');
  expect(view.result.current.journal.refusedAtEpochMs).not.toBeNull();
  expect(parseRun(window.localStorage.getItem(RUN_STORAGE_KEY))?.journal.body).toBe(
    'unlucky payload',
  );
});

it('clears the saved AND refused marks on the next edit', async () => {
  const view = mount();
  act(() => {
    view.result.current.setJournalDraft({ body: 'first go' });
  });
  request.mockRejectedValueOnce(new ApiError('refused', 422));
  await pressSave(view);
  expect(view.result.current.journal.refusedAtEpochMs).not.toBeNull();

  act(() => {
    view.result.current.setJournalDraft({ body: 'second go' });
  });
  expect(view.result.current.journal.refusedAtEpochMs).toBeNull();
  expect(view.result.current.journal.savedAtEpochMs).toBeNull();
});

it('keeps the server’s row id, which is the whole difference between Save and Update', async () => {
  const view = mount();
  request.mockResolvedValue({
    id: 41,
    client_uuid: 'x',
    entry_date: '2026-08-28',
    logged_session_id: null,
  });
  act(() => {
    view.result.current.setJournalDraft({ body: 'first go' });
  });
  await pressSave(view);
  expect(view.result.current.journal.entryId).toBe(41);
  expect(journalSaveOffer(view.result.current.journal)).toBe('none');

  act(() => {
    view.result.current.setJournalDraft({ body: 'second go' });
  });
  // The row outlives the text: the edit cleared the marks and NOT the id, so the press now
  // edits row 41 rather than creating one — which is the only thing that licenses "Update".
  expect(view.result.current.journal.entryId).toBe(41);
  expect(journalSaveOffer(view.result.current.journal)).toBe('update');
});

it('offers SAVE, never Update, after a 4xx that was then edited', async () => {
  const view = mount();
  act(() => {
    view.result.current.setJournalDraft({ body: 'unlucky payload' });
  });
  request.mockRejectedValueOnce(new ApiError('refused', 422));
  await pressSave(view);
  // Refused and UNEDITED: no control at all, or quarantine's doctrine is a suggestion.
  expect(journalSaveOffer(view.result.current.journal)).toBe('none');

  act(() => {
    view.result.current.setJournalDraft({ body: 'edited payload' });
  });
  // ⚠️ Nothing landed, so this press CREATES the row. "Update" here would be a lie about the
  // server's state, and the text is still on the record either way.
  expect(view.result.current.journal.entryId).toBeNull();
  expect(journalSaveOffer(view.result.current.journal)).toBe('save');
  expect(parseRun(window.localStorage.getItem(RUN_STORAGE_KEY))?.journal.body).toBe(
    'edited payload',
  );
});

it('offers SAVE after a 5xx, because nothing landed then either', async () => {
  const view = mount();
  act(() => {
    view.result.current.setJournalDraft({ body: 'felt strong today' });
  });
  request.mockRejectedValueOnce(new ApiError('boom', 500));
  await pressSave(view);
  expect(view.result.current.journal.entryId).toBeNull();
  expect(journalSaveOffer(view.result.current.journal)).toBe('save');
});

it('sends nothing at all for an empty draft', async () => {
  const view = mount();
  await pressSave(view);
  expect(journalCalls()).toHaveLength(0);
});

it('sends nothing at all in demo scope, while the draft still persists locally', async () => {
  scope = 'demo';
  const view = mount();
  act(() => {
    view.result.current.setJournalDraft({ body: 'demo words' });
  });
  await pressSave(view);
  expect(journalCalls()).toHaveLength(0);
  expect(view.result.current.journal.body).toBe('demo words');
});
