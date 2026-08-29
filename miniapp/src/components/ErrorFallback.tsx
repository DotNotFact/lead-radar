import { Placeholder } from '@telegram-apps/telegram-ui'
import type { FallbackProps } from 'react-error-boundary'

// Ловит любой render-time throw в дереве ниже - в первую очередь useRawInitData(), которая
// бросает LaunchParamsRetrieveError вне настоящего Telegram (обычный браузер, статический
// предпросмотр). Без ErrorBoundary такое открытие роняет весь экран без объяснения - нарушает
// тот же принцип "деградация, не падение", что и у бэкенда этого проекта.
export function ErrorFallback({ error }: FallbackProps) {
  const isOutsideTelegram = error instanceof Error && error.name === 'LaunchParamsRetrieveError'

  return (
    <Placeholder
      header={isOutsideTelegram ? 'Откройте это приложение в Telegram' : 'Что-то пошло не так'}
      description={
        isOutsideTelegram
          ? 'Mini App использует данные, которые Telegram передаёт только внутри своего клиента.'
          : error instanceof Error
            ? error.message
            : 'Неизвестная ошибка'
      }
    />
  )
}
