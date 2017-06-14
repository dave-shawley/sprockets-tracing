FROM python:3.5-alpine

ENV SMTP_USER useconfig
ENV SMTP_PASSWORD useconfig
ENV SMTP_HOST useconfig
ENV SMTP_PORT useconfig

COPY emailer.py setup.py rejected.yml /app/emailer/
COPY packages/* /app/packages/

RUN apk add --update-cache --virtual .deps musl-dev gcc linux-headers \
 && pip install --no-cache-dir --disable-pip-version-check --find-links /app/packages /app/emailer/ sprockets-tracing \
 && rm -fr /app/packages /var/cache/apk \
 && apk del --purge .deps

CMD ["rejected", "-c", "/app/emailer/rejected.yml", "-f"]
