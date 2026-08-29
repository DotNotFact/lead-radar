import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRawInitData } from '@telegram-apps/sdk-react'

import { apiRequest } from './client'
import type { SourceStatus } from './types'

const SOURCES_KEY = ['sources'] as const

export function useSourcesQuery() {
  const initData = useRawInitData()
  return useQuery({
    queryKey: SOURCES_KEY,
    queryFn: () => apiRequest<SourceStatus[]>('/sources', initData),
    // Источники опрашиваются в фоне процессом каждые несколько минут - раз в 30с достаточно,
    // чтобы статус в Mini App не выглядел застывшим, не заваливая сервер лишними запросами.
    refetchInterval: 30_000,
  })
}

interface ToggleVariables {
  id: string
  enabled: boolean
}

export function useToggleSourceMutation() {
  const initData = useRawInitData()
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ id, enabled }: ToggleVariables) =>
      apiRequest<SourceStatus>(`/sources/${id}/toggle`, initData, {
        method: 'POST',
        body: JSON.stringify({ enabled }),
      }),
    onSuccess: (updated) => {
      queryClient.setQueryData<SourceStatus[]>(SOURCES_KEY, (current) =>
        current?.map((source) => (source.id === updated.id ? updated : source)),
      )
    },
  })
}
