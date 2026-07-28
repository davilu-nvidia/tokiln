#!/usr/bin/env bash
# Build images and write digests back into VERSIONS.lock (the digest is the fact; tags are aliases).
set -euo pipefail
cd "$(dirname "$0")"
for c in sglang-glm52 dynamo; do
  img="tokiln/${c}:dev"
  docker build -f "Dockerfile.${c}" -t "$img" .
  digest=$(docker inspect --format='{{index .RepoDigests 0}}' "$img" 2>/dev/null || docker images --digests --format '{{.Digest}}' "$img" | head -1)
  echo "built ${c}: ${digest}"
  echo "TODO: write the digest into VERSIONS.lock -> components.${c}.image (manually or via CI)"
done
