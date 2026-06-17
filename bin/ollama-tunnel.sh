#!/usr/bin/env bash
# ollama-tunnel.sh — exec wrapper for the launchd-managed SSH tunnel to the rtx GPU box.
#
# WHY THIS EXISTS:
#   On 2026-06-12 the VS Code Remote-SSH port forward for 11435 black-holed:
#   the listener accepted TCP connections but returned 0 bytes, freezing four
#   fleet workers mid-HTTP-request for hours. VS Code forwarded ports have no
#   keepalive and silently die when the remote channel breaks.
#
# HOW IT SELF-HEALS:
#   - ServerAliveInterval=15 + ServerAliveCountMax=3: ssh sends keepalive probes
#     every 15s; if 3 consecutive probes go unanswered (~45s) ssh EXITS cleanly
#     instead of hanging forever. launchd then restarts it via KeepAlive=true.
#   - ExitOnForwardFailure=yes: if port 11435 is already bound (e.g. by VS Code),
#     ssh exits immediately with an error rather than starting without the forward.
#     launchd retries every ThrottleInterval=10s — harmless retry loop until the
#     port frees.
#   - "-S none": never re-use an existing control socket; always a fresh connection.
#   - "-F /dev/null": do NOT read ~/.ssh/config. The "Host rtx" block there carries
#     LocalForward 8888/8889/8081; combined with ExitOnForwardFailure, any other
#     process squatting one of those ports would block THIS tunnel from restarting
#     even though 11435 is free. Connection params are spelled out explicitly below
#     (mirror of the rtx block: sergii@93.180.178.241 port 2225, default keys).
#
# EDIT THIS FILE to change the host or remote port; no need to touch the plist.

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting ollama tunnel → rtx:11434 → 127.0.0.1:11435"

exec /usr/bin/ssh \
  -N \
  -T \
  -F /dev/null \
  -p 2225 \
  -o BatchMode=yes \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=15 \
  -o ServerAliveCountMax=3 \
  -o ConnectTimeout=10 \
  -o TCPKeepAlive=yes \
  -S none \
  -L 127.0.0.1:11435:127.0.0.1:11434 \
  sergii@93.180.178.241
