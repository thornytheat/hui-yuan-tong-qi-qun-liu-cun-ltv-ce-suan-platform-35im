import { defineStore } from 'pinia'
import {
  fetchIdentityLinks,
  fetchIdentityOverview,
  mergeMemberCodes,
  revokeIdentityLink,
} from '../api/identity'
import type {
  IdentityActionResult,
  IdentityLink,
  IdentityOverview,
  IdentityStatus,
} from '../types/identity'

interface IdentityState {
  overview: IdentityOverview | null
  links: IdentityLink[]
  loading: boolean
  submitting: boolean
  error: string
  lastResult: IdentityActionResult | null
}

export const useIdentityStore = defineStore('identity', {
  state: (): IdentityState => ({
    overview: null,
    links: [],
    loading: false,
    submitting: false,
    error: '',
    lastResult: null,
  }),
  getters: {
    activeLinks: (state): IdentityLink[] => state.links.filter((l) => l.status === 'active'),
    revokedLinks: (state): IdentityLink[] => state.links.filter((l) => l.status === 'revoked'),
    isMerged: (state): boolean => state.overview?.identity_mode === 'merged',
  },
  actions: {
    async load() {
      this.loading = true
      this.error = ''
      try {
        const [overview, links] = await Promise.all([
          fetchIdentityOverview(),
          fetchIdentityLinks(),
        ])
        this.overview = overview
        this.links = links.items
      } catch (error) {
        this.error = (error as { message?: string }).message ?? '加载认定数据失败'
      } finally {
        this.loading = false
      }
    },
    async filter(status: IdentityStatus | undefined) {
      this.loading = true
      try {
        const links = await fetchIdentityLinks(status)
        this.links = links.items
      } catch (error) {
        this.error = (error as { message?: string }).message ?? '加载认定记录失败'
      } finally {
        this.loading = false
      }
    },
    async merge(codes: string[], note: string) {
      this.submitting = true
      this.error = ''
      try {
        const result = await mergeMemberCodes(codes, note)
        this.lastResult = result
        await this.load()
        return result
      } catch (error) {
        this.error = (error as { message?: string }).message ?? '认定失败'
        throw error
      } finally {
        this.submitting = false
      }
    },
    async revoke(linkId: string) {
      this.submitting = true
      this.error = ''
      try {
        const result = await revokeIdentityLink(linkId)
        this.lastResult = result
        await this.load()
        return result
      } catch (error) {
        this.error = (error as { message?: string }).message ?? '撤销失败'
        throw error
      } finally {
        this.submitting = false
      }
    },
    clearLastResult() {
      this.lastResult = null
    },
  },
})
