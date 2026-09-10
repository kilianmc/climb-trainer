import { createLazyFileRoute } from '@tanstack/react-router';
import { useMemo, useState } from 'react';

import type { JournalEntry, PhaseGuide } from '../../api/types';
import { useAuth } from '../../auth/AuthProvider';
import { EntryDetail } from '../../diary/EntryDetail';
import { EntryRow } from '../../diary/EntryRow';
import { PlanRename } from '../../diary/PlanRename';
import { WellbeingChart } from '../../diary/DiaryChart';
import type { SortOrder } from '../../diary/entries';
import { groupByPlan, sortEntries, sortPlanGroups } from '../../diary/entries';
import type { PlanWeek } from '../../diary/chart';
import { groupSpan, journalPlanWeeks, planWeeks } from '../../diary/chart';
import { useJournal } from '../../diary/api';
import type { PhaseGuides } from '../../plan/PhaseGuide';
import { phaseGuides, phaseLabel } from '../../plan/PhaseGuide';
import { useActivePlanView } from '../../plan/api';
import { useProfileScreen } from '../../profile/api';
import { writesEnabled } from '../../session/api';
import { localIsoDate } from '../../session/today';
import {
  IconPlanSortNewest,
  IconPlanSortOldest,
  IconSortNewest,
  IconSortOldest,
} from '../../ui/icons';

/** `/diary` — ONE section per plan and every one the same shape (Kilian): the plan's name, then a
 *  card with its chart, its readings as numbers and its own entries. ⚠️ No goal, band or delta. */
