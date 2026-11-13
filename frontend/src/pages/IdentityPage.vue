<template>
  <AppShell>
    <PageHeader
      eyebrow="一员多码 · 会员身份认定"
      title="会员身份认定"
      subtitle="把门店、私域、信息流的不同会员码认定为同一人：按最早消费月重新分群，历史订单只在首次获客渠道计一次；撤销即恢复原始分群。认定结果驱动留存矩阵、LTV 与导出。"
    >
      <template #actions>
        <button class="btn btn--quiet" type="button" data-test="identity-refresh" @click="load">
          刷新
        </button>
      </template>
    </PageHeader>

    <ErrorNotice v-if="store.error" :message="store.error" @retry="load" />

    <div v-if="store.loading && !store.overview" class="stack">
      <div class="skeleton"></div>
      <div class="skeleton skeleton--tall"></div>
    </div>

    <template v-else>
      <!-- 总览：认定前后会员数 -->
      <section class="band">
        <div class="band__cell">
          <span class="label">口径状态</span>
          <span class="band__value">
            <span class="tag" :class="store.isMerged ? 'tag--ok' : 'tag--censor'">
              {{ store.isMerged ? '认定生效中' : '原始口径' }}
            </span>
          </span>
          <span class="band__sub mono">生效认定 {{ store.overview?.active_links ?? 0 }} 组</span>
        </div>
        <div class="band__cell">
          <span class="label">原始会员码</span>
          <span class="band__value mono">{{ integer(store.overview?.members_raw ?? 0) }}</span>
          <span class="band__sub mono">认定前去重口径</span>
        </div>
        <div class="band__cell">
          <span class="label">认定后人数</span>
          <span class="band__value mono">{{ integer(store.overview?.members_effective ?? 0) }}</span>
          <span class="band__sub mono">同一人只算一个</span>
        </div>
        <div class="band__cell">
          <span class="label">重复偏高修正</span>
          <span class="band__value mono">
            {{ integer((store.overview?.members_raw ?? 0) - (store.overview?.members_effective ?? 0)) }}
          </span>
          <span class="band__sub mono">被合并的重复会员</span>
        </div>
        <div class="band__cell band__cell--note">
          <span class="label">已撤销认定</span>
          <span class="band__value mono">{{ store.overview?.revoked_links ?? 0 }}</span>
          <span class="band__sub mono">撤销后恢复原分群</span>
        </div>
      </section>

      <!-- 各群规模前后对照 -->
      <section class="panel panel--tight panel--sizes" v-if="store.overview">
        <div class="spread">
          <span class="eyebrow">各同期群规模：认定前 → 认定后</span>
          <span class="label">留存矩阵 / LTV / 导出共用此结果</span>
        </div>
        <div class="sizes scroll-x">
          <div v-for="row in store.overview.cohort_sizes" :key="row.cohort_month" class="size">
            <div class="mono size__month">{{ row.cohort_month }}</div>
            <div class="mono size__num">
              <span :class="{ 'size--strike': row.before !== row.after }">{{ row.before }}</span>
              <span v-if="row.before !== row.after" class="size__arrow">→</span>
              <strong v-if="row.before !== row.after">{{ row.after }}</strong>
            </div>
          </div>
        </div>
      </section>

      <div class="layout">
        <div class="stack">
          <!-- 最近一次操作结果提示 -->
          <div v-if="resultNotice" class="result-notice" :class="resultNotice.tone" role="status">
            <span class="tag" :class="resultNotice.tone === 'ok' ? 'tag--ok' : 'tag--censor'">
              {{ resultNotice.tag }}
            </span>
            <span>{{ resultNotice.text }}</span>
          </div>

          <!-- 认定表单（analyst / admin） -->
          <section class="panel" v-if="canWrite">
            <div class="eyebrow">新建认定</div>
            <p class="form__hint">
              输入同一人的多个会员码（逗号 / 空格 / 换行分隔，至少 2 个）。同一组码重复认定只生效一次。
            </p>
            <div class="field">
              <label class="label" for="codes">会员码</label>
              <textarea
                id="codes"
                v-model="codesText"
                rows="3"
                data-test="identity-codes-input"
                placeholder="例如：M00-0007, M03-0211, M07-0155"
              ></textarea>
            </div>
            <div class="field">
              <label class="label" for="note">备注（可选）</label>
              <input id="note" v-model="note" type="text" maxlength="400" placeholder="认定依据，如：同一手机号 / 同一会员卡" />
            </div>
            <div class="row form__foot">
              <button
                class="btn btn--solid"
                type="button"
                data-test="identity-merge"
                :disabled="store.submitting || parsedCodes.length < 2"
                @click="submitMerge"
              >
                {{ store.submitting ? '认定并重建中…' : '认定为同一人并重建矩阵' }}
              </button>
              <span class="label">识别到 {{ parsedCodes.length }} 个去重会员码</span>
            </div>
          </section>
          <section class="panel" v-else>
            <div class="eyebrow">只读账号</div>
            <p class="form__hint">当前角色可查看认定结果，认定与撤销需要分析师或负责人权限。</p>
          </section>

          <!-- 最近一次操作的前后变化 -->
          <IdentityChangePanel
            v-if="store.lastResult?.change"
            :change="store.lastResult!.change"
            :title="changeTitle"
          />
          <IdentityChangePanel
            v-if="store.lastResult?.change_before"
            :change="store.lastResult!.change_before!"
            title="撤销前口径（已恢复为上方撤销后状态）"
          />

          <!-- 认定记录列表 -->
          <section class="panel panel--tight">
            <div class="spread list__head">
              <span class="eyebrow">认定记录（{{ store.links.length }}）</span>
              <div class="row">
                <button
                  v-for="opt in statusOptions"
                  :key="opt.value"
                  class="btn btn--sm"
                  :class="{ 'btn--solid': filter === opt.value }"
                  type="button"
                  @click="applyFilter(opt.value)"
                >
                  {{ opt.label }}
                </button>
              </div>
            </div>

            <EmptyState v-if="!store.links.length" title="还没有认定记录" :hint="EMPTY_HINTS.identity" />

            <div class="scroll-x" v-else>
              <table class="table">
                <thead>
                  <tr>
                    <th>状态</th>
                    <th>统一会员（person）</th>
                    <th class="num">会员码</th>
                    <th>认定后首单月</th>
                    <th>首次获客渠道</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="link in store.links" :key="link.id">
                    <td>
                      <span class="tag" :class="link.status === 'active' ? 'tag--ok' : 'tag--censor'">
                        {{ link.status === 'active' ? '生效中' : '已撤销' }}
                      </span>
                    </td>
                    <td class="mono">{{ link.person_code }}</td>
                    <td class="num mono">{{ link.code_count }}</td>
                    <td class="mono">{{ link.first_order_month ?? '—' }}</td>
                    <td>{{ link.first_channel ? channelLabel(link.first_channel) : '—' }}</td>
                    <td>
                      <button
                        v-if="canWrite && link.status === 'active'"
                        class="btn btn--sm btn--danger"
                        type="button"
                        :data-test="`identity-revoke-${link.id}`"
                        :disabled="store.submitting"
                        @click="submitRevoke(link.id)"
                      >
                        撤销误认
                      </button>
                      <span v-else class="faint">—</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>
        </div>

        <!-- 侧栏：口径说明 + 生效认定的会员码明细 -->
        <aside class="stack">
          <section class="panel panel--tight">
            <div class="eyebrow">认定口径</div>
            <dl class="defs">
              <div><dt>重新分群</dt><dd>同一人按其全部订单的最早消费月归入一个同期群。</dd></div>
              <div><dt>渠道只计一次</dt><dd>历史订单统一计入该人最早消费月的首单渠道，其余渠道不再重复计回本。</dd></div>
              <div><dt>撤销恢复</dt><dd>撤销后各会员码恢复原始首单月分群与渠道归属，矩阵按原始口径重建。</dd></div>
              <div><dt>幂等</dt><dd>同组会员码（与顺序无关）重复认定只生效一次；撤销后允许重新认定。</dd></div>
            </dl>
          </section>

          <section class="panel panel--tight">
            <div class="eyebrow">生效认定的会员码明细</div>
            <div v-if="!store.activeLinks.length" class="faint side__empty">暂无生效认定</div>
            <div v-for="link in store.activeLinks" :key="link.id" class="linkdetail">
              <div class="spread">
                <strong class="mono">{{ link.person_code }}</strong>
                <span class="tag tag--ok">{{ link.code_count }} 码</span>
              </div>
              <div class="linkdetail__codes">
                <span v-for="code in link.member_codes" :key="code" class="mono chip">{{ code }}</span>
              </div>
            </div>
          </section>
        </aside>
      </div>
    </template>
  </AppShell>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import AppShell from '../components/common/AppShell.vue'
