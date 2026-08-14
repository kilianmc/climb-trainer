import '@testing-library/jest-dom/vitest';

// jsdom implements almost none of the device APIs the session player will need.
// Stubs land here as those features arrive (wakeLock, AudioContext, vibrate,
// onLine) — mirroring the convention already used in portfolio-shell.

// TanStack Router scrolls on navigation and jsdom has no scrollTo, which otherwise
// prints "Not implemented" for every router test.
window.scrollTo = () => undefined;
