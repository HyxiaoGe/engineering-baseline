# 会造成 Review Churn 的旧策略

- 每次新提交后立即评论 `@codex review`，上一轮尚未结束也继续触发。
- 每个 finding 单独修复、push，再完整审查一次。
- 只有收到 👍 才算通过，文字通过仍继续请求 Review。