import PageHeader from '../components/common/PageHeader.vue'
import EmptyState from '../components/common/EmptyState.vue'
import ErrorNotice from '../components/common/ErrorNotice.vue'
import IdentityChangePanel from '../components/business/IdentityChangePanel.vue'
import { useIdentityStore } from '../stores/identityStore'
import { useAuthStore } from '../stores/authStore'
import { CHANNEL_LABELS, type ChannelCode } from '../constants/enums'
import { EMPTY_HINTS } from '../constants/messages'
import { integer } from '../utils/format'
import type { IdentityStatus } from '../types/identity'

const store = useIdentityStore()
const auth = useAuthStore()

const codesText = ref('')
const note = ref('')
const filter = ref<'all' | IdentityStatus>('all')

const canWrite = computed(() => auth.can('identity:write'))
const parsedCodes = computed(() =>
  Array.from(new Set(codesText.value.split(/[\s,，;；]+/).map((s) => s.trim()).filter(Boolean))),
)
const changeTitle = computed(() => {
  const result = store.lastResult
  if (!result) return ''
  if (result.idempotent) return '该认定已存在（重复执行未再次生效）'
  if (result.revoked) return '撤销后变化（已恢复原始分群与渠道归属）'
  return '认定前后变化'
})

const resultNotice = computed<{ tone: 'ok' | 'muted'; tag: string; text: string } | null>(() => {
  const result = store.lastResult
  if (!result) return null
  if (result.idempotent) {
    return {
      tone: 'muted',
      tag: '重复提交',
      text: `同一组会员码的认定已存在（person：${result.link.person_code}），本次未再次生效、矩阵未重建。`,
    }
  }
  if (result.revoked) {
    return {
      tone: 'ok',
      tag: '已撤销',
      text: `已撤销认定 ${result.link.person_code}，矩阵按原始分群与渠道归属重建。`,
    }
  }
  if (result.applied) {
    return {
      tone: 'ok',
      tag: '认定生效',
      text: `已认定为同一人（person：${result.link.person_code}），矩阵按最早消费月与首次获客渠道重建。`,
    }
  }
  return null
})

