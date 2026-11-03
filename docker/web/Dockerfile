# syntax=docker/dockerfile:1
FROM nginxinc/nginx-unprivileged:1.27-alpine

USER root
RUN apk add --no-cache curl
USER 101

COPY web/ /usr/share/nginx/html/
COPY web/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY web/frame_ancestors.default /etc/nginx/frame_ancestors.default
COPY docker/web/entrypoint.sh /entrypoint.sh

USER root
RUN chmod +x /entrypoint.sh
USER 101

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:8080/" >/dev/null || exit 1

ENTRYPOINT ["/entrypoint.sh"]
