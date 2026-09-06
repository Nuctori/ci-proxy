# 部署指南(私有实例初始化清单)

> 原则:本仓库(若公开)只当模板壳,运行实例一律**私有初始化**。

## 1. 私有实例

在**承载账号**(即想用其免费额度的账号)下新建私有仓库,复制本仓库全部内容推送上去。不要 fork(fork 会继承公开可见性且锁死)。

## 2. 目标仓库侧:签发 NPC_PAT

浏览器开 `https://github.com/settings/personal-access-tokens/new`(以**有目标仓库权限的账号**登录):

- Resource owner:目标仓库所属账号/组织
- Repository access:**Only select repositories** → 只勾目标仓库
- Permissions(Repository permissions):
  - `Contents: Read and write` —— 检出代码 + 推回游标
  - `Issues: Read and write` —— 开/评审码 issue
  - `Commit statuses: Read and write` —— 回写门禁 status
- Expiration:90 天(记轮换日历)

## 3. 代理仓库侧:配置 secrets

Settings → Secrets and variables → **Actions** → New repository secret:

| Name | 值 |
|---|---|
| `NPC_PAT` | 第 2 步的 PAT |
| (agent key,如 `COMMAND_CODE_API_KEY`) | 按 `setup_command` 引用自定 |

## 4. 触发接线

### 4a. 本地 hook(push 类事件,推荐)

```bash
# 放入源仓库 hooks 目录 or PATH,并接线到 post-push;环境变量写本地 profile:
export NPC_REPO="<代理仓库 owner/name>"
export GH_TOKEN_NP="<对代理仓库有 Contents: write 的 PAT>"
# 可选:CURSOR_PATH / THROTTLE_MINUTES / SKIP_KEYWORD / NPC_EVENT_TYPE
```

git 侧:`core.hooksPath` 指到含 `post-push` 的目录,post-push 末尾调用:

```bash
branch="$(git rev-parse --abbrev-ref HEAD)"; sha="$(git rev-parse HEAD)"
msg="$(git log -1 --format=%s)"
hooks/post-push-guard.sh "$branch" "$sha" "$msg" &
```

### 4b. workflow_dispatch

适合首次验证与手动补跑,参数见 README 输入表。

### 4c. webhook 中继(issues / issue_comment 等界面事件)

1. Cloudflare Workers 创建 Worker,粘贴 `relay/worker.js`;
2. Variables:`PROXY_REPO` / `EVENT_TYPE` / `FORWARD_EVENTS`;Secrets:`WEBHOOK_SECRET` / `DISPATCH_PAT`(对代理仓库 `Contents: write`);
3. 源仓库 Settings → Webhooks → Add webhook:Payload URL 指 Worker,Content type `application/json`,Secret 同 `WEBHOOK_SECRET`,事件按 `FORWARD_EVENTS` 勾选(需源仓库 repo admin)。

## 5. 首验(干跑)

```bash
gh api -X POST repos/<代理仓库>/dispatches \
  -f event_type=npc-review \
  -F 'client_payload[repo]=<目标仓库>' \
  -F 'client_payload[branch]=main' \
  -F 'client_payload[dry_run]=true' \
  -F 'client_payload[cursor_path]=cursor.txt' \
  -F "client_payload[sha]=$(gh api repos/<目标仓库>/commits/main --jq .sha)"
```

验收点:①run 绿;②目标仓库出现 `chore: npc-review cursor` 新提交;③目标 SHA 上出现 `npc-review` context 的 success status。四段管道全部打通后,再配 `setup_command`+`provider`+`model`(或 `review_command`)转真跑。

## 6. 运维

- PAT 到期前 7 天轮换,同步更新代理仓库 secrets;
- 每月看一眼代理账号 Actions 用量;贴近免费额度再考虑扩池(新账号再初始化一个实例);
- 干跑随时可重跑,不消耗 LLM、不动目标仓库代码(只动游标文件)。
