# Metaculus 预测 bot（Claude 版）操作手册

基于官方模板 `Metaculus/metac-bot-template`（2026-10-15 版，forecasting-tools 0.3.4），改动只有三处：
`bot_config.py`（全部换成 Claude）、`claude_research.py`（用 Claude 自带 web search 做研究）、`main.py`（接入 + `--no-publish` / `--max-questions`）。
其余文件与上游一致，方便以后 `git pull upstream main`。

## 0. 先确认两件事
- **奖金付款**：Metaculus 通过 Ramp 银行转账付奖金，Ramp 支持 China (CNY) 和 Hong Kong (HKD)，USD SWIFT 也支持。到账 1–5 个工作日，SWIFT 固定 $20 手续费。
- **一人一个主 bot**：第一个创建的 bot 是 primary（可拿奖），之后的都是 secondary（不上榜、不拿奖）。

## 1. 你要做的（约 20 分钟）
1. 注册 Metaculus 人类账号 → `Settings → My Forecasting Bots` → **Create Bot** → 复制 API Key，这就是 `METACULUS_TOKEN`。
2. 填参赛表 https://forms.gle/aQdYMq9Pisrf1v7d8（前 3 题必填）。表里同时申请免费额度：Metaculus 会发一个 **OpenRouter key**（约 $100 起，MiniBench 打得好会追加），设成 `OPENROUTER_API_KEY`。
   - 没拿到额度前，也可以用自己的 `ANTHROPIC_API_KEY`（直连，研究步骤会用 Claude 的联网搜索，$10/千次搜索）。
3. 可选：AskNews 额度（每月 1k 次调用）——用 bot 注册邮箱注册 asknews.app，然后发邮件到 contact@asknews.app 报 bot 名、邮箱、姓名、LinkedIn，拿到 `ASKNEWS_API_KEY`。
4. 把 key 填进 `.env`（已从模板复制好，占位符 `REPLACE_ME` 会被当作未设置）。

## 2. 本地跑
```bash
cd ~/Desktop/PartTime/metaculus-bot
.venv/bin/python smoke_test.py                                   # 离线：一道自编题，不发帖，只需 LLM key
.venv/bin/python main.py --mode test_questions --no-publish --max-questions 2   # 真题 2 道，存到 ./reports，不发帖
.venv/bin/python main.py --mode test_questions                   # 正式冒烟：在 bot-testing-area 发真预测
.venv/bin/python main.py --mode tournament                       # 秋季赛 + MiniBench，跳过已预测的题
```
看 bot 的预测：人类账号登录 → `Settings → My Forecasting Bots → Switch to bot account` → 题目页的 Private 评论。

## 2b. 2026-10-18 配置对比结果（`marketbench_configs.py`，参照 = Polymarket 市场价）

| 配置 | 第 1 轮 | 第 2 轮 | 备注 |
|---|---|---|---|
| **Grok 4.7 高推理 + Grok 4.7:online 研究** | — | **26.3** | 上线配置 |
| Grok 4.7 + DeepSeek flash:online 研究 | 11.2 | 14.6 | |
| Kimi K3 + flash:online 研究 | 15.1 | 13.0 | |
| DeepSeek V4 Pro + flash:online 研究 | 5.3 | 11.2 | |
| Grok 4.7 无研究 | 23.2 | 7.7 | 两轮差 15 分 = 样本噪声 |
| Grok 4.7:online 自带联网预测 | — | 7.7 | 单步联网不如分离研究 |
| Kimi K3 无研究 | — | 7.8 | |
| 市场自身（上限） | 30.2 | 31.3 | |

每轮 15 题、每配置 3 次采样；分数 = 把市场价当真值的期望 Baseline 分。结论：研究员的质量比预测模型更重要；
OpenAI/Anthropic/Google 对本账号 403，故候选只在 Grok/Kimi/DeepSeek 中选。两轮共花 $17.95。

## 3. 模型与成本
| 角色 | 直连 Anthropic | OpenRouter（Metaculus 额度） |
|---|---|---|
| 预测（default） | `anthropic/claude-opus-5-5` | `openrouter/anthropic/claude-opus-5.5` |
| 解析 / 摘要 | `anthropic/claude-haiku-5-5` | `openrouter/anthropic/claude-haiku-5.5` |
| 研究 | Claude web search（`claude_research.py`） | `openrouter/anthropic/claude-sonnet-5.5:online` |

每题 1 次研究 + 5 次预测 + 解析。Opus 5.5 $4/$20 per M；粗估每题 $0.15–0.40，一季 300–400 题 + MiniBench ≈ $80–200。
想省钱把 `FORECASTER_MODEL` 改成 sonnet（`.env` 里有注释）。模型全部不传 temperature（Claude 5.5 拒绝非默认采样参数）。

## 4. 挂到 GitHub Actions（免费、自动、不用本机）
仓库：**https://github.com/AuthonyL/metaculus-bot**（2026-10-19 起 public，Actions 分钟数不限；`upstream` 指向官方模板，`git pull upstream main` 可同步更新）。
1. `Settings → Secrets and variables → Actions → Secrets` 添加：
   - `METACULUS_TOKEN`（bot 账号的 token）
   - `OPENROUTER_API_KEY`
   - 可选 `ASKNEWS_API_KEY`
