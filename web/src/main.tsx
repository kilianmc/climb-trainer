import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import App from './App';
import './styles/global.scss';

/**
 * Standalone entry (climb.kilianmc.com). The federated entry lands in PR #4 as a
 * separate `remote.tsx` sharing one route tree.
 *
 * A service worker must NEVER be registered from the federated entry — its scope
 * would be kilianmc.com and it would hijack the production portfolio.
 */
const root = document.getElementById('root');
if (!root) throw new Error('#root is missing from index.html');

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
