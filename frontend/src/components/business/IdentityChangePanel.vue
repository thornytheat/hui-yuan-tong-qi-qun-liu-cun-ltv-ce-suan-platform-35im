<template>
  <div v-if="change" class="cmp panel panel--tight rise">
    <div class="spread">
      <span class="eyebrow">{{ title }}</span>
      <span class="tag" :class="change.members_after <= change.members_before ? 'tag--ok' : 'tag--warn'">
        去重人数 {{ change.members_before }} → {{ change.members_after }}
        <template v-if="change.members_before - change.members_after">
          （减少 {{ change.members_before - change.members_after }} 人）
        </template>
      </span>
    </div>

    <div class="cmp__section">
      <div class="label">各同期群规模变化（按最早消费月重新分群）</div>
      <div class="scroll-x">
        <table class="table">
          <thead>
            <tr>
              <th>首单月</th>
              <th class="num">认定前</th>
              <th class="num">认定后</th>
              <th class="num">变化</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in change.cohort_size_changes.filter((r) => r.before !== r.after)"
              :key="row.cohort_month"
            >
              <td class="mono">{{ row.cohort_month }}</td>
              <td class="num mono">{{ row.before }}</td>
              <td class="num mono">{{ row.after }}</td>
              <td class="num mono" :class="deltaClass(row.delta)">{{ deltaLabel(row.delta) }}</td>
            </tr>
            <tr v-if="!change.cohort_size_changes.some((r) => r.before !== r.after)">
              <td colspan="4" class="muted">群规模无变化</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="cmp__section">
      <div class="label">会员级首单月 / 渠道归属变化（历史订单只在首次获客渠道计一次）</div>
      <div class="persons">
        <article v-for="(person, idx) in change.persons" :key="idx" class="person">
          <div class="person__head">
            <span class="tag" :class="person.moved_cohort ? 'tag--warn' : 'tag--ok'">
              {{ person.moved_cohort ? '跨群重分' : '同群归并' }}
            </span>
            <span class="mono person__root">{{ person.after?.person_code }}</span>
          </div>
          <div class="person__codes">
            <div v-for="code in person.codes" :key="code.member_code" class="person__code">
              <span class="mono">{{ code.member_code }}</span>
              <span class="faint">
                首单 {{ code.first_order_month }} · {{ channelLabel(code.channel) }} · {{ code.orders }} 单
              </span>
            </div>
          </div>
          <div v-if="person.after" class="person__after">
            认定后 → 首单月 <strong class="mono">{{ person.after.first_order_month }}</strong>
            ，统一渠道 <strong>{{ channelLabel(person.after.channel) }}</strong>
            ，共 {{ person.after.orders }} 单
          </div>
        </article>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { IdentityChange } from '../../types/identity'
import { CHANNEL_LABELS, type ChannelCode } from '../../constants/enums'

defineProps<{ change: IdentityChange | null; title: string }>()

function channelLabel(code: string): string {
  return CHANNEL_LABELS[code as ChannelCode] ?? code
}

function deltaLabel(delta: number): string {
  if (delta === 0) return '0'
  return delta > 0 ? `+${delta}` : `${delta}`
}

function deltaClass(delta: number): string {
  if (delta > 0) return 'delta-up'
  if (delta < 0) return 'delta-down'
  return ''
}
</script>

<style scoped>
.cmp { display: flex; flex-direction: column; gap: 14px; }
.cmp__section { display: flex; flex-direction: column; gap: 7px; }
.persons { display: flex; flex-direction: column; gap: 10px; }
.person { border: 1px dashed var(--rule); padding: 10px 12px; background: var(--cream); }
.person__head { display: flex; align-items: center; gap: 9px; margin-bottom: 7px; }
.person__root { font-size: 12px; font-weight: 600; }
.person__codes { display: flex; flex-direction: column; gap: 4px; margin-bottom: 7px; }
.person__code { display: flex; gap: 8px; flex-wrap: wrap; font-size: 12px; }
.person__after { font-size: 12px; color: var(--coffee-2); border-top: 1px dashed var(--rule-soft); padding-top: 7px; }
.delta-up { color: var(--sage); }
.delta-down { color: var(--brick); }
</style>
