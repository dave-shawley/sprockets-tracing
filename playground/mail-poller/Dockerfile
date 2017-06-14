FROM python:3.6-alpine

ENV PORT 80
EXPOSE $PORT

COPY mailpoller.py setup.py /app/mailpoller/
COPY packages/* /app/packages/

RUN pip install --no-cache-dir --disable-pip-version-check --find-links /app/packages /app/mailpoller/ sprockets-tracing \
 && rm -fr /app/packages

CMD ["python", "/app/mailpoller/mailpoller.py"]
