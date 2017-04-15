Examples
========

Simple Tornado Application
--------------------------
:file:`examples/basic.py` is a very simple Tornado web application that
returns the current time as a JSON object.  By including the
:class:`sprocketstracing.tracing.RequestHandlerMixin` class in your
request handler's super-class list, you get tracing of the endpoint for
nearly free.  The only thing that you have to do on a per-request basis
is to set the ``operation_name`` key of the
:attr:`~sprocketstracing.tracing.RequestHandlerMixin.opentracing_options`
to the name of the operation for the trace.

.. literalinclude:: ../examples/basic.py
   :pyobject: TimeHandler.initialize
   :linenos:
   :dedent: 4

The 
:attr:`~sprocketstracing.tracing.RequestHandlerMixin.opentracing_options`
attribute is created by the 
:meth:`~sprocketstracing.tracing.RequestHandlerMixin` during initialization
of it does not already exist.  This attribute let's you customize certain
aspects of the trace creation.

You also have to initialize the ``opentracing.tracer`` attribute to the
sprockets-tracing implementation.  The ``tracer`` attribute of the
``opentracing`` package is the API-defined entrypoint into the tracing
logic.  Implementations are expected to reset the global to the
implementation-defined tracer (see `opentracing-python`_).  This library
exposes the :func:`sprocketstracing.install` function for this very
purpose.  It creates a new tracer instance, configures it according to
whatever is in ``application.settings['opentracing']``, installs it into
the :data:`opentracing.tracer` global, and spawns a reporter that sends
trace information to the tracing system.

.. literalinclude:: ../examples/basic.py
   :pyobject: make_app
   :linenos:

.. _opentracing-python: https://github.com/opentracing/opentracing-python
   /blob/4109459ae6ed4f5444b60ffe12127d8a6b85e1bd/opentracing
   /__init__.py#L36-L39

The :class:`sprocketstracing.tracing.RequestHandlerMixin` handles
extracting the active span from the incoming headers and reporting the
span processing details to the aggregator if sampling is enabled.
A simple implementation of the mixin looks something like:

.. code-block:: python

   class RequestHandlerMixin(web.RequestHandler):
      
       def prepare(self):
           super(RequestHandlerMixin, self).prepare()
           kwargs = {'start_time': ioloop.time()}
           context = opentracing.tracer.extract(
              opentracing.Format.HTTP_HEADERS,
              self.request.headers)
           if context:
              kwargs['child_of'] = context
           self.span = opentracing.tracer.start_span(
              self.opentracing_options['operation_name'], **kwargs)
           self.span.set_tag('span.kind', 'server')
           self.span.set_tag('http.method', self.request.method)
           self.span.set_tag('http.version', self.request.version)
           self.span.set_tag('peer.address', self.request.remote_ip)

       def on_finish(self):
           self.span.set_tag('http.status_code', self.get_status())
           self.span.finish(end_time=ioloop.time())
       
       def log_exception(self, typ, value, tb):
           self.span.log_kv({'python.exception.type': typ,
                             'python.exception.value': value,
                             'python.exception.tb': tb})
           super(RequestHandlerMixin, self).log_exception(
               typ, value, tb)

.. note::

   Remember that the above is implemented for you when you use
   :class:`sprocketstracing.tracing.RequestHandlerMixin`.  If you
   want to roll your own, then that is close to what you need to do.

This is all that you need for the most basic of tracing.  Your request
is registered and sent to the tracing implementation when it finishes.
You can use :func:`opentracing.start_child_span` to start a new child
span that tracks whatever operation you are interested in:

.. code-block:: python

   class RequestHandlerMixin(web.RequestHandler):

       def get(self):
           with opentracing.start_child_span(self.span, 'some-operation'):
               # do stuff ... the context manager exit will handle tracing

That's about it for the basic usage.  Take a look at the examples in
full for more examples.
