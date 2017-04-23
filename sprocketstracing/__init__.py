import logging


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
    reporter = reporting.get_reporter(**application.settings['opentracing'])
    opentracing.tracer = tracer
    setattr(application, 'opentracing', tracer)
    io_loop.spawn_callback(reporting.report_spans, reporter, span_queue)

    application.settings['opentracing']['state'] = {
        'reporter': reporter,
        'span_queue': span_queue,
        'tracer': tracer,
    }


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
    import tornado.concurrent
    import tornado.ioloop

    logger = logging.getLogger('sprocketstracing.shutdown')
    state = application.settings.get('opentracing', {}).get('state')
    if state:
        reporter = state.get('reporter')
        tracer = state.get('tracer')
        iol = tornado.ioloop.IOLoop.current()
        future = tornado.concurrent.TracebackFuture()

        def reporter_flushed(f):
            logger.info('shutdown of tracing layer is complete')
            if f.exception():
                logger.warning('exception while flushing reporter - %r',
                               f.exception())
            application.settings['opentracing'].pop('state', None)
            future.set_result(None)

        def tracer_stopped(f):
            if f.exception():
                logger.warning('exception while stopping tracer - %r',
                               f.exception())
            if reporter:
                logger.info('flushing reporter')
                iol.add_future(reporter.flush(), reporter_flushed)
            else:
                future.set_result(None)

        if state.get('tracer'):
            logger.info('stopping tracer, reporter will be flushed and '
                        'stopped once the tracer is shut down')
            iol.add_future(tracer.stop(), tracer_stopped)

            # install the no-op tracer
            opentracing.tracer = opentracing.Tracer()
            setattr(application, 'opentracing', opentracing.tracer)

            return future

        elif reporter:
            logger.info('flushing reporter')
            iol.add_future(reporter.flush(), reporter_flushed)

            return future

    else:
        logger.info('tracing was not initialized, nothing to do')
