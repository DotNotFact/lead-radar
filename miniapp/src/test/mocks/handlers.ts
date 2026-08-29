import { http, HttpResponse } from 'msw'

import type { SourceStatus } from '../../api/types'

export const sampleSources: SourceStatus[] = [
  {
    id: 'hh_ru',
    tier: 1,
    enabled: true,
    poll_interval: 300,
    last_ok_at: '2026-08-29T10:00:00Z',
    last_error: null,
    consecutive_failures: 0,
    requires_restart_to_enable: false,
  },
  {
    id: 'freelancer',
    tier: 1,
    enabled: false,
    poll_interval: 900,
    last_ok_at: null,
    last_error: null,
    consecutive_failures: 0,
    requires_restart_to_enable: true,
  },
]

export const handlers = [
  http.get('/api/sources', () => HttpResponse.json(sampleSources)),

  http.post('/api/sources/:id/toggle', async ({ params, request }) => {
    const body = (await request.json()) as { enabled: boolean }
    const source = sampleSources.find((item) => item.id === params.id)
    if (!source) {
      return HttpResponse.json({ detail: `Неизвестный источник: ${params.id}` }, { status: 404 })
    }
    return HttpResponse.json({ ...source, enabled: body.enabled })
  }),
]
