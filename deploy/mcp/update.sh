#!/usr/bin/env bash
# Executed by the trusted production deploy identity, never the MCP SSH user.
set -euo pipefail
stage="${1:?staging directory required}"
sha="${2:?image SHA required}"
[[ "$stage" =~ ^/tmp/putevka-mcp-[0-9]+-[0-9]+$ ]]
[[ "$sha" =~ ^[0-9a-f]{40}$ ]]
test "$(realpath "$stage")" = "$stage"
test -f "$stage/mcp-image.tar.gz"
# Bootstrap must have supplied the restricted SSH account and dedicated DB role.
sudo -n test -f /etc/putevka-mcp/runtime.env
sudo -n test -f /etc/putevka-mcp/image.env
sudo -n test -f /usr/local/sbin/putevka-mcp-session
image="putevka-development-mcp:$sha"
gzip -dc "$stage/mcp-image.tar.gz" | docker load > /dev/null
# Validate and sample the candidate BEFORE switching the image used by new sessions.
# Use the candidate compose file, but the root-owned runtime credentials.
sudo -n env "MCP_IMAGE=$image" /usr/bin/docker --config /etc/putevka-mcp/docker compose \
    --project-name putevka-mcp-check \
    --env-file /etc/putevka-mcp/runtime.env \
    -f "$stage/docker-compose.mcp.yml" \
    run --rm --no-deps -T --interactive=false --entrypoint python development-mcp \
    -m development_mcp.smoke --sample-cases
sudo -n install -d -m 0755 -o root -g root /opt/putevka-mcp
if sudo -n test -f /opt/putevka-mcp/docker-compose.mcp.yml; then
    sudo -n cp /opt/putevka-mcp/docker-compose.mcp.yml /opt/putevka-mcp/docker-compose.mcp.yml.previous
fi
sudo -n cp /usr/local/sbin/putevka-mcp-session /usr/local/sbin/putevka-mcp-session.previous
sudo -n install -m 0644 -o root -g root "$stage/docker-compose.mcp.yml" /opt/putevka-mcp/docker-compose.mcp.yml
sudo -n install -m 0755 -o root -g root "$stage/putevka-mcp-session" /usr/local/sbin/putevka-mcp-session
printf 'MCP_IMAGE=%s\n' "$image" | sudo -n tee /etc/putevka-mcp/image.env.next > /dev/null
sudo -n chmod 0600 /etc/putevka-mcp/image.env.next
sudo -n cp /etc/putevka-mcp/image.env /etc/putevka-mcp/image.env.previous
sudo -n mv /etc/putevka-mcp/image.env.next /etc/putevka-mcp/image.env
# Keep the previous image for rollback. Existing stdio sessions finish normally.
rm -- "$stage/mcp-image.tar.gz"
printf '%s\n' 'MCP updated; new SSH sessions will use the verified image.'
