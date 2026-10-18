# Metaculus FutureEval bot：实施方案（2026-10-18）

定位：**低投入副项目**。目标第一季（Fall 2026，到 12 月底）进前 20（推算约 $1k），第二季冲前 10。
现金投入 ≈ 0（官方额度先付，自费上限每月 $50），人力投入：首周约 10 小时，之后每季一轮迭代。

## 阶段 0 · 开户（你，约 30 分钟）
1. metaculus.com 注册人类账号 → Settings → My Forecasting Bots → Create Bot → 复制 token（`METACULUS_TOKEN`）。bot 名字就是榜上的名字，第一个 bot 是主 bot。
2. 填参赛表 forms.gle/aQdYMq9Pisrf1v7d8（3 道必答），同一张表勾选申请 LLM 额度 → 收到 `OPENROUTER_API_KEY`（起步约 $100，滚动审核）。
3. 可选：AskNews 额度（用 bot 注册邮箱注册 asknews.app，邮件 contact@asknews.app 报 bot 名/邮箱/姓名/LinkedIn）→ `ASKNEWS_API_KEY`。
4. 把三个 key 填进 `metaculus-bot/.env`，告诉我。
5. 收款：赛季结束后 Metaculus 发问卷 + Ramp 付款指引，填 W-8BEN，港卡收 HKD 或 USD。

## 阶段 1 · 跑通（我，拿到 key 当天）
- `smoke_test.py`：一道自编题离线走完研究→预测→解析。
- `main.py --mode test_questions --no-publish --max-questions 2`：两道真题干跑，存 `reports/`，不发帖。
- `main.py --mode test_questions`：在 bot-testing-area 正式发帖（测试区不计分），到 bot 账号页确认预测和评论都在。
- 建私有 GitHub 仓库，填 secrets，跑一次 Test Bot workflow。
- 交付：bot 能自动收题、答题、发帖、留评论。

## 阶段 2 · 选配置（我，第 1 周，约 $50–100 额度）
原则：**不预设厂商，按数据选**。春季赛证据：高推理档最重要；Claude Opus 无相关性、GPT-5.x 最强；研究质量是瓶颈；多次采样和 extremize 无益。
- 工具：forecasting-tools 自带 `Benchmarker`（需装可选包 `openai-agents`），在当前**开放中**的题上跑各配置，以社区预测为基准算期望分——没有"搜到答案"的泄漏问题，也不用等结算。
- 候选（各跑约 60 题）：
  | 配置 | 预测模型 | 研究 |
  |---|---|---|
  | A | GPT-5.x 高推理（OpenRouter） | Sonnet 5.5 `:online` |
  | B | Claude Opus 5.5 | Claude web search |
  | C | 配置 A 的模型 | A + AskNews 双源 |
  | D | 配置 A 的模型 | 无研究（对照组，看研究值多少分） |
- 固定项：裁剪 [0.03, 0.97]；3 次采样取中位数（5 次与 3 次差异不显著，先省钱）；不 extremize；prompt 保留"重押现状 + 先写参考类基率"。
- 产出：一张配置×分数表，选一个上线。

## 阶段 3 · 上线（第 2 周起）
- GitHub Actions 每 20 分钟轮询秋季赛 + MiniBench（模板自带）。rc_trader 反馈 GitHub cron 实际只触发约 5 次/天，若观察到同样问题改用 Cloudflare Worker 定时触发。
- 预算：额度优先，用完自动切自费 key，自费月上限 $50（代码里硬性封顶）。
- 两周后看第一期 MiniBench 名次：这是最早的真实反馈。

## 阶段 4 · 迭代（每两周看 MiniBench，每季一轮）
按证据排序的改进项：
1. 研究加来源：查 Metaculus 相似题、Polymarket/Kalshi 公开赔率（相关性 +0.34）；自写网页抓取（+0.33）。
2. MiniBench 数据题走代码路径：题目直接指向 FRED/股价序列，拉数据外推比让 LLM 猜准。
3. 校准：定期用 `review-bot` skill 复盘已结算题，看是否系统性过度自信。
4. 不做：多模型集成、情景分析、自我批评——数据说无效。

## 成功 / 止损标准
- 两期 MiniBench 后进不了前 1/3 → 换配置再试一轮；仍不行 → 维持模板跑着，不再投时间。
- 赛季结束前 20 以内 → 继续；30 名以外 → 降为"零维护挂机"。

## 风险
- **规则**：全自动、必留评论、一人一主 bot、赛季问卷必填、拿奖要交代码或说明。
- **运维**：GitHub cron 不准；搜索结果噪声；额度耗尽后的自费封顶要可靠；Metaculus 限流约 5 次/秒。
- **评估**：以社区预测为基准的分数只是代理，真分数要等题目结算（60 天内分批出）。

## 分工
- 你：账号、参赛表、额度、AskNews、GitHub secrets、收款。
- 我：全部代码、测试、配置对比、上线、迭代与复盘。
