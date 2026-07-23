import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

// Skeleton entry point. Real UI (screens, Zustand store, 3D twin) and
// ESLint/Prettier are set up in issue #38.
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <h1>26_HP015 Dashboard</h1>
  </StrictMode>,
)
