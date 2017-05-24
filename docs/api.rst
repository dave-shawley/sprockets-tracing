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
.. autofunction:: sprocketstracing.reporting.get_reporter

.. autofunction:: sprocketstracing.reporting.add_reporter

.. autofunction:: sprocketstracing.reporting.report_spans

.. autoclass:: sprocketstracing.reporting.NullReporter
   :members:

.. autoclass:: sprocketstracing.reporting.ZipkinReporter
   :members:

Span Propagation
----------------
.. autofunction:: sprocketstracing.propagation.get_syntax

.. autofunction:: sprocketstracing.propagation.add_syntax

.. autoclass:: sprocketstracing.propagation.NoPropagation
   :members:

.. autoclass:: sprocketstracing.propagation.PropagationSyntax
   :members:

.. autoclass:: sprocketstracing.propagation.B3PropagationSyntax
   :members:

Testing Utilities
-----------------
.. autoclass:: sprocketstracing.testing.RecordingReporter
   :members:
