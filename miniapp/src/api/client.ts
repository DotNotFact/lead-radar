const API_BASE = '/api'

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

interface ErrorBody {
  detail?: string
}

/** initData передаётся из useRawInitData() вызывающим хуком - клиент сам его не читает, чтобы
 * оставаться обычной функцией, а не хуком (используется и внутри других хуков, и в тестах). */
export async function apiRequest<T>(
  path: string,
  initData: string | undefined,
  init?: RequestInit,
): Promise<T> {
  const headers: Record<string, string> = { ...(init?.headers as Record<string, string> | undefined) }
  if (initData) {
    headers.Authorization = `tma ${initData}`
  }
  if (init?.body) {
    headers['Content-Type'] = 'application/json'
  }

  const response = await fetch(`${API_BASE}${path}`, { ...init, headers })

  if (!response.ok) {
    const body: ErrorBody | null = await response.json().catch(() => null)
    throw new ApiError(response.status, body?.detail ?? `Запрос завершился ошибкой ${response.status}`)
  }

  return (await response.json()) as T
}
