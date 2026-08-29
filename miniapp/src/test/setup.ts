import '@testing-library/jest-dom/vitest'

import { afterAll, afterEach, beforeAll, vi } from 'vitest'

import { server } from './mocks/server'

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

// useRawInitData() бросает LaunchParamsRetrieveError вне настоящего Telegram-окружения (jsdom
// не подделывает window.Telegram.WebApp) - в компонентных тестах интересует наша логика поверх
// initData, а не собственное окружение SDK (оно тестируется его же авторами), поэтому здесь
// подменяем только этот хук фиксированным значением.
vi.mock('@telegram-apps/sdk-react', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@telegram-apps/sdk-react')>()
  return {
    ...actual,
    useRawInitData: vi.fn(() => 'mocked-init-data-for-tests'),
  }
})
