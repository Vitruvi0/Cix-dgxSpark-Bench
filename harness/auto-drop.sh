#!/bin/bash
# auto-drop.sh <stato-driver.txt>: quando il driver scrive "ATTESA drop_caches" fa il drop
# (sudoers NOPASSWD del 07/09: /etc/sudoers.d/bench, solo `sysctl vm.drop_caches=3`);
# prepara_memoria di driver-lib riparte da sola quando Cached scende sotto 10 GiB.
# Esce a FINITO/FALLITO. Log in auto-drop.log nella dir dello stato.
f=${1:?file di stato}; cd "$(dirname "$f")" || exit 1; f=$(basename "$f"); ultimo=""
while :; do
  l=$(tail -1 "$f" 2>/dev/null)
  case "$l" in
    FINITO*|FALLITO*) echo "$(date +%T) esco su: $l" >> auto-drop.log; exit 0;;
    ATTESA\ drop_caches*)
      if [ "$l" != "$ultimo" ]; then
        sync && sudo -n /usr/sbin/sysctl vm.drop_caches=3 >/dev/null \
          && echo "$(date +%T) drop fatto ($(awk '/^Cached:/{printf "%d", $2/1048576}' /proc/meminfo) GiB in cache dopo) per: $l" >> auto-drop.log \
          || echo "$(date +%T) drop FALLITO (sudo -n): $l" >> auto-drop.log
        ultimo=$l
      fi;;
  esac
  sleep 15
done
