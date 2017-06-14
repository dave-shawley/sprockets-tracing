Tracing Playground
==================
This directory contains a non-trivial example system that sends email to a
`mailtrap.io <https://mailtrap.io/>`_ mailbox, retrieves it and stores it in
a local MongoDB database.  The result is the following distributed system
represented in a docker compose environment::

                                  _ _
   (1)       +---------+ (2)     | | |
   --------->| message |-------->| | |___
             | server  |         |     o |
             +---------+         +_______+
                                     |
             +---------+        +----------+ (3)       +-------------+
             | mongodb |        | emailer  |---------->| mailtrap.io |
             +---------+        +----------+           +-------------+
                  ^                                           ^
                  |         (5) +----------+ (4)              |
                  \_____________|   mail   |__________________/
                                |  poller  |
                                +----------+

1. HTTP POST to the ``/email`` endpoint of the message server starts the
   process of sending an email through the system.
2. The message server injects a request into RabbitMQ to send the email.
3. RabbitMQ sends the request to the emailer consumer which sends the
   email to mailtrap.io using the Python SMTP machinery.
4. The mail poller is a Tornado application that periodically polls the
   mailtrap.io mailbox, retrieves message content, stores the message
   locally, and then deletes it from the mailtrap.io inbox.
5. The message headers and content are stored in the MongoDB instance that
   is running in the docker environment.

So that is the most outlandish way to send an email but it is a non-trivial
distributed system.  In addition to a working distributed system, the three
python components (message server, consumer, and mail poller) are
instrumented using sprockets-tracing and emit trace information to a zipkin
instance that is included in the docker environment.

Many distributed tracing architectures are based on the concept of a
*traces* and *spans*.  A **span** is a period of time that an actor is
performing a **named task**.  It is a discrete period of time identified
by a starting and ending timestamp.  Spans also have a set of key-value
pairs and zero or more parents.  A **trace** is a set of spans that have the
same unique *trace id*.

Another way to look at the sequence of events presented above is as a series
of spans::

    [ (1) schedule-email ]
                      [ (2) amqp-publish ]
                                       [ emailer                ]
                                             [ (3) send-email ]

    A-----------------B--C-------------D-E---F----------------G-H----->
    time

The Mail Poller is a separate trace since it is unrelated to the scheduling
and sending of the email message::

    [ poll-email                                                           ]
       [(4) fetch-inbox]
                         [fetch-message]
                                        [(5) store-message]
                                                            [delete-message]

    I--J---------------K-L-------------MN-----------------O-P--------------Q
    time

Running the Demo
----------------
First of all you need to sign up for a mailtrap.io account.  Go to
`mailtrap.io <https://mailtrap.io/register/signup>`_ and create a new
account.  The free account has more than enough capacity to run this demo.
Once you have a mailtrap account, navigate to the demo inbox and create a
file named *.env* in the playground directory with the following lines::

   MAILTRAP_USER=f3c461d7eee050fce
   MAILTRAP_PASSWORD=74eec5d8432d62
   MAILTRAP_BOXID=35577
   MAILTRAP_TOKEN=47c37c235891ed9d952b7deb2a249889

The values above are random values so don't use them.  The user and password
values are on the SMTP Settings Credentials tab shown for an empty mailbox.
The API token is in the "API" section of you account settings.  The mailbox
ID is a little more difficult to come by since it is not visible in the UI.
It is in the URL of the inbox.

Once you have created the *.env* file, run the *./run* script to build the
containers and bring up the environment.  This will take a few seconds since
it has to build docker containers for the individual services.  Once the
script has completed, it will output the URLs used to access the various
services.  The most useful one is the zipkin URL::

   Rabbit MQ:      http://127.0.0.1:32808
   Zipkin:         http://127.0.0.1:32810
   Message-Server: http://127.0.0.1:32812

The *send-email* script prompts for information, sends an email through the
system destined for the mailtrap inbox, and outputs the URL for the zipkin
trace.

What happened?
--------------

(1) HTTP POST
^^^^^^^^^^^^^
This is the initiating action.  It is a simple HTTP POST to a Tornado web
application.  The message format is described by the following JSON schema.
See `json-schema.org <http://json-schema.org>`_ for an in-depth discussion
of the format.  Neither the message server or the emailer consumer are
validating the incoming documents so it is up to you to ensure that the
request documents make sense.

