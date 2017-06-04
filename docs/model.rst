Process Models
==============

HTTP Requests
-------------
HTTP request spans can be either root spans or child spans.  This is
determined by the configured propagation syntax -- in the case of B3
propagation, the presense of ``X-B3-ParentSpanId`` header creates a
child span.

Span Context Attributes
~~~~~~~~~~~~~~~~~~~~~~~

+-----------------+-----------------------------------------------------+
| span_id         | set from headers or to a new value                  |
+-----------------+-----------------------------------------------------+
| trace_id        | set from headers or to a new value                  |
+-----------------+-----------------------------------------------------+
| service_name    | service name from the opetracing configuration      |
+-----------------+-----------------------------------------------------+
| service_endpoint| set based on the request host                       |
+-----------------+-----------------------------------------------------+

Tags
~~~~

+-----------------+-----------------------------------------------------+
| span.kind       | set to ``server``                                   |
+-----------------+-----------------------------------------------------+
| server.type     | set to ``http``                                     |
+-----------------+-----------------------------------------------------+
| http.method     | stores the HTTP method                              |
+-----------------+-----------------------------------------------------+
| http.url        | stores the full URL reconstructed from the request  |
+-----------------+-----------------------------------------------------+
| http.version    | stores the requested HTTP version                   |
+-----------------+-----------------------------------------------------+
| peer.address    | stores the client's IP endpoint                     |
+-----------------+-----------------------------------------------------+
| http.user_agent | stores the user agent if present                    |
+-----------------+-----------------------------------------------------+

Consuming Events
----------------
AMQP consumers present an interesting problem -- the messaging can be either
one-way or request-response.  Modelling one-way eventing is based on the
recommendation of the `zipkin.io <http://zipkin.io/pages/instrumenting.html>`_
documentation.  The event producer starts a span as a client of the broker
and the consumer finishes the span by issuing a "server receive" on behalf
of the broker.  Then the consumer starts a fresh span as a "server" that is
associated with the same trace.  In Zipkin this looks like::

   [- Producer -------------]
       (A) [- Broker -------------] (B)
                           [- Consumer -------------------]

The start of the "broker" span (A) is issued by the producer of the message
and the finish (B) is issued by the consumer.  In a perfect world, the broker
would recognize the headers and advertise the span on it's own.  Without that
it is up to the producer and consumer to synthesize the message.  The tricky
part of getting this working properly is that the broker spans service name
and IP endpoints need to be consistent for many of the tracing tools to honor
the span.  The recommended approach is to use the IP address and port number
that the producer is connecting to when publishing the message.  This
*should* be the same as the address the consumer is consuming from -- if you
are using RabbitMQ, then the endpoint would be the server address and port
5,672.  The service name also has to match.

It is important to realize that the *broker* span is separate from the
producer and consumer spans.  It is started *BEFORE* the producer publishes
to message to the AMQP broker.  The span is finished as soon as the broker
delivers the message to the consumer.

RabbitMQ Example
~~~~~~~~~~~~~~~~
Propagation of tracing information in AMQP is similar to HTTP.  The span
information is included in the message as the ``headers`` property.

.. rubric:: Producer Tags

The producer starts the broker span using the following pattern of tags.
The ``producer`` span kind triggers the implementation to start the broker
span and it expects the ``broker.`` prefixed tags to identify the server-side
of the RabbitMQ connection.

+--------------------+-----------------------------------------------------+
| span.kind          | ``producer``                                        |
+--------------------+-----------------------------------------------------+
| amqp.exchange      | Name of the exchange that was published to.         |
+--------------------+-----------------------------------------------------+
| amqp.routing_key   | Routing key that the message was published with.    |
+--------------------+-----------------------------------------------------+
| broker.service     | ``rabbitmq``                                        |
+--------------------+-----------------------------------------------------+
| broker.address     | IP address of the RabbitMQ server.                  |
+--------------------+-----------------------------------------------------+
| broker.port        | TCP port of the RabbitMQ server (e.g., 5672).       |
+--------------------+-----------------------------------------------------+

.. rubric:: Consumer Tags

The consumer completes the broker span using the following pattern of tags.
The ``consumer`` span kind triggers the implementation to finish the broker
span using the ``broker.`` prefixed tags to identify the RabbitMQ server
endpoint that sent the message to the consumer.

+--------------------+-----------------------------------------------------+
| span.kind          | ``consumer``                                        |
+--------------------+-----------------------------------------------------+
| amqp.exchange      | Exchange that the message was received from.        |
+--------------------+-----------------------------------------------------+
| amqp.routing_key   | Routing key from the received message.              |
+--------------------+-----------------------------------------------------+
| broker.service     | ``rabbitmq``                                        |
+--------------------+-----------------------------------------------------+
| broker.address     | IP address that the consumer connected to.          |
+--------------------+-----------------------------------------------------+
| broker.port        | TCP port of the server side of the connection.      |
+--------------------+-----------------------------------------------------+
