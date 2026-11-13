"""审计动作名、口径说明文案（前端只展示后端回传的文案，不另写一份）。"""
from __future__ import annotations

ACTION_LOGIN = "auth.login"
ACTION_LOGIN_FAILED = "auth.login_failed"
ACTION_REBUILD = "matrix.rebuild"
ACTION_LTV_RUN = "ltv.run"
ACTION_LTV_PUBLISH = "ltv.publish"
ACTION_EXPORT = "export.download"
ACTION_FORBIDDEN = "auth.forbidden"
ACTION_IDENTITY_MERGE = "identity.merge"
ACTION_IDENTITY_REVOKE = "identity.revoke"

METRIC_NOTES: dict[str, str] = {
    "matrix": "按首单月分群；Mn = 第 n 个月有过 ≥1 单的会员数 / 群规模；观察期未到的格子标右删失，不参与拟合。",
    "fit": "ARPU 留存 R_m = a·exp(-λm)；λ 在 [0.02, 0.60] 上 0.001 步长网格搜索，权重 = 群规模，a 为给定 λ 的闭式解。",
    "ltv_hist": "历史 LTV = 群内观察期累计营收 / 群规模，跨群按会员数加权。",
    "ltv_pred": "预测 12 月 LTV = ARPU₀ × Σ_{m=0..11} a·exp(-λm)。",
    "payback": "回本周期 = CAC / 月均毛利贡献；月均毛利贡献 = 观察期人均月营收 × 毛利率（默认 50%）。",
    "low_sample": "群或「群×渠道」样本 < 30 标 low_sample，不进入渠道排行。",
    "identity": "多会员码认定为一人后按最早消费月重新分群；历史订单仅在该人首次获客渠道计一次；撤销认定即恢复原始分群与渠道归属。",
}

IDENTITY_NOTES: dict[str, str] = {
    "merge": "认定为同一人后，按最早消费月重新分群；历史订单只在首次获客渠道计一次，留存矩阵、LTV 与导出共用同一结果。",
    "revoke": "撤销后该组会员码恢复各自原始分群与渠道归属；同一组会员码的认定重复执行只生效一次。",
}