.. code-block:: json

   {
     "type": "object",
     "properties": {
       "sender": {
         "type": "object",
         "properties": {
           "address": {
             "type": "string",
             "format": "email"
           },
           "display": {
             "type": "string"
           },
           "required": ["address"]
       },
       "recipient": {
         "type": "object",
         "properties": {
           "address": {
             "type": "string",
             "format": "email"
           },
           "display": {
             "type": "string"
           },
           "required": ["address"]
       },
       "subject": {
         "type": "string",
         "minLength": 1
       },
       "body": {
         "type": "string",
         "minLength": 1
       }
     },
     "required": ["sender", "recipient", "subject", "body"]
   }

A simple example message is:

.. code-block:: http

   POST /email HTTP/1.1
   Host: 127.0.0.1:32784
   Content-Type: application/json
   Connection: close
   Date: Mon Jun 12 07:50:27 EDT 2017

   {
      "sender": {"address": "me@example.com"},
      "recipient": {"address": "54d15d43b460697c@mailtrap.io"},
      "subject": "Something catchy",
      "body": "Whatever you want"
   }

When the message server receives a request it starts a new trace that is
propagated through the system.  It attaches two spans to the trace -- one
for the HTTP request that it services and another for the AMQP RPC that it
initiates.  The open-tracing objects look something like::

   Span d3a4c80eb70ff124: schedule-email
      trace: b3d9bc001fb01494a21a295b9565bd82
      parent: null
      start: A (message-server)
      end: C (message-server)
      span.kind: server
      peer.address: 127.0.0.1
      http.method: POST
      http.url: http://127.0.0.1:32784/email
      http.version: HTTP/1.1

The *schedule-email* span is completed when the message server sends the
response.  The *amqp-publish* span is started by the message server and
remains open until the consumer finishes it.

(2) AMQP Publish
^^^^^^^^^^^^^^^^
The AMQP publish span is started by the message server and finished by the
consumer when it receives the message.  On the wire this is represented by
two span records that share the same span ID::

   Span 8dc810654b39fa50: amqp-publish
      trace: b3d9bc001fb01494a21a295b9565bd82
      parent: d3a4c80eb70ff124
      start: B (message-server)
      span.kind: producer
      broker.address: 127.0.0.1
      broker.service: rabbitmq
      broker.port: 5672
      amqp.exchange: rpc
      amqp.routing_key: send.email

    Span ae90036046e351a8: amqp-publish
      trace: b3d9bc001fb01494a21a295b9565bd82
      parent: d3a4c80eb70ff124
      end: E (rabbitmq)
      span.kind: consumer
      broker.address: 127.0.0.1
      broker.service: rabbitmq
      broker.port: 5672
      amqp.exchange: rpc
      amqp.routing_key: send.email

The ability for spans to be started in one service and finished in another
is accomplished by propagating the trace and span identifiers from one
process to another.  In both HTTP and AMQP it is accomplished by passing
header values that the tracing software recognizes.

(3) Sending Email
^^^^^^^^^^^^^^^^^
The next step is for the consumer to transmit the Email message to the
mailtrap service.  Since the service is external to the distributed tracing
system, it is represented as a simple span that is child of the consumer's
span::

   Span 723c26e07dae71c3: emailer
      trace: b3d9bc001fb01494a21a295b9565bd82
      parent: ae90036046e351a8
      start: D (emailer)
      end: H (emailer)
      span.kind: server
      amqp.exchange: rpc
      amqp.routing_key: send.email

   Span db105e9094de23f4: send-email
      trace: b3d9bc001fb01494a21a295b9565bd82
      parent: 723c26e07dae71c3
      start: F (emailer)
      end: G (emailer)
      span.kind: client
      peer.hostname: 54.86.221.84
      smtp.server: smtp.mailtrap.io
      smtp.port: 465
      smtp.tls: true
      smtp.payload_size: 636

(4) Fetch Inbox
^^^^^^^^^^^^^^^
The mail-poller periodically fetches the inbox from the mailtrap service,
retrieves the message content, and stashes it off on MongoDB.  This is done
under a new trace identifier though we could propagate the trace information
through the SMTP headers in the same way that they are propagated through
HTTP and AMQP headers.  I just chose not to propagate the information::

   Span 5fdbbb12d31cfb4e: poll-email
      trace: d331504ff129d8a0d7be5827beca43fd
      start: I (mail-poller)
      end: Q (mail-poller)
      span.kind: periodic

   Span 0ee0e48b947daae9: fetch-inbox
      trace: d331504ff129d8a0d7be5827beca43fd
      parent: 5fdbbb12d31cfb4e
      start: J (mail-poller)
      end: K (mail-pooler)
      span.kind: client
      peer.hostname: mailtrap.io
      peer.port: 443
      server.address: 54.86.221.84:443
      http.method: GET
      http.status: 200
      http.url: https://mailtrap.io/api/v1/inboxes/84127/messages

   Span 9d1d32eb26ace495: fetch-message
      trace: d331504ff129d8a0d7be5827beca43fd
      parent: 5fdbbb12d31cfb4e
      start: L (mail-poller)
      end: M (mail-poller)
      span.kind: client
      peer.hostname: mailtrap.io
      peer.port: 443
      server.address: 54.86.221.84:443
      http.method: GET
      http.status: 200
      http.url: https://mailtrap.io/api/v1/inboxes/84127/messages/448292754/body.eml

(5) Storing the Message
^^^^^^^^^^^^^^^^^^^^^^^
Storing the message in MongoDB is another example of a client-side RPC span
that is part of the poll-email trace::

   Span c315b80735377d39: store-message
      trace: d331504ff129d8a0d7be5827beca43fd
      parent: 5fdbbb12d31cfb4e
      start: N (mail-poller)
      end: O (mail-poller)
      span.kind: client
      db.type: mongodb
      db.instance: messages.raw
      db.object_id: 593d991bd6749700019e4d99
      server.address: 172.18.0.7:27017

The final span in the trace is the client-side of the RPC span for deleting
a message from the mailtrap service::

   Span e9a79cb6d5f43404: delete-message
      trace: d331504ff129d8a0d7be5827beca43fd
      parent: 5fdbbb12d31cfb4e
      start: P (mail-poller)
      end: Q (mail-poller)
      span.kind: client
      peer.hostname: mailtrap.io
      peer.port: 443
      server.address: 54.86.221.84:443
      http.method: DELETE
      http.status: 200
      http.url: https://mailtrap.io/api/v1/inboxes/84127/messages/448292754
