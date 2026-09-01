import { registerSW } from 'virtual:pwa-register';

// ⚠️ Reachable from `main.tsx` ONLY: `remote.tsx` shares the route tree, so a registration from
// there would be scoped to kilianmc.com. `remote.guard.test.tsx` is the detector.
export function registerServiceWorker(): void {
  registerSW();
}