const statusOptions: { label: string; value: 'all' | IdentityStatus }[] = [
  { label: '全部', value: 'all' },
  { label: '生效中', value: 'active' },
  { label: '已撤销', value: 'revoked' },
]

function channelLabel(code: string): string {
  return CHANNEL_LABELS[code as ChannelCode] ?? code
}

async function load() {
  await store.load()
}

async function applyFilter(value: 'all' | IdentityStatus) {
  filter.value = value
  await store.filter(value === 'all' ? undefined : value)
}

async function submitMerge() {
  if (parsedCodes.value.length < 2) return
  try {
    const result = await store.merge(parsedCodes.value, note.value)
    if (result.idempotent) {
      store.error = ''
    }
    codesText.value = ''
    note.value = ''
  } catch {
    /* store.error 已带信息 */
  }
}

async function submitRevoke(linkId: string) {
  try {
    await store.revoke(linkId)
  } catch {
    /* store.error 已带信息 */
  }
}

onMounted(load)
</script>

<style scoped>
.band {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  border: var(--hair);
  border-bottom: 0;
  background: var(--cream-2);
}
.band__cell {
  display: flex; flex-direction: column; gap: 4px;
  padding: 11px 14px;
  border-right: var(--hair);
}
.band__cell:last-child { border-right: 0; }
.band__cell--note { background: var(--cream-3); }
.band__value { font-size: 20px; color: var(--espresso); display: flex; align-items: center; }
.band__sub { font-size: 10px; color: var(--coffee-3); }

.panel--sizes { margin-bottom: 16px; }
.sizes { display: flex; gap: 14px; overflow-x: auto; padding-top: 10px; }
.size { min-width: 86px; display: flex; flex-direction: column; gap: 3px; }
.size__month { font-size: 11px; color: var(--coffee-3); }
.size__num { font-size: 14px; display: flex; align-items: center; gap: 5px; }
.size--strike { text-decoration: line-through; color: var(--coffee-3); }
.size__arrow { color: var(--coffee-3); font-size: 11px; }

.layout {
  display: grid;
  grid-template-columns: minmax(0, 3.1fr) minmax(280px, 1fr);
  gap: 16px;
  align-items: start;
}

.form__hint { margin: 8px 0 12px; font-size: 12px; color: var(--coffee-2); }
.form__foot { margin-top: 12px; }

.result-notice {
  display: flex;
  align-items: center;
  gap: 10px;
  border: 1px solid var(--rule);
  background: var(--cream-2);
  padding: 10px 13px;
  font-size: 12.5px;
}
.result-notice.ok { border-color: var(--sage); background: var(--sage-soft); }
.result-notice.muted { border-style: dashed; color: var(--coffee-2); }

.defs { margin: 8px 0 0; display: flex; flex-direction: column; gap: 9px; }
.defs div { display: grid; grid-template-columns: 64px 1fr; gap: 8px; }
.defs dt { font-family: var(--mono); font-size: 10px; color: var(--coffee); }
.defs dd { margin: 0; font-size: 11.5px; color: var(--coffee-2); line-height: 1.5; }

.list__head { margin-bottom: 8px; }
.linkdetail { border-bottom: 1px dashed var(--rule-soft); padding: 9px 0; display: flex; flex-direction: column; gap: 7px; }
.linkdetail__codes { display: flex; flex-wrap: wrap; gap: 5px; }
.chip {
  font-size: 10.5px; border: 1px solid var(--rule);
  padding: 2px 6px; background: var(--cream);
}
.side__empty { font-size: 12px; padding: 6px 0; }

.skeleton {
  height: 90px; border: 1px dashed var(--rule); background: var(--cream-2);
  animation: pulse 1.4s ease-in-out infinite;
}
.skeleton--tall { height: 360px; }
@keyframes pulse { 0%, 100% { opacity: 0.55; } 50% { opacity: 0.9; } }

@media (max-width: 1199px) {
  .layout { grid-template-columns: 1fr; }
  .band { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 767px) {
  .band { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
