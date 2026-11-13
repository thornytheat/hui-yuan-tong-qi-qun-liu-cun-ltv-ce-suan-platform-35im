import http from './http'
import type {
  IdentityActionResult,
  IdentityLink,
  IdentityOverview,
  IdentityStatus,
} from '../types/identity'

export async function fetchIdentityOverview(): Promise<IdentityOverview> {
  const { data } = await http.get<IdentityOverview>('/identity/overview')
  return data
}

export async function fetchIdentityLinks(
  status?: IdentityStatus,
): Promise<{ total: number; items: IdentityLink[] }> {
  const { data } = await http.get('/identity/links', {
    params: status ? { status } : {},
  })
  return data
}

export async function mergeMemberCodes(
  memberCodes: string[],
  note = '',
): Promise<IdentityActionResult> {
  const { data } = await http.post<IdentityActionResult>('/identity/links', {
    member_codes: memberCodes,
    note,
  })
  return data
}

export async function revokeIdentityLink(linkId: string): Promise<IdentityActionResult> {
  const { data } = await http.post<IdentityActionResult>(`/identity/links/${linkId}/revoke`, {})
  return data
}
