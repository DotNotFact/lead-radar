import { Badge, Cell, List, Placeholder, Section, Spinner, Switch } from '@telegram-apps/telegram-ui'
import type { ChangeEvent } from 'react'

import { useSourcesQuery, useToggleSourceMutation } from '../api/sources'
import type { SourceStatus } from '../api/types'

const SOURCE_LABELS: Record<string, string> = {
  hh_ru: 'hh.ru',
  kwork_projects: 'Kwork — проекты',
  kwork_catalog: 'Kwork — каталог',
  remoteok: 'RemoteOK',
  freelancer: 'Freelancer.com',
  rss_remote_jobs: 'RSS (We Work Remotely)',
  telegram: 'Telegram-чаты',
}

function statusText(source: SourceStatus): string {
  if (source.consecutive_failures > 0) {
    return `Сбоев подряд: ${source.consecutive_failures}`
  }
  if (source.last_ok_at) {
    return `Опрошен: ${new Date(source.last_ok_at).toLocaleString('ru-RU')}`
  }
  return 'Ещё не опрашивался'
}

export function SourcesPage() {
  const { data: sources, isPending, isError, error } = useSourcesQuery()
  const toggle = useToggleSourceMutation()

  if (isPending) {
    return (
      <Placeholder header="Загрузка источников">
        <Spinner size="l" />
      </Placeholder>
    )
  }

  if (isError) {
    return (
      <Placeholder
        header="Не удалось загрузить источники"
        description={error instanceof Error ? error.message : 'Неизвестная ошибка'}
      />
    )
  }

  return (
    <List>
      <Section
        header="Источники лидов"
        footer="Выключение уже запущенного источника действует сразу. Включение источника,
          отмеченного «!» (выключен при старте процесса или не хватает данных для входа),
          требует перезапуска бота."
      >
        {sources.map((source) => {
          const isTogglingThis = toggle.isPending && toggle.variables?.id === source.id
          return (
            <Cell
              key={source.id}
              subtitle={statusText(source)}
              titleBadge={
                source.requires_restart_to_enable ? (
                  <Badge type="number" mode="critical">
                    !
                  </Badge>
                ) : undefined
              }
              after={
                <Switch
                  checked={source.enabled}
                  disabled={isTogglingThis}
                  onChange={(event: ChangeEvent<HTMLInputElement>) =>
                    toggle.mutate({ id: source.id, enabled: event.target.checked })
                  }
                />
              }
            >
              {SOURCE_LABELS[source.id] ?? source.id}
            </Cell>
          )
        })}
      </Section>
    </List>
  )
}