function Diary() {
  // ⚠️ The profile and the vocabulary are deliberately NOT in the gate below: unread reads as
  // body-metrics OFF (`SessionJournal`'s rule) and `phaseLabel` falls back to `humanise`.
  const { profile, vocabulary } = useProfileScreen();
  const active = useActivePlanView();
  const canEdit = writesEnabled(useAuth().scope);
  const todayIso = localIsoDate(new Date());
  const [wholeHistory, setWholeHistory] = useState(false);
  const [planOrder, setPlanOrder] = useState<SortOrder>('newest');
  const [openUuid, setOpenUuid] = useState<string | null>(null);

  const activePlanId = active.plan?.id ?? null;
  // TWO keys, so the scoped read and the whole history both stay cached. ⚠️ Held until the
  // active read lands: fetching before it would cache the wrong scope under the wrong key.
  const journal = useJournal(wholeHistory ? null : activePlanId, active.plan !== undefined);

  const showBodyMetrics = profile?.show_body_metrics === true;
  // ⚠️ The active plan's OWN ruler under either read: its section renders with the whole history
  // open too, so taking the ticks off the toggle would silently unrule the current chart.
  const chartWeeks = useMemo(() => planWeeks(active.plan), [active.plan]);
  const guides: PhaseGuides = useMemo(
    () => (vocabulary === undefined ? new Map<string, PhaseGuide>() : phaseGuides(vocabulary)),
    [vocabulary],
  );

  const data = journal.data;
  const plansById = useMemo(
    () => new Map((data?.plans ?? []).map((plan) => [plan.plan_id, plan])),
    [data],
  );
  const planNameOf = (entry: JournalEntry): string | null =>
    entry.plan === null ? null : (plansById.get(entry.plan.plan_id)?.name ?? null);

  // ⚠️ Exactly what the SCOPED read returns: `_journal_query` filters on the attributed
  // `plan_id`, so an entry no plan claims is never in it and must not land in this section.
  const activeEntries = useMemo(
    () =>
      data === undefined || activePlanId === null
        ? []
        : data.entries.filter((entry) => entry.plan?.plan_id === activePlanId),
    [data, activePlanId],
  );
  // Every OTHER plan, each with its own axis, so no chart is ruled in another plan's weeks. ⚠️ The
  // ACTIVE plan is excluded: the unscoped read carries it too, and grouping it blind renders twice.
  const oldSections = useMemo(() => {
    if (data === undefined) return [];
    const rest = data.entries.filter((entry) => (entry.plan?.plan_id ?? null) !== activePlanId);
    return sortPlanGroups(groupByPlan(rest, data.plans), planOrder).map((group) => {
      const weeks = journalPlanWeeks(group.plan);
      return { ...group, weeks, axis: groupSpan(weeks, group.entries, todayIso) };
    });
  }, [data, activePlanId, planOrder, todayIso]);

  // ⚠️ `data === undefined`, never `isError`: a failed background refetch must not replace a
  // diary the climber is reading. Sorting is client-side and issues no request.
  if (data === undefined || active.plan === undefined) {
    const failed = journal.isLoadingError || active.isLoadingError;
    return (
      <>
        <h1>Diary</h1>
        {failed ? (
          <>
            <p className="ct-app__status ct-app__status--error" role="alert">
              {journal.isLoadingError
                ? 'Your diary could not be loaded, so nothing is shown rather than the wrong thing.'
                : 'We could not check which plan you are on, so the entries have nothing to be grouped under.'}
            </p>
            <div className="ct-app__actions">
              <button
                type="button"
                className="ct-app__button ct-app__button--primary"
                onClick={() => {
                  if (journal.isLoadingError) void journal.refetch();
                  if (active.isLoadingError) active.retry();
                }}
              >
                Try again
              </button>
            </div>
          </>
        ) : (
          <p className="ct-app__status">Loading your diary…</p>
        )}
      </>
    );
  }

  const open = data.entries.find((entry) => entry.client_uuid === openUuid) ?? null;
  // Narrowed once: the early return ruled out `undefined`. A PREVIEW's ids are ABSENT, so
  // `activePlanId` rather than `plan !== null` is what says a section can be addressed at all.
  const activePlan = active.plan;
  const current = activePlan === null || activePlanId === null ? null : activePlan;
  // With no plan of her own there is no current section to open a history behind, so the old
  // sections are simply the whole diary.
  const showOld = wholeHistory || activePlanId === null;

  return (
    <div className="ct-app__bleed ct-app__diary">
      <div className="ct-app__diarybody">
        <h1>Diary</h1>

        {/* A fact about the whole READ, not about one plan, so it sits above every section. */}
        {data.truncated ? (
          <p className="ct-app__notice" role="note">
            <span>
              This is as far back as one read goes. There are older entries than the ones listed
              here.
            </span>
          </p>
        ) : null}

        {current === null || activePlanId === null ? null : (
          <PlanSection
            planId={activePlanId}
            planName={current.name}
            canEdit={canEdit}
            entries={activeEntries}
            weeks={chartWeeks}
            anchorIso={current.start_date ?? null}
            todayIso={todayIso}
            showBodyMetrics={showBodyMetrics}
            guides={guides}
            planNameOf={planNameOf}
            onOpen={setOpenUuid}
          />
        )}

        {/* AFTER the current plan's card (Kilian): what this reveals is appended BELOW it, so the
            control sits where the new sections arrive rather than a screen above them. */}
        {data.has_entries_outside_plan && !wholeHistory ? (
          <div className="ct-app__actions">
            <button
              type="button"
              className="ct-app__button"
              onClick={() => {
                setWholeHistory(true);
              }}
            >
              Show old plans
            </button>
          </div>
        ) : null}
        {wholeHistory && activePlanId !== null ? (
          <div className="ct-app__actions">
            <button
              type="button"
              className="ct-app__button"
              onClick={() => {
                setWholeHistory(false);
              }}
            >
              Only current plan
            </button>
          </div>
        ) : null}

        {showOld ? (
          <>
            {/* Which SECTION leads, never a second entry sort (Kilian) — and nothing to decide
                until there are two of them. */}
            {oldSections.length > 1 ? (
              <SortControls order={planOrder} onPick={setPlanOrder} of="plans" />
            ) : null}
            {oldSections.map((section) => (
              <PlanSection
                key={section.key}
                planId={section.plan?.plan_id ?? null}
                planName={section.plan?.name ?? 'Outside any plan'}
                canEdit={canEdit}
                entries={section.entries}
                weeks={section.weeks}
                anchorIso={section.axis.anchorIso}
                todayIso={section.axis.endIso}
                showBodyMetrics={showBodyMetrics}
                guides={guides}
                planNameOf={planNameOf}
                onOpen={setOpenUuid}
              />
            ))}
          </>
        ) : null}

        {current === null && oldSections.length === 0 ? (
          <p className="ct-app__muted">Nothing written down yet.</p>
        ) : null}
      </div>

      {open === null ? null : (
        <EntryDetail
          entry={open}
          planName={planNameOf(open)}
          phaseName={open.plan === null ? null : phaseLabel(guides, open.plan.phase)}
          showBodyMetrics={showBodyMetrics}
          canEdit={canEdit}
          onClose={() => {
            setOpenUuid(null);
          }}
        />
      )}
    </div>
  );
}

