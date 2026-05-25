#!/bin/sh
set -e
# Substitute only ${BACKEND_URL} — leave nginx variables like $uri untouched
envsubst '${BACKEND_URL}' \
  < /etc/nginx/conf.d/default.conf.template \
  > /etc/nginx/conf.d/default.conf
exec nginx -g 'daemon off;'
