import React from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AppLayout } from './components/layout/AppLayout'
import { DashboardPage } from './pages/DashboardPage'
import { CopilotPage } from './pages/CopilotPage'
import { MemoryPage } from './pages/MemoryPage'
import { DocumentsPage } from './pages/DocumentsPage'
import { SyncPage } from './pages/SyncPage'
import { ConflictsPage } from './pages/ConflictsPage'
import { DevicesPage } from './pages/DevicesPage'
import { ActivityPage } from './pages/ActivityPage'
import { SettingsPage } from './pages/SettingsPage'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})

export const App: React.FC = () => {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<AppLayout />}>
            <Route index element={<DashboardPage />} />
            <Route path="copilot" element={<CopilotPage />} />
            <Route path="memory" element={<MemoryPage />} />
            <Route path="documents" element={<DocumentsPage />} />
            <Route path="sync" element={<SyncPage />} />
            <Route path="conflicts" element={<ConflictsPage />} />
            <Route path="devices" element={<DevicesPage />} />
            <Route path="activity" element={<ActivityPage />} />
            <Route path="settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

export default App
