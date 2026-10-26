#!/bin/sh
set -eu

TZ=${TZ:-Asia/Seoul}
export TZ
hour=${1:-$(date +%H)}
case "$hour" in
    08|09|10|11|12|13|14|15|16|17) printf '%s\n' tv ;;
    00|01|02|03|04|05|06|07|18|19|20|21|22|23) printf '%s\n' air_purifier ;;
    *) echo "Invalid hour: $hour" >&2; exit 2 ;;
esac
