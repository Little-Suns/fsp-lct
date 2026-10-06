#!/bin/sh
# cgroup v2 для nsjail: процессы контейнера — в дочернюю группу init, корню включаем контроллеры
# (в cgroup v2 группа с процессами не может раздавать контроллеры детям). Нужен privileged и cgroupns private.
set -e
if [ ! -w /sys/fs/cgroup/cgroup.subtree_control ]; then
  echo "sandbox: /sys/fs/cgroup недоступен на запись — контейнеру нужен privileged (cgroup v2, cgroupns private)" >&2
  exit 1
fi
mkdir -p /sys/fs/cgroup/init
for p in $(cat /sys/fs/cgroup/cgroup.procs); do echo "$p" > /sys/fs/cgroup/init/cgroup.procs 2>/dev/null || true; done
echo "+memory +pids +cpu" > /sys/fs/cgroup/cgroup.subtree_control
exec "$@"
