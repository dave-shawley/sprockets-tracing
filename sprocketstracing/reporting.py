from tornado import gen


@gen.coroutine
def report_spans(span_queue, **kwargs):
    """
    Report spans out-of-band.

    :param tornado.queues.Queue span_queue: queue to consume spans from.

    This co-routine consumes spans from the `span_queue` and reports them
    to the aggregation endpoint.

    """
