version_info = (0, 0, 0)
version = '.'.join(str(v) for v in version_info)


def install(application, io_loop):
    """
    Install the sprockets-tracing implementation hooks.

    :param tornado.web.Application application: the application to
        instrument.  The configuration details are read from
        ``application.settings['opentracing']``.
    :param tornado.ioloop.IOLoop io_loop: the IO loop to run the
        reporter instance on.

    This function initializes the Open Tracing implementation using
    the configuration stored in ``application.settings['opentracing']``,
    creates a new :class:`~sprocketstracing.tracing.Tracer` instance
    configured appropriately, and spawns a reporter on the IO loop.  The
    :class:`~sprocketstracing.tracing.Tracer` instance is stored as
    the ``opentracing`` attribute on ``application`` (via :func:`setattr`)
    though you should access it via the :data:`opentracing.tracer` global.

    """
    from sprocketstracing import reporting, tracing
    import opentracing
    import tornado.queues

    span_queue = tornado.queues.Queue()
    application.settings.setdefault('opentracing', {})
    tracer = tracing.Tracer(span_queue, **application.settings['opentracing'])
    opentracing.tracer = tracer
    setattr(application, 'opentracing', tracer)
    io_loop.spawn_callback(reporting.report_spans, span_queue, **settings)


def shutdown(application):
    """
    Initiate an orderly shutdown of the Open Tracing implementation.

    :param tornado.web.Application application: the application associated
        with the tracer to shut down.
    :returns: a :class:`tornado.concurrent.Future` if measurements
        need to be flushed before termination; otherwise, :data:`None`.
    :rtype: tornado.concurrent.Future

    """
    import opentracing

    if not isinstance(opentracing.tracer, opentracing.Tracer):
        future = opentracing.tracer.stop()
        opentracing.tracer = opentracing.Tracer()  # install the no-op tracer
        setattr(application, 'opentracing', opentracing.tracer)
        return future
