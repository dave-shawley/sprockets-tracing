import unittest
try:
    from unittest import mock
except ImportError:
    import mock

from tornado import web
import opentracing


class SprocketsTracingTestCase(unittest.TestCase):

    def setUp(self):
        super(SprocketsTracingTestCase, self).setUp()
        self.saved_tracer = opentracing.tracer
        self.application = self.create_application()
        self.io_loop = mock.Mock()

    def tearDown(self):
        super(SprocketsTracingTestCase, self).tearDown()
        opentracing.tracer = self.saved_tracer

    def create_application(self):
        return web.Application(
            [],
            opentracing={'propagation_syntax': 'zipkin'})


def create_method_proxy(instance, method_name):
    """
    Mock a method so that you can see how it was called.

    :param instance: object to wrap the method for
    :param str method_name: name of the method to wrap
    :return: a :class:`unittest.mock.Mock` instance that wraps
        calls to `method_name` on `instance`
    :rtype: unittest.mock.Mock

    The named method of `instance` is patched with returned mock.  The
    mock is configured so that it simply calls the original method with
    the same parameters.

    """
    orig_method = getattr(instance, method_name)

    def wrapped(*args, **kwargs):
        return orig_method(*args, **kwargs)

    wrapping_mock = mock.Mock(name='{}.{}'.format(instance.__class__.__name__,
                                                  method_name),
                              side_effect=wrapped)
    setattr(instance, method_name, wrapping_mock)

    return wrapping_mock
