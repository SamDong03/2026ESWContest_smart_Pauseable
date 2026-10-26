#!/bin/sh
set -eu

for pid in $(docker top ha-ai-full 2>/dev/null | awk '/[r]un_repetitive_hybrid_demo.py/ {print $2}'); do
  kill -TERM "$pid" 2>/dev/null || true
done
for pid in $(docker top ha-ai-full 2>/dev/null | awk '/[r]un_washer_hybrid_demo.py/ {print $2}'); do
  kill -TERM "$pid" 2>/dev/null || true
done
for pid in $(docker top ha-ai-full 2>/dev/null | awk '/[r]oute_repetitive_output.py/ {print $2}'); do
  kill -TERM "$pid" 2>/dev/null || true
done

systemctl stop pauseable-repetitive-central-output.service 2>/dev/null || true
systemctl stop pauseable-air-purifier-tts.path 2>/dev/null || true
systemctl stop pauseable-washer-youtube-tts.path 2>/dev/null || true
echo "Repetitive-behavior demo stopped."
