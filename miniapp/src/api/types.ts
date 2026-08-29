export interface SourceStatus {
  id: string
  tier: number
  enabled: boolean
  poll_interval: number
  last_ok_at: string | null
  last_error: string | null
  consecutive_failures: number
  requires_restart_to_enable: boolean
}

export interface ToggleSourceRequest {
  enabled: boolean
}
