# Fleet Ollama Tunnel — launchd-managed SSH forward

## What this is

A self-healing SSH tunnel that forwards `127.0.0.1:11435` on this Mac to
`127.0.0.1:11434` (ollama) on the `rtx` GPU box (`93.180.178.241`).

Fleet workers talk to `http://127.0.0.1:11435` (OpenAI-compatible ollama
endpoint). This tunnel replaces the fragile VS Code Remote-SSH port forward
that failed silently on **2026-06-12 ~08:30**: the VS Code listener accepted
TCP connections but returned 0 bytes, freezing four fleet workers mid-request
for hours. launchd-managed ssh with ServerAlive keepalives self-heals within
~45 seconds of any channel failure.

## Files

| File | Purpose |
|------|---------|
| `~/.fleet/bin/ollama-tunnel.sh` | exec wrapper — edit here to change host/port |
| `~/Library/LaunchAgents/com.fleet.ollama-tunnel.plist` | launchd job definition |
| `~/.fleet/logs/ollama-tunnel.log` | combined stdout+stderr log |

## Checking status

```bash
# Is it running?
launchctl print gui/501/com.fleet.ollama-tunnel | grep -E 'state|pid|last exit'

# Is the port bound?
lsof -nP -iTCP:11435 -sTCP:LISTEN

# Does the tunnel actually serve models?
curl -s -m 10 http://127.0.0.1:11435/v1/models | python3 -m json.tool | head -20

# Live log
tail -f ~/.fleet/logs/ollama-tunnel.log
```

## Pausing / removing

```bash
# Unload (stops tunnel, survives reboot — reload with bootstrap below):
launchctl bootout gui/501/com.fleet.ollama-tunnel

# Reload after editing the script or plist:
launchctl bootstrap gui/501 ~/Library/LaunchAgents/com.fleet.ollama-tunnel.plist

# Force-restart the tunnel right now:
launchctl kickstart -k gui/501/com.fleet.ollama-tunnel
```

## IMPORTANT: VS Code Ports panel conflict

The launchd tunnel and a VS Code port-forward CANNOT share port 11435.
If VS Code's Ports panel shows 11435 forwarded, the launchd job will
retry-loop every 10 seconds (clean, by design — you'll see "bind: Address
already in use" in the log) until the port is freed.

**To fix:** In VS Code, open the Ports panel (Terminal → Ports), right-click
the 11435 entry, and choose "Stop Forwarding Port". The launchd tunnel will
bind automatically within ~10 seconds with no further action.

After removing the VS Code forward, verify:
```bash
lsof -nP -iTCP:11435 -sTCP:LISTEN   # should show "ssh", not "Code\x20H"
curl -s -m 10 http://127.0.0.1:11435/v1/models | head -c 200
```

## Self-healing mechanism

- `ServerAliveInterval=15` + `ServerAliveCountMax=3`: ssh probes the connection
  every 15s; if 3 probes fail (~45s) it exits cleanly. launchd restarts it.
- `ExitOnForwardFailure=yes`: port conflict causes immediate clean exit, not a
  hung process.
- `KeepAlive=true` + `ThrottleInterval=10`: launchd ensures the tunnel is
  always running, restarting at most once per 10s.
