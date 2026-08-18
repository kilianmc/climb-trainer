import { createFileRoute } from '@tanstack/react-router';

import { RouteNotFound } from '../ui/status';

// A real catch-all route, not just the root's `notFoundComponent`: that one fires for
// an explicit `notFound()`, while an unmatched URL needs somewhere to land.
export const Route = createFileRoute('/$')({ component: RouteNotFound });
