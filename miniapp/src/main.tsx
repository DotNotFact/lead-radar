import '@telegram-apps/telegram-ui/dist/styles.css'
import './index.css'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { bindMiniAppCssVars, bindThemeParamsCssVars, init, mountMiniApp, mountThemeParams } from '@telegram-apps/sdk-react'
import { AppRoot } from '@telegram-apps/telegram-ui'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { ErrorBoundary } from 'react-error-boundary'

import { App } from './App'
import { ErrorFallback } from './components/ErrorFallback'

function initTelegramSdk(): void {
  try {
    init()
    mountMiniApp()
    mountThemeParams()
    bindMiniAppCssVars()
    bindThemeParamsCssVars()
  } catch (error) {
    // Вне Telegram (обычная разработка в браузере) SDK не может примонтироваться - приложение
    // остаётся рабочим со стандартной темой telegram-ui, а не падает.
    console.warn('Telegram SDK недоступен, использую тему по умолчанию', error)
  }
}

initTelegramSdk()

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AppRoot>
        <ErrorBoundary FallbackComponent={ErrorFallback}>
          <App />
        </ErrorBoundary>
      </AppRoot>
    </QueryClientProvider>
  </StrictMode>,
)
