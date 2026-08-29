import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useRawInitData } from '@telegram-apps/sdk-react'
import { AppRoot } from '@telegram-apps/telegram-ui'
import { render, screen } from '@testing-library/react'
import { ErrorBoundary } from 'react-error-boundary'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { SourcesPage } from '../pages/SourcesPage'
import { ErrorFallback } from './ErrorFallback'

// Ровно та ошибка, которую реально бросает useRawInitData() из @telegram-apps/sdk-react, если
// приложение открыто не внутри Telegram (подтверждено живым прогоном в браузере вне Telegram -
// см. main.tsx: initTelegramSdk() перехватывает её же при монтировании SDK).
function launchParamsRetrieveError(): Error {
  const error = new Error('Unable to retrieve launch parameters from any known source.')
  error.name = 'LaunchParamsRetrieveError'
  return error
}

describe('ErrorFallback via ErrorBoundary', () => {
  // mockImplementationOnce не годится здесь: React 18 в dev-режиме повторно вызывает
  // упавший компонент перед тем, как показать fallback (чтобы получить более точный стек) -
  // "once"-реализация успевает вернуться к штатной ещё до того, как ErrorBoundary решит,
  // что рендер действительно провалился. mockImplementation (постоянная) + откат в afterEach.
  afterEach(() => {
    vi.mocked(useRawInitData).mockImplementation(() => 'mocked-init-data-for-tests')
  })

  it('показывает понятное сообщение вместо падения всего дерева вне Telegram', () => {
    vi.mocked(useRawInitData).mockImplementation(() => {
      throw launchParamsRetrieveError()
    })

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <AppRoot>
          <ErrorBoundary FallbackComponent={ErrorFallback}>
            <SourcesPage />
          </ErrorBoundary>
        </AppRoot>
      </QueryClientProvider>,
    )

    expect(screen.getByText('Откройте это приложение в Telegram')).toBeInTheDocument()
    expect(screen.queryByText('Не удалось загрузить источники')).not.toBeInTheDocument()
  })

  it('показывает общее сообщение об ошибке для любых других исключений', () => {
    vi.mocked(useRawInitData).mockImplementation(() => {
      throw new Error('что-то совсем неожиданное')
    })

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <AppRoot>
          <ErrorBoundary FallbackComponent={ErrorFallback}>
            <SourcesPage />
          </ErrorBoundary>
        </AppRoot>
      </QueryClientProvider>,
    )

    expect(screen.getByText('Что-то пошло не так')).toBeInTheDocument()
    expect(screen.getByText('что-то совсем неожиданное')).toBeInTheDocument()
  })
})
