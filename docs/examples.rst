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
