# Sourced by early boot and the shutdown program. Names belong to this payload.
mounted() { awk -v path="$1" '$2 == path {found=1} END {exit !found}' /proc/mounts; }

mapping_present() {
    for entry in /sys/class/block/dm-*/dm/name; do
        [ -r "$entry" ] || continue
        [ "$(cat "$entry")" = "$1" ] && return 0
    done
    return 1
}

unmount_tree() {
    mount_root=$1
    if mounted "$mount_root"; then
        awk -v prefix="$mount_root/" 'index($2,prefix)==1 {print $2}' /proc/mounts | sort -r |
            while IFS= read -r escaped; do
                umount "$(printf '%b' "$escaped")" || exit 1
            done || return 1
        umount "$mount_root" || return 1
    fi
}

stop_storage() {
    unmount_tree /oldroot || return 1
    unmount_tree /newroot || return 1
    pidfile=/hybrid-nbd.pid
    if [ ! -f "$pidfile" ]; then pidfile=/run/hybrid-nbd.pid; fi
    if [ -f "$pidfile" ]; then
        pid=$(cat "$pidfile") || return 1
        case "$pid" in ''|*[!0-9]*) return 1;; esac
        if [ -s "/proc/$pid/cmdline" ] || [ -n "$(cat "/proc/$pid/cmdline" 2>/dev/null | tr '\000' ' ')" ]; then
            tr '\000' '\n' < "/proc/$pid/cmdline" | head -n 1 | grep -qx '@qemu-nbd' || return 1
            kill -TERM "$pid" || return 1
            for second in 1 2 3 4 5 6 7 8 9 10; do
                [ -z "$(cat "/proc/$pid/cmdline" 2>/dev/null | tr '\000' ' ')" ] && break
                sleep 1
            done
            [ -z "$(cat "/proc/$pid/cmdline" 2>/dev/null | tr '\000' ' ')" ] || return 1
        fi
    fi
    if mounted /host; then umount /host || return 1; fi
    if mounted /esp; then umount /esp || return 1; fi
    mounted /sys || return 1
    for mapping in hybrid_host hybrid_vault; do
        if mapping_present "$mapping"; then
            echo "HYBRID_CLOSING_MAPPING $mapping"
            timeout -k 5 15 dmsetup --noudevsync remove "$mapping" || return 1
            ! mapping_present "$mapping" || return 1
        fi
    done
}
