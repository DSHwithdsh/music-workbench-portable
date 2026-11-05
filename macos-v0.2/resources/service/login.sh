#!/bin/sh
set -eu
cd /app
database=/app/rootfs/data/data/com.apple.android.music/files/mpl_db/kvs.sqlitedb
if [ -f "$database" ]; then
    exec ./wrapper -H 0.0.0.0
fi
printf 'Apple ID: '
IFS= read -r workbench_user
printf '密码（输入不显示）: '
trap 'stty echo 2>/dev/null || true' EXIT INT TERM
stty -echo
IFS= read -r workbench_password
stty echo
printf '\n'
trap - EXIT INT TERM
if [ -z "$workbench_user" ] || [ -z "$workbench_password" ]; then
    printf '账号或密码为空，未启动。\n' >&2
    exit 2
fi
exec ./wrapper -H 0.0.0.0 -L "$workbench_user:$workbench_password"
