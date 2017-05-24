from tornado import gen


class RecordingReporter(object):

    """
    A reporter that simple records what it processes.

    Register this class with :func:`~sprocketstracing.reporting.add_reporter`
    to simply record what would have been reported.  This is most useful
    when testing if you are the type of person that wants to ensure that
    your tracing information is accurate.

    **Usage Example**

    .. code-block:: python

       from sprocketstracing import reporting, testing
       from tornado import ioloop, web
       import sprocketstracing

       # register the reporter somewhere
       reporting.add_reporter('recorder', testing.RecordingReporter)

       # install and configure sprockets tracing
       def make_app(**settings):
           settings['opentracing'] = {'propagation_syntax': 'b3',
                                      'report_format': 'recorder'}
           app = web.Application(handlers, **settings)
           sprocketstracing.install(app, ioloop.IOLoop.instance())
           return app

       # access the reporter from the opentracing state
       spans = app.settings['opentracing']['state']['reporter'].captured_spans

    .. attribute:: captured_spans

       A list containing the spans that have been captured.  This list
       contains the :class:`~sprocketstracing.tracing.Span` instances
       that have been sampled.

    """

    def __init__(self, *args, **kwargs):
        super(RecordingReporter, self).__init__()
        self.captured_spans = []

    @gen.coroutine
    def process_span(self, span):
        self.captured_spans.append(span)

    @gen.coroutine
    def flush(self):
        pass
