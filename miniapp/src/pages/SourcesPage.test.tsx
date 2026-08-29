import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AppRoot } from '@telegram-apps/telegram-ui'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import type { ReactElement } from 'react'
import { describe, expect, it } from 'vitest'

import { server } from '../test/mocks/server'
import { SourcesPage } from './SourcesPage'

function renderWithClient(ui: ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <AppRoot>{ui}</AppRoot>
    </QueryClientProvider>,
  )
}

describe('SourcesPage', () => {
  it('показывает загруженные источники по их читаемым названиям', async () => {
    renderWithClient(<SourcesPage />)

    expect(await screen.findByText('hh.ru')).toBeInTheDocument()
    expect(screen.getByText('Freelancer.com')).toBeInTheDocument()
  })

  it('показывает состояние здоровья источника', async () => {
    renderWithClient(<SourcesPage />)

    expect(await screen.findByText(/Опрошен:/)).toBeInTheDocument()
    expect(screen.getByText('Ещё не опрашивался')).toBeInTheDocument()
  })

  it('помечает источник, для включения которого нужен перезапуск', async () => {
    renderWithClient(<SourcesPage />)

    await screen.findByText('Freelancer.com')
    expect(screen.getByText('!')).toBeInTheDocument()
  })

  it('переключает источник и отражает новое состояние без перезагрузки страницы', async () => {
    renderWithClient(<SourcesPage />)
    await screen.findByText('hh.ru')

    const hhSwitch = screen.getAllByRole('checkbox')[0]
    expect(hhSwitch).toBeChecked()

    await userEvent.click(hhSwitch)

    await waitFor(() => expect(hhSwitch).not.toBeChecked())
  })

  it('показывает сообщение об ошибке, если сервер недоступен', async () => {
    server.use(
      http.get('/api/sources', () => HttpResponse.json({ detail: 'сервер недоступен' }, { status: 500 })),
    )

    renderWithClient(<SourcesPage />)

    expect(await screen.findByText('Не удалось загрузить источники')).toBeInTheDocument()
    expect(screen.getByText('сервер недоступен')).toBeInTheDocument()
  })
})
