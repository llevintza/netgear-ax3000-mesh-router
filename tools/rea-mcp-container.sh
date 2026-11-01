#!/usr/bin/env bash
# Start (or restart) the long-running "rea-mcp" container. Any MCP-capable agent reaches REA
# through it as a stdio server: `docker exec -i rea-mcp rea --mcp` (see AGENTS.md).
#
# - Project dir is mounted at the SAME absolute path, so host paths work inside the container.
#   firmware/ is mounted read-only on top.
# - Extraction output must go to /work/out (a Docker volume): REA rejects bind-mounted output
#   dirs on Colima because inode identity is not stable ("Extraction directory identity changed").
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
NAME=rea-mcp
IMAGE=rea-fw

docker image inspect "$IMAGE" >/dev/null 2>&1 || docker build -t "$IMAGE" "$PROJECT_DIR/tools"
docker rm -f "$NAME" >/dev/null 2>&1 || true

docker run -d --name "$NAME" --restart unless-stopped \
  -v "$PROJECT_DIR:$PROJECT_DIR" \
  -v "$PROJECT_DIR/firmware:$PROJECT_DIR/firmware:ro" \
  -v rea-out:/work/out \
  -w "$PROJECT_DIR" \
  "$IMAGE" sleep infinity >/dev/null

docker exec "$NAME" rea --version
echo "rea-mcp container running. Copy results out with:"
echo "  docker exec $NAME sh -c 'tar -C /work/out -cf - <dir>' | tar -C \"$PROJECT_DIR/extracted\" -xf -"
