#!/bin/sh
# 部署组件仓(origin/main)到 bot 私有实例:bot/main → cherry-pick origin/main → push。
# bot 实例的 env 特化(clarify-scan/worker 的内联默认值)保留在 bot/main 上,
# 若组件改动与特化冲突,本脚本会中止并提示手工处理。
# 用法: 在组件仓工作区内执行 scripts/deploy-instance.sh
set -eu
cd "$(dirname "$0")/.."
git fetch origin main -q
git fetch bot main -q
git checkout -q -b deploy-tmp bot/main
if git cherry-pick origin/main 2>&1; then
  git push -q bot deploy-tmp:main
  echo "实例已部署: $(git rev-parse --short deploy-tmp) → bot/main"
else
  git cherry-pick --abort 2>/dev/null || true
  echo "cherry-pick 冲突:实例特化与组件变更冲突,需手工处理" >&2
  exit 1
fi
git checkout -q main
git branch -qD deploy-tmp
