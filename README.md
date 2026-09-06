# ci-proxy

跨仓库 CI 代理:让一个"代理仓库"代替你的私有仓库跑 CI/审码负载——私有仓库保持私有,分钟数记在代理仓库所属账号的免费额度上。

```text
┌──────────────┐  post-push hook   ┌─────────────────┐  PAT 检出   ┌──────────────┐
│  私有仓库     │ ────────────────▶ │  代理仓库(可公开) │ ──────────▶ │ 目标代码在代理 │
│ (GitHub-hosted│   (本地快筛过滤)   │  npc-review.yml  │  (只读+回写) │ runner 上运行 │
│  Actions 可死)│                   └────────┬────────┘             └──────┬───────┘
└──────────────┘          ▲                  │ repository_dispatch         │
       webhook ───────────┘   issue/status/游标 ◀────────────────────────────┘
       (可选中继)              (MAIN/NPC PAT 回写)
```

- **私有仓库的 Actions 配额烧穿后照样可用**:触发来自本地 hook / webhook 中继,不依赖私有仓库自身的 Actions。
- **agent 可插拔**:内置 `pi` 调用约定,也可用 `review_command` 接任何审码/检查命令。
- **干跑模式**:`dry_run=true` 验证"调度 → 跨仓检出 → 游标回写 → commit status"四段管道,不执行 agent、零 LLM 消耗。

## 快速开始(3 步)

1. **私有初始化代理仓库**(不要 fork 公开源,直接新建私有仓库后复制本仓库内容):
   ```bash
   git clone --bare https://github.com/Nuctori/ci-proxy && cd ci-proxy.git
   git push --mirror https://github.com/<你的代理账号>/<你的私有仓库名>.git
   ```
2. **配置 secrets**(代理仓库 → Settings → Secrets and variables → Actions):
   | Secret | 说明 |
   |---|---|
   | `NPC_PAT` | 细粒度 PAT:限定**目标仓库**,`Contents: RW + Issues: RW + Commit statuses: RW` |
   | `AGENT_API_KEY` | agent 所需 API key(以 `$AGENT_API_KEY` 暴露给 `setup_command`/审码环境;pi-commandcode 约定会自动映射为 `COMMAND_CODE_API_KEY`) |
3. **触发**:
   ```bash
   gh api -X POST repos/<代理仓库>/dispatches \
     -f event_type=npc-review \
     -F 'client_payload[repo]=<目标仓库 owner/name>' \
     -F 'client_payload[branch]=main' \
     -F 'client_payload[dry_run]=true' \
     -F 'client_payload[cursor_path]=cursor.txt'
   ```
   干跑通过后再去掉 `dry_run`,带 `provider`/`model`/`setup_command` 真跑。

## 输入(dispatch 负载 `client_payload` 与 workflow_dispatch 输入同名同义)

> **平台限制**: `client_payload` 顶层最多 10 个属性。dispatch 时动态四键放顶层
> (`repo`/`branch`/`sha`/`msg`),其余配置统一收进 `client_payload.cfg` 子对象。

| 键 | 默认 | 说明 |
|---|---|---|
| `repo` / `branch` | 必填 | 目标仓库与分支 |
| `sha` | 空 | 回写 commit status 用 |
| `msg` | 空 | head commit message,参与跳过关键词过滤 |
| `cfg.dry_run` | `false` | 干跑,只走管道不跑 agent |
| `cfg.cursor_path` | 空(禁用) | 游标文件路径;`.json` 后缀写 JSON,否则写 `lastReviewedAt=...` 行 |
| `cfg.since` | `3 hours ago` | 审码窗口 |
| `cfg.context` | `npc-review` | commit status context |
| `cfg.throttle_minutes` | `180` | 基于游标的限流(0 禁用) |
| `cfg.skip_keyword` | `[auto-fix]` | 提交信息命中则秒退 |
| `cfg.fetch_depth` | `200` | 目标仓库浅克隆深度(浅克隆不裁剪工作区,只裁历史) |
| `cfg.setup_command` | 空 | agent 安装命令,例:`npm install -g @earendil-works/pi-coding-agent@x.y.z` |
| `cfg.provider` / `cfg.model` | 空 | `pi` 的 provider/model;非干跑二者与 `review_command` 至少有一组 |
| `cfg.prompt_path` | 空 | 目标仓库内的提示词文件;空则用内置通用提示词 |
| `cfg.review_command` | 空 | 自定义审码命令(cwd=目标仓库根,优先级最高) |

## 触发方式(三选一或组合)

1. **本地 post-push hook**(推荐,零额外依赖):`hooks/post-push-guard.sh`,配置 `NPC_REPO` / `GH_TOKEN_NP` 环境变量;本地先做限流/关键词/路径过滤,通过才 dispatch。
2. **workflow_dispatch**:手工或脚本带参触发,适合首次验证。
3. **webhook 中继** `relay/worker.js`(Cloudflare Workers 免费档):私有仓库 Settings → Webhooks 指向 Worker,转发 `issues` / `issue_comment` 等无法从本地触发的事件;HMAC-SHA256 校验,事件白名单 `FORWARD_EVENTS`。

## 安全边界(务必读)

- **公开的代理仓库只能当模板壳**:只要它对私有目标仓库真跑过一次审码,diff 内容就会进入公开 job log。公开存放时请 **Settings → Actions → Disable actions**;运行实例一律私有初始化。
- **PAT 最小化**:`NPC_PAT` 用 fine-grained、限定单一目标仓库、最短可行有效期(建议 90 天轮换);不要用全 scope classic token 长期挂载。
- `permissions: {}` 已收掉默认 `GITHUB_TOKEN`;所有跨仓操作都走显式 PAT,权限可审计。
- secrets 不会进入 fork PR 的运行;`repository_dispatch` 本身需要代理仓库写权限才能调用。

## FAQ

- **浅克隆会丢审码上下文吗?** 不会丢工作区——`fetch_depth` 只裁历史,HEAD 全部文件照常落盘;agent 需要更老历史时可自助 `git fetch --deepen`。
- **为什么不用 reusable workflow?** 跨仓 reusable workflow 的分钟仍记在调用方,起不到"换额度池"的作用;dispatch 模式才真正把 runner 换到代理账号。
- **游标限流的原理?** 游标文件存在目标仓库里,记录上次审码时间;guard 用 API 免检出读取,超窗才放行。

## @唤起职能角色(npc-at)

在目标仓库的 issue 评论里 `@你的bot + 职能词`,即可唤起对应职能 agent 回帖干活:

```text
@zri-review-npc 分析 这个崩溃的根因是什么   → role=analyze
@zri-review-npc 规划 拆解一下这个需求       → role=plan
@zri-review-npc 修 掉这个问题               → role=fix(需自备修复职能 playbook)
```

- 触发:`hooks/npc-mention-watch.py` 本机守望者(轮询提及,零云账号)或 webhook 中继(转发 `npc-at` 事件);
- 职能扩展 = 在目标仓库放 `docs/planner/playbooks/npc-{role}.md` 提示词文件,无需改工作流;未命中走内置通用提示词;
- 防回环:agent 回帖带 `<!-- npc-at -->` 标记且禁止再 @bot,守望者自动跳过自己的回帖。

## License

[MIT](LICENSE)
