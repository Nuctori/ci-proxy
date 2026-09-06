#!/bin/sh
# ci-proxy 本地快筛:push 后本地完成过滤,通过才向代理仓库发 dispatch。
# 始终 exit 0 —— 绝不阻塞 push;只决定要不要触发审码。
#
# 环境变量(写入本地 shell profile,勿入库):
#   NPC_REPO        代理仓库 owner/name
#   GH_TOKEN_NP     对代理仓库有 Contents: write 的 PAT
# 可选:
#   NPC_EVENT_TYPE  默认 npc-review
#   SKIP_KEYWORD    默认 "[auto-fix]"
#   CURSOR_PATH     相对当前仓库的游标文件(限流用,可空)
#   THROTTLE_MINUTES 默认 180(0=禁用)
#
# 用法: post-push-guard.sh <branch> <sha> <commit-msg> [repo_full_name]

branch="${1:?branch}"; sha="${2:?sha}"; msg="${3:-}"; repo_full="${4:-}"
fail() { echo "[ci-proxy-hook] 跳过: $1"; exit 0; }

# 1) 限流:读本地工作区游标(push 后工作区即最新)
throttle="${THROTTLE_MINUTES:-180}"
if [ -n "$CURSOR_PATH" ] && [ "$throttle" -gt 0 ] 2>/dev/null && [ -f "$CURSOR_PATH" ]; then
  last="$(jq -r '.lastReviewedAt // empty' "$CURSOR_PATH" 2>/dev/null \
    || grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:]+Z' "$CURSOR_PATH" 2>/dev/null | tail -n 1 || true)"
  if [ -n "$last" ]; then
    lastSec="$(date -u -d "$last" +%s 2>/dev/null || echo 0)"
    gap=$(( $(date -u +%s) - lastSec ))
    [ "$gap" -lt $(( throttle * 60 )) ] && fail "限流内(距上次 ${gap}s)"
  fi
fi

# 2) 跳过关键词
kw="${SKIP_KEYWORD:-[auto-fix]}"
[ -n "$kw" ] && case "$msg" in *"$kw"*) fail "命中关键词 $kw";; esac

# 3) 变更路径快筛:仅忽略路径变更则不触发(纯本地 git,不耗 CI)
ignored_re='^(graphic/|audio/|font/|movie/|temp/|bin/|\.godot/|docs/issues/|docs/planner/)|(\.import$|\.uid$)'
changed="$(git diff-tree --no-commit-id --name-only -r "$sha" 2>/dev/null | grep -Ev "$ignored_re" | head -n 1)"
[ -z "$changed" ] && fail "仅忽略路径变更"

# 4) dispatch
: "${NPC_REPO:?需设置 NPC_REPO}"; : "${GH_TOKEN_NP:?需设置 GH_TOKEN_NP}"
repo_full="${repo_full:-$(git config --get remote.origin.url | sed -E 's#.*(github.com[:/])##; s#\.git$##')}"
[ -n "$repo_full" ] || fail "无法解析源仓库全名"
code="$(curl -s -o /dev/null -w '%{http_code}' -X POST \
  -H "Authorization: Bearer $GH_TOKEN_NP" \
  -H "Accept: application/vnd.github+json" \
  -H "Content-Type: application/json" \
  "https://api.github.com/repos/$NPC_REPO/dispatches" \
  -d "{\"event_type\":\"${NPC_EVENT_TYPE:-npc-review}\",\"client_payload\":{\"repo\":\"$repo_full\",\"branch\":\"$branch\",\"sha\":\"$sha\",\"msg\":$(printf '%s' "$msg" | jq -Rs .)}}")"
if [ "$code" = "204" ]; then
  echo "[ci-proxy-hook] 已触发 $NPC_REPO: $sha"
else
  echo "[ci-proxy-hook] dispatch 失败 http=$code(可由 webhook 中继兜底)"
fi
exit 0
