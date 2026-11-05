FROM --platform=linux/arm64 debian:13.2
WORKDIR /app
COPY wrapper /app/wrapper
COPY rootfs /app/rootfs
COPY login.sh /app/workbench-login.sh
RUN chmod +x /app/wrapper /app/workbench-login.sh
EXPOSE 10020 20020
ENTRYPOINT ["/app/workbench-login.sh"]
