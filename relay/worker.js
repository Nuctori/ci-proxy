// ci-proxy relay —— GitHub webhook → 代理仓库 repository_dispatch 中继
// 部署于 Cloudflare Workers 免费档;用于转发无法从本地触发的仓库事件
// (push 可走本地 hook,issues/issue_comment 等只能走本中继)。
//
// Worker Secrets:
//   WEBHOOK_SECRET  与源仓库 webhook 配置的共享密钥(HMAC-SHA256 校验)
//   DISPATCH_PAT    对代理仓库有 Contents: write 的 PAT
// Worker Variables:
//   PROXY_REPO      代理仓库 owner/name,例 "someone/ci-proxy"
//   EVENT_TYPE      dispatch 的事件类型,例 "npc-review"
//   FORWARD_EVENTS  逗号分隔的转发事件白名单,例 "push,issues,issue_comment"
//
// 源仓库 Webhooks 配置:
//   Payload URL = https://<worker>.<account>.workers.dev
//   Content type = application/json;Secret = WEBHOOK_SECRET 同值
//   事件 = 与 FORWARD_EVENTS 一致

export default {
  async fetch(request, env) {
    if (request.method !== "POST") return new Response("ok", { status: 200 });

    const event = request.headers.get("x-github-event") || "";
    const allow = (env.FORWARD_EVENTS || "push").split(",").map((s) => s.trim());
    if (!allow.includes(event)) return new Response("event not allowed", { status: 204 });

    const body = await request.text();
    if (!(await verifyHmac(env.WEBHOOK_SECRET, request.headers.get("x-hub-signature-256") || "", body))) {
      return new Response("bad signature", { status: 401 });
    }

    const payload = JSON.parse(body);
    const repoFull = payload?.repository?.full_name;
    if (!repoFull) return new Response("no repo", { status: 400 });

    const client = { repo: repoFull };
    if (event === "push" && payload.ref?.startsWith("refs/heads/")) {
      client.branch = payload.ref.slice("refs/heads/".length);
      client.sha = payload.head_commit?.id || payload.after;
      client.msg = payload.head_commit?.message || "";
    } else {
      client.action = payload.action || "";
      client.number = payload.issue?.number ?? payload.pull_request?.number ?? null;
    }

    const res = await fetch(`https://api.github.com/repos/${env.PROXY_REPO}/dispatches`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.DISPATCH_PAT}`,
        Accept: "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "ci-proxy-relay",
      },
      body: JSON.stringify({ event_type: env.EVENT_TYPE || "npc-review", client_payload: client }),
    });
    if (!res.ok) console.error("dispatch failed", res.status, await res.text());
    return new Response(res.ok ? "dispatched" : "dispatch failed", { status: res.ok ? 202 : 502 });
  },
};

async function verifyHmac(secret, signature, body) {
  if (!secret || !signature.startsWith("sha256=")) return false;
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const mac = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(body));
  const hex = [...new Uint8Array(mac)].map((b) => b.toString(16).padStart(2, "0")).join("");
  return signature === `sha256=${hex}`;
}
