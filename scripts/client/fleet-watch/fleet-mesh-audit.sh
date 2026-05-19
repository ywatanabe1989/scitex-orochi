#!/bin/bash
# Fleet full-mesh SSH connectivity audit (#387).
# Runs from head-nas as orchestrator, dispatches per-host probes via SSH.

HOSTS=(mba nas spartan ywata-note-win)
TARGETS=(mba nas spartan ywata-note-win)
TIMEOUT=8

declare -A RESULTS
for FROM in "${HOSTS[@]}"; do
  for TO in "${TARGETS[@]}"; do
    if [[ "$FROM" == "$TO" ]]; then
      RESULTS["${FROM}__${TO}"]="-"
      continue
    fi
    if [[ "$FROM" == "nas" ]]; then
      # Local NAS -> TO
      START=$(date +%s%N)
      if ssh -o ConnectTimeout=$TIMEOUT -o BatchMode=yes -o StrictHostKeyChecking=no "$TO" 'hostname -s' >/dev/null 2>&1; then
        END=$(date +%s%N); MS=$(( (END - START) / 1000000 ))
        RESULTS["${FROM}__${TO}"]="OK ${MS}ms"
      else
        RESULTS["${FROM}__${TO}"]="FAIL"
      fi
    else
      # Remote FROM -> TO via nested ssh
      START=$(date +%s%N)
      OUT=$(ssh -o ConnectTimeout=$TIMEOUT -o BatchMode=yes -o StrictHostKeyChecking=no "$FROM" "ssh -o ConnectTimeout=$TIMEOUT -o BatchMode=yes -o StrictHostKeyChecking=no $TO 'hostname -s' 2>&1" 2>&1)
      END=$(date +%s%N); MS=$(( (END - START) / 1000000 ))
      if [[ -n "$OUT" ]] && [[ "$OUT" != *"fail"* ]] && [[ "$OUT" != *"refused"* ]] && [[ "$OUT" != *"timed out"* ]] && [[ "$OUT" != *"Could not"* ]] && [[ "$OUT" != *"kex_"* ]]; then
        RESULTS["${FROM}__${TO}"]="OK ${MS}ms"
      else
        RESULTS["${FROM}__${TO}"]="FAIL"
      fi
    fi
  done
done

# Build markdown table
printf "\n| from \\\\ to | %s | %s | %s | %s |\n" "${TARGETS[@]}"
printf "|---|---|---|---|---|\n"
for FROM in "${HOSTS[@]}"; do
  printf "| **%s** " "$FROM"
  for TO in "${TARGETS[@]}"; do
    printf "| %s " "${RESULTS["${FROM}__${TO}"]}"
  done
  printf "|\n"
done
