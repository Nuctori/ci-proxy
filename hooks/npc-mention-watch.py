#!/usr/bin/env python3
# npc-mention-watch — 本机守望者(v1 触发器):轮询目标仓库对 @bot 的提及,唤起职能 NPC。
# 零云账号、零 GitHub Actions 分钟;云中继(webhook)上线后本脚本退役,dispatch 契约不变。
#
# 用法: npc-mention-watch.sh 常驻;环境变量见 CONFIG。
# 状态: ~/.cache/npc-mention-last-id.json 记录已处理评论 id(重启不重放)。
# 依赖: gh 登录态(对代理仓有 Contents:write,对 watched 仓可读)。

import json
import os
import re
import subprocess
import sys
import time

CONFIG = {
    "watch_repo": os.environ.get("WATCH_REPO", "Zero-Research-Institute/Touhou-Koi-Mystery"),
    "npc_repo": os.environ.get("NPC_REPO", "zri-review-npc/ci-proxy"),
    "bot": os.environ.get("BOT_USERNAME", "zri-review-npc"),
    "event_type": os.environ.get("NPC_EVENT_TYPE", "npc-at"),
    "interval": int(os.environ.get("INTERVAL", "60")),
    "page_size": 30,
    "state_file": os.environ.get(
        "STATE_FILE", os.path.expanduser("~/.cache/npc-mention-last-id.json")
    ),
    # agent 栈配置(随 dispatch 携带;环境变量可覆盖)
    "cfg_provider": os.environ.get("CFG_PROVIDER", "commandcode"),
    "cfg_model": os.environ.get("CFG_MODEL", "meta/muse-spark-1.2-contributor"),
    "cfg_setup_command": os.environ.get(
        "CFG_SETUP",
        'export COMMAND_CODE_API_KEY="$AGENT_API_KEY"; '
        "npm install -g @earendil-works/pi-coding-agent@0.84.4 "
        "pi-commandcode-provider@0.6.0 @earendil-works/pi-ai@0.84.4; "
        "pi install npm:pi-commandcode-provider 2>&1 | tail -n 20 || true; "
        'mkdir -p "$HOME/.pi/agent"; '
        'cp -f .pi-commandcode-models.json "$HOME/.pi/agent/commandcode-models.json" 2>/dev/null || true',
    ),
}

ROLE_MAP = [
    (r"审|review", "review"),
    (r"分析|根因|analyze|cause", "analyze"),
    (r"规划|拆解|plan|task", "plan"),
    (r"修|fix|repair", "fix"),
]


def gh(endpoint, method="GET", payload=None):
    cmd = ["gh", "api", endpoint]
    if method != "GET":
        cmd += ["-X", method]
    if payload is not None:
        cmd += ["--input", "-"]
    proc = subprocess.run(
        cmd,
        input=json.dumps(payload) if payload is not None else None,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip()[:300])
    return json.loads(proc.stdout) if proc.stdout.strip() else {}


def dispatch(repo, number, role, task, author):
    payload = {
        "event_type": CONFIG["event_type"],
        "client_payload": {
            "repo": repo,
            "number": number,
            "role": role,
            "cfg": {
                "task": task[:4000],
                "author": author,
                "provider": CONFIG["cfg_provider"],
                "model": CONFIG["cfg_model"],
                "setup_command": CONFIG["cfg_setup_command"],
            },
        },
    }
    gh(f"repos/{CONFIG['npc_repo']}/dispatches", "POST", payload)


def extract_role(body):
    m = re.search(re.escape("@" + CONFIG["bot"]) + r"\s+(\S+)", body)
    if not m:
        return "assistant"
    word = m.group(1)
    for pattern, role in ROLE_MAP:
        if re.search(pattern, word, re.IGNORECASE):
            return role
    return "assistant"


def load_state():
    try:
        with open(CONFIG["state_file"], encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"last_id": 0}


def save_state(state):
    os.makedirs(os.path.dirname(CONFIG["state_file"]), exist_ok=True)
    with open(CONFIG["state_file"], "w", encoding="utf-8") as f:
        json.dump(state, f)


def poll_once(state):
    comments = gh(
        f"repos/{CONFIG['watch_repo']}/issues/comments"
        f"?sort=created&direction=desc&per_page={CONFIG['page_size']}"
    )
    last = state["last_id"]
    fresh = [
        c
        for c in comments
        if c["id"] > last
        and CONFIG["bot"] in (c.get("body") or "")
        and "<!-- npc-at -->" not in (c.get("body") or "")
        and c["user"]["login"] != CONFIG["bot"]
    ]
    for c in sorted(fresh, key=lambda x: x["id"]):
        number = int(re.search(r"/issues/(\d+)", c["issue_url"]).group(1))
        role = extract_role(c["body"])
        print(
            f"[npc-watch] @{CONFIG['bot']} 提及: issue #{number} role={role} "
            f"by @{c['user']['login']} (id={c['id']})",
            flush=True,
        )
        try:
            dispatch(CONFIG["watch_repo"], number, role, c["body"], c["user"]["login"])
            print(f"[npc-watch] 已 dispatch → {CONFIG['npc_repo']}", flush=True)
        except Exception as exc:  # noqa: BLE001 — 单次失败不终止守望
            print(f"[npc-watch] dispatch 失败: {exc}", flush=True)
        state["last_id"] = max(state["last_id"], c["id"])
        save_state(state)
    max_id = max((c["id"] for c in comments), default=last)
    if max_id > state["last_id"]:
        state["last_id"] = max_id
        save_state(state)


def main():
    state = load_state()
    print(
        f"[npc-watch] 守望启动: {CONFIG['watch_repo']} → {CONFIG['npc_repo']} "
        f"bot=@{CONFIG['bot']} interval={CONFIG['interval']}s last_id={state['last_id']}",
        flush=True,
    )
    while True:
        try:
            poll_once(state)
        except Exception as exc:  # noqa: BLE001 — 网络抖动继续轮询
            print(f"[npc-watch] 轮询异常: {exc}", flush=True)
        time.sleep(CONFIG["interval"])


if __name__ == "__main__":
    sys.exit(main())
