#!/usr/bin/env bash
# Run in a disposable cgroup-v2 VM with root privileges. Never modifies the
# parent group memory limit. The child is intentionally OOM-killed.
set -euo pipefail
group="/sys/fs/cgroup/geofathom-test-$$"
mkdir "$group"
trap 'rmdir "$group"' EXIT
echo 134217728 > "$group/memory.max"
if [[ -f "$group/memory.swap.max" ]]; then echo 0 > "$group/memory.swap.max"; fi
export GEOFATHOM_WORKER_CGROUP="$group"
export GEOFATHOM_WORKER_MEMORY_MB=128
python3 -c 'from jobs.hard_limits import enforce; print(enforce("ci"))'
set +e
python3 -c 'from jobs.hard_limits import enforce; enforce("ci"); x=bytearray(512*1024**2)'
status=$?
set -e
test "$status" -eq 137
awk '$1=="oom_kill" && $2>=1 { found=1 } END{exit !found}' "$group/memory.events"
