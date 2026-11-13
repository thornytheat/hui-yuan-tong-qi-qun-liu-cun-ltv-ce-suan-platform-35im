/** 一员多码认定相关类型（与 backend src/schemas/identity.py 同构）。 */

export type IdentityStatus = 'active' | 'revoked'
export type IdentityMode = 'raw' | 'merged'

export interface IdentityLink {
  id: string
  person_code: string
  member_codes: string[]
  code_count: number
  status: IdentityStatus
  fingerprint: string
  first_order_month: string | null
  first_channel: string | null
  note: string
  created_by: string
  revoked_by: string
  created_at: string
  revoked_at: string | null
}

export interface CohortSizeChange {
  cohort_month: string
  before: number
  after: number
  delta: number
}

export interface PersonCodeBefore {
  member_code: string
  first_order_month: string
  channel: string
  orders: number
}

export interface PersonChange {
  codes: PersonCodeBefore[]
  before: {
    first_order_months: string[]
    channels: string[]
  }
  after: {
    person_code: string
    first_order_month: string
    channel: string
    orders: number
  } | null
  moved_cohort: boolean
}

export interface IdentityChange {
  members_before: number
  members_after: number
  cohort_size_changes: CohortSizeChange[]
  persons: PersonChange[]
}

export interface IdentityActionResult {
  idempotent: boolean
  applied?: boolean
  revoked?: boolean
  link: IdentityLink
  rebuild: Record<string, unknown> | null
  change: IdentityChange | null
  change_before?: IdentityChange | null
}

export interface IdentityOverview {
  active_links: number
  revoked_links: number
  members_raw: number
  members_effective: number
  members_before: number
  members_after: number
  identity_mode: IdentityMode
  cohort_sizes: { cohort_month: string; before: number; after: number }[]
}