/** ONE plan, current or finished, and the same shape either way (Kilian): the name with its
 *  pencil, then a card holding that plan's chart, its numbers and its own entries. */
function PlanSection({
  planId,
  planName,
  canEdit,
  entries,
  weeks,
  anchorIso,
  todayIso,
  showBodyMetrics,
  guides,
  planNameOf,
  onOpen,
}: {
  /** `null` for the entries no plan claims: a real section, but nothing to rename. */
  planId: number | null;
  planName: string;
  canEdit: boolean;
  entries: readonly JournalEntry[];
  weeks: readonly PlanWeek[];
  anchorIso: string | null;
  todayIso: string;
  showBodyMetrics: boolean;
  guides: PhaseGuides;
  planNameOf: (entry: JournalEntry) => string | null;
  onOpen: (clientUuid: string) => void;
}) {
  // ⚠️ Per SECTION, so one plan's order cannot reorder another plan's list. The chart takes the
  // entries UNSORTED: `diaryChart` orders them itself and must not depend on this.
  const [order, setOrder] = useState<SortOrder>('newest');
  const sorted = useMemo(() => sortEntries(entries, order), [entries, order]);
  return (
    <div className="ct-app__diarygroup">
      {planId === null ? (
        <h2>{planName}</h2>
      ) : (
        <PlanRename
          planId={planId}
          planName={planName}
          canRename={canEdit}
          idPrefix={`ct-diary-rename-${String(planId)}`}
        />
      )}
      <section className="ct-app__card">
        <WellbeingChart
          entries={entries}
          anchorIso={anchorIso}
          weeks={weeks}
          todayIso={todayIso}
          showBodyMetrics={showBodyMetrics}
        />
        <SortControls order={order} onPick={setOrder} of="entries" />
        {sorted.length === 0 ? (
          <p className="ct-app__muted">Nothing written down yet.</p>
        ) : (
          <EntryList entries={sorted} guides={guides} planNameOf={planNameOf} onOpen={onOpen} />
        )}
      </section>
    </div>
  );
}

function EntryList({
  entries,
  guides,
  planNameOf,
  onOpen,
}: {
  entries: readonly JournalEntry[];
  guides: PhaseGuides;
  planNameOf: (entry: JournalEntry) => string | null;
  onOpen: (clientUuid: string) => void;
}) {
  return (
    <ul className="ct-app__diarylist">
      {entries.map((entry) => (
        <EntryRow
          key={entry.client_uuid}
          entry={entry}
          planName={planNameOf(entry)}
          phaseName={entry.plan === null ? null : phaseLabel(guides, entry.plan.phase)}
          onOpen={() => {
            onOpen(entry.client_uuid);
          }}
        />
      ))}
    </ul>
  );
}

/** What each control is FOR, in the words it says out loud. Two subjects, and they must read
 *  differently: one flips a list of entries, the other flips which plan section leads. */
const SORT_LABELS = {
  entries: ['Newest first — switch to oldest first', 'Oldest first — switch to newest first'],
  plans: [
    'Newest plan first — switch to oldest plan first',
    'Oldest plan first — switch to newest plan first',
  ],
} as const;

/** ONE control that FLIPS (Kilian): the GLYPH says which order it is in, so a STATIC one here was
 *  REJECTED. Two pairs differing only in body — plans carries the nav's calendar, entries lines. */
function SortControls({
  order,
  onPick,
  of,
}: {
  order: SortOrder;
  onPick: (order: SortOrder) => void;
  of: keyof typeof SORT_LABELS;
}) {
  const newest = order === 'newest';
  const label = SORT_LABELS[of][newest ? 0 : 1];
  return (
    <div className="ct-app__actions">
      <button
        type="button"
        className="ct-app__button ct-app__button--icon"
        aria-label={label}
        title={label}
        onClick={() => {
          onPick(newest ? 'oldest' : 'newest');
        }}
      >
        {of === 'plans' ? (
          newest ? (
            <IconPlanSortNewest />
          ) : (
            <IconPlanSortOldest />
          )
        ) : newest ? (
          <IconSortNewest />
        ) : (
          <IconSortOldest />
        )}
      </button>
    </div>
  );
}

export const Route = createLazyFileRoute('/_authed/diary')({ component: Diary });
