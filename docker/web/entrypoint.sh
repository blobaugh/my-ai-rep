#!/bin/sh
set -eu

ancestors="${FRAME_ANCESTORS:-}"
if [ -z "$ancestors" ]; then
  ancestors=$(grep -v '^#' /etc/nginx/frame_ancestors.default | awk 'NF {print}' | tr '\n' ' ')
  ancestors=${ancestors% }
fi

if [ -z "$ancestors" ]; then
  echo "FRAME_ANCESTORS is empty" >&2
  exit 1
fi

case "$ancestors" in
  *"'"*|*'"'*|*';'*|*$'\n'*|*$'\r'*)
    echo "FRAME_ANCESTORS contains unsafe characters" >&2
    exit 1
    ;;
esac

if [ "${DEV_PROXY_API:-0}" = "1" ]; then
  api_block='    location /api/ {
        proxy_pass http://api:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
    }
'
else
  api_block=""
fi

template=$(cat /etc/nginx/templates/default.conf.template)
template=${template//__FRAME_ANCESTORS__/$ancestors}
template=${template//__API_PROXY_BLOCK__/$api_block}
printf '%s\n' "$template" > /etc/nginx/conf.d/default.conf

exec nginx -g 'daemon off;'
