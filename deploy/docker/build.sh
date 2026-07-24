#!/usr/bin/env bash
# 构建镜像并把 digest 写回 VERSIONS.lock (digest 即事实, tag 只是别名)。
set -euo pipefail
cd "$(dirname "$0")"
for c in sglang-glm52 dynamo; do
  img="tokiln/${c}:dev"
  docker build -f "Dockerfile.${c}" -t "$img" .
  digest=$(docker inspect --format='{{index .RepoDigests 0}}' "$img" 2>/dev/null || docker images --digests --format '{{.Digest}}' "$img" | head -1)
  echo "built ${c}: ${digest}"
  echo "TODO: 手工或 CI 将 digest 写入 VERSIONS.lock -> components.${c}.image"
done
