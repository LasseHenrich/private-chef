#!/usr/bin/env bash
# Install into ignored project-local storage without changing the system's Node.js.
set -euo pipefail

chef_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
chef_runtime="$chef_root/data/runtime"
mkdir -p "$chef_runtime"
chmod 700 "$chef_root/data" "$chef_runtime"

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required to bootstrap the private runtime." >&2
  exit 1
fi

# Install Node first: installing OpenClaw under the old system runtime can fail.
npm install --prefix "$chef_runtime" --cache "$chef_runtime/npm-cache" \
  --fetch-retries=0 --no-audit --no-fund node@24
export PATH="$chef_runtime/node_modules/.bin:$PATH"
npm install --prefix "$chef_runtime" --cache "$chef_runtime/npm-cache" \
  --fetch-retries=0 --no-audit --no-fund openclaw@latest

openclaw --version
echo "Installed the private runtime. Continue with the pairing commands in docs/openclaw.md."
