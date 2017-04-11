Programming Interface
=====================

Open Tracing Objects
--------------------
.. autoclass:: sprocketstracing.tracing.Tracer
   :members:

.. autoclass:: sprocketstracing.tracing.Span
   :members:

.. autoclass:: sprocketstracing.tracing.SpanContext
   :members:

Application Management
----------------------
.. autofunction:: sprocketstracing.install

.. autofunction:: sprocketstracing.shutdown

Request Handlers
----------------
.. autoclass:: sprocketstracing.tracing.RequestHandlerMixin
   :members:

Span Reporting
--------------
.. autofunction:: sprocketstracing.reporting.report_spans