2. 同页 `Variables` 标签添加 `OPENROUTER_SPEND_CAP_USD`（例如 `45`）；不填则工作流默认 45。
3. `Actions` 页启用 workflows → 先手动跑 **Test Bot**（bot-testing-area）→ 到 bot 账号确认发帖 → **Forecast on new AI tournament questions** 定时跑秋季赛 + MiniBench（写的是每 20 分钟，实测 GitHub 约 2 小时才跑一次，见 4b；Metaculus Cup 的定时已关，只能手动触发）。
4. 暂停：该 workflow 右上角 `Disable workflow`。额度用完时 `budget_guard` 会让运行直接退出，不会报错刷屏。

看运行记录：https://github.com/AuthonyL/metaculus-bot/actions → 点某次运行 → `forecast_job` → 展开 `Run bot`，末尾有 `Bot submitted N forecast(s)` 和当次花费。
看预测结果：bot 主页 https://www.metaculus.com/accounts/profile/310753/（用户名 `Authony-Bot`，id 310753）；赛事页 https://www.metaculus.com/tournament/fall-futureeval-2026/ 、 https://www.metaculus.com/tournament/minibench/ 、 https://www.metaculus.com/tournament/bot-testing-area/ 。

## 4b. 外部触发器（补 GitHub 定时的延迟）
**为什么需要**：GitHub `schedule` 实测约每 2 小时跑一次（10-18 17:26 / 19:31 / 21:53、10-19 00:07），而题目只开放 **3 小时**：
正赛 53 题里 51 题是 3 小时窗口，开题时刻分布在 00/03/06/09/12/14/15/18/21 UTC 各整点；MiniBench 首批 4 题 10-19 00:19–00:46 UTC 开。
一次延迟就会整题错过，所以用 cron-job.org 每 20 分钟调一次 GitHub 的 `workflow_dispatch` 接口兜底（GitHub 自己的定时保留作备份）。

**你要做的（约 10 分钟）**
1. 建一个只能触发这个仓库 Actions 的 token：https://github.com/settings/personal-access-tokens/new
   - Token name：`metaculus-bot-trigger`；Expiration：Custom → `2027-01-31`（赛季 12 月底结束）
   - Repository access：Only select repositories → `AuthonyL/metaculus-bot`
   - Permissions → Repository permissions → **Actions: Read and write**（Metadata 会自动变成 Read）
   - Generate token → 复制（只显示一次），不要发给我，只填到下一步。
2. 注册 https://cron-job.org（免费）→ Cronjobs → **CREATE CRONJOB**：
   - Title：`metaculus-bot trigger`
   - URL：`https://api.github.com/repos/AuthonyL/metaculus-bot/actions/workflows/run_bot_on_tournament.yaml/dispatches`
   - Execution schedule：Every 20 minutes（或 Custom → Minutes 勾 0、20、40）
   - 切到 **ADVANCED** 标签：
     - Request method：**POST**
     - Headers 加 4 行：`Accept` = `application/vnd.github+json`；`Authorization` = `Bearer <第 1 步的 token>`；`X-GitHub-Api-Version` = `2022-11-28`；`Content-Type` = `application/json`
     - Request body：`{"ref":"main"}`
   - CREATE → 在该 job 页点 **TEST RUN**，状态码 **204** 即成功（GitHub 对成功的 dispatch 不返回内容）。
3. 告诉我"填完了"，我用 `gh run list` 核对出现 `workflow_dispatch` 的运行；之后 Actions 页每 20 分钟会多一条 `workflow_dispatch` 运行，空跑约 50 秒。

**Actions 分钟数**：私有仓库每月只有 2,000 分钟。实测空跑约 50 秒（按 1 分钟计费）、带 1 题约 10 分钟；
每天 3–6 道正赛 + ~4 道 MiniBench，再加每 20 分钟一次空跑，约需 **4,000+ 分钟/月**，超额后 Actions 直接停跑。
所以 2026-10-19 已改成 public，分钟数不限（改之前扫过全部 97 个提交：`.env` 从未提交，无任何 key 模式；密钥都在 GitHub Secrets，预测结果在被忽略的 `reports/`）。
注意 public 仓库的 `schedule` 会在 60 天无提交后被自动禁用，但 cron-job.org 走的 `workflow_dispatch` 不受影响。

## 5. 规则红线
- 全自动，人不能改 bot 的预测，也不能用自己的判断去调它。
- 每题必须留评论（模板已做）。
- 拿奖要填赛季问卷、提供代码或说明，接受 Metaculus 检查；商业机构的闭源 bot 不能拿奖。
- 不要把 `.env` 提交到 git（已在 .gitignore）。

## 6. 下一步可做的改进（都在官方开源 bot 列表里有先例）
- 多模型/多次研究取中位数；按问题类型调整 prompt；对日期/数值题加 Fermi 估计；接 AskNews 做新闻研究；用 `review-bot` skill 复盘已结算题。
