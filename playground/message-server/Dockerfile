FROM python:3.5-alpine

ENV PORT 80
EXPOSE $PORT

COPY messageserver.py setup.py /app/messageserver/
COPY packages/* /app/packages/

RUN pip install --no-cache-dir --disable-pip-version-check --find-links /app/packages /app/messageserver/ sprockets-tracing \
 && rm -fr /app/packages

CMD ["python", "/app/messageserver/messageserver.py"]
