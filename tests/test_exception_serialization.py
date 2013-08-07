
# Copyright 2013 Red Hat, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import sys

import testscenarios

from oslo import messaging
from oslo.messaging._drivers import common as exceptions
from oslo.messaging.openstack.common import jsonutils
from tests import utils as test_utils

load_tests = testscenarios.load_tests_apply_scenarios


class NovaStyleException(Exception):

    format = 'I am Nova'

    def __init__(self, message=None, **kwargs):
        self.kwargs = kwargs
        if not message:
            message = self.format % kwargs
        super(NovaStyleException, self).__init__(message)


class KwargsStyleException(NovaStyleException):

    format = 'I am %(who)s'


def add_remote_postfix(ex):
    ex_type = type(ex)
    message = str(ex)
    str_override = lambda self: message
    new_ex_type = type(ex_type.__name__ + "_Remote", (ex_type,),
                       {'__str__': str_override,
                        '__unicode__': str_override})
    new_ex_type.__module__ = '%s_Remote' % ex.__class__.__module__
    try:
        ex.__class__ = new_ex_type
    except TypeError:
        ex.args = (message,) + ex.args[1:]
    return ex


class SerializeRemoteExceptionTestCase(test_utils.BaseTestCase):

    _log_failure = [
        ('log_failure', dict(log_failure=True)),
        ('do_not_log_failure', dict(log_failure=False)),
    ]

    _add_remote = [
        ('add_remote', dict(add_remote=True)),
        ('do_not_add_remote', dict(add_remote=False)),
    ]

    _exception_types = [
        ('bog_standard', dict(cls=Exception,
                              args=['test'],
                              kwargs={},
                              clsname='Exception',
                              modname='exceptions',
                              msg='test')),
        ('nova_style', dict(cls=NovaStyleException,
                            args=[],
                            kwargs={},
                            clsname='NovaStyleException',
                            modname=__name__,
                            msg='I am Nova')),
        ('nova_style_with_msg', dict(cls=NovaStyleException,
                                     args=['testing'],
                                     kwargs={},
                                     clsname='NovaStyleException',
                                     modname=__name__,
                                     msg='testing')),
        ('kwargs_style', dict(cls=KwargsStyleException,
                              args=[],
                              kwargs={'who': 'Oslo'},
                              clsname='KwargsStyleException',
                              modname=__name__,
                              msg='I am Oslo')),
    ]

    @classmethod
    def generate_scenarios(cls):
        cls.scenarios = testscenarios.multiply_scenarios(cls._log_failure,
                                                         cls._add_remote,
                                                         cls._exception_types)

    def setUp(self):
        super(SerializeRemoteExceptionTestCase, self).setUp()

    def test_serialize_remote_exception(self):
        errors = []

        def stub_error(msg, *a, **kw):
            if (a and len(a) == 1 and isinstance(a[0], dict) and a[0]):
                a = a[0]
            errors.append(str(msg) % a)

        self.stubs.Set(exceptions.LOG, 'error', stub_error)

        try:
            try:
                raise self.cls(*self.args, **self.kwargs)
            except Exception as ex:
                if self.add_remote:
                    ex = add_remote_postfix(ex)
                raise ex
        except Exception:
            exc_info = sys.exc_info()

        serialized = exceptions.serialize_remote_exception(
            exc_info, log_failure=self.log_failure)

        failure = jsonutils.loads(serialized)

        self.assertEqual(failure['class'], self.clsname, failure)
        self.assertEqual(failure['module'], self.modname)
        self.assertEqual(failure['message'], self.msg)
        self.assertEqual(failure['args'], [self.msg])
        self.assertEqual(failure['kwargs'], self.kwargs)

        # Note: _Remote prefix not stripped from tracebacks
        tb = ex.__class__.__name__ + ': ' + self.msg
        self.assertIn(tb, ''.join(failure['tb']))

        if self.log_failure:
            self.assertTrue(len(errors) > 0, errors)
        else:
            self.assertEqual(len(errors), 0, errors)


SerializeRemoteExceptionTestCase.generate_scenarios()


class DeserializeRemoteExceptionTestCase(test_utils.BaseTestCase):

    _standard_allowed = [__name__, 'exceptions']

    scenarios = [
        ('bog_standard',
         dict(allowed=_standard_allowed,
              clsname='Exception',
              modname='exceptions',
              cls=Exception,
              args=['test'],
              kwargs={},
              str='test\ntraceback\ntraceback\n',
              message='test',
              remote_name='Exception',
              remote_args=('test\ntraceback\ntraceback\n', ),
              remote_kwargs={})),
        ('nova_style',
         dict(allowed=_standard_allowed,
              clsname='NovaStyleException',
              modname=__name__,
              cls=NovaStyleException,
              args=[],
              kwargs={},
              str='test\ntraceback\ntraceback\n',
              message='I am Nova',
              remote_name='NovaStyleException_Remote',
              remote_args=('I am Nova', ),
              remote_kwargs={})),
        ('nova_style_with_msg',
         dict(allowed=_standard_allowed,
              clsname='NovaStyleException',
              modname=__name__,
              cls=NovaStyleException,
              args=['testing'],
              kwargs={},
              str='test\ntraceback\ntraceback\n',
              message='testing',
              remote_name='NovaStyleException_Remote',
              remote_args=('testing', ),
              remote_kwargs={})),
        ('kwargs_style',
         dict(allowed=_standard_allowed,
              clsname='KwargsStyleException',
              modname=__name__,
              cls=KwargsStyleException,
              args=[],
              kwargs={'who': 'Oslo'},
              str='test\ntraceback\ntraceback\n',
              message='I am Oslo',
              remote_name='KwargsStyleException_Remote',
              remote_args=('I am Oslo', ),
              remote_kwargs={})),
        ('not_allowed',
         dict(allowed=[],
              clsname='Exception',
              modname='exceptions',
              cls=messaging.RemoteError,
              args=[],
              kwargs={},
              str=("Remote error: Exception test\n"
                   "[u'traceback\\ntraceback\\n']."),
              msg=("Remote error: Exception test\n"
                   "[u'traceback\\ntraceback\\n']."),
              remote_name='RemoteError',
              remote_args=(),
              remote_kwargs={'exc_type': 'Exception',
                             'value': 'test',
                             'traceback': 'traceback\ntraceback\n'})),
        ('unknown_module',
         dict(allowed=['notexist'],
              clsname='Exception',
              modname='notexist',
              cls=messaging.RemoteError,
              args=[],
              kwargs={},
              str=("Remote error: Exception test\n"
                   "[u'traceback\\ntraceback\\n']."),
              msg=("Remote error: Exception test\n"
                   "[u'traceback\\ntraceback\\n']."),
              remote_name='RemoteError',
              remote_args=(),
              remote_kwargs={'exc_type': 'Exception',
                             'value': 'test',
                             'traceback': 'traceback\ntraceback\n'})),
        ('unknown_exception',
         dict(allowed=['exceptions'],
              clsname='FarcicalError',
              modname='exceptions',
              cls=messaging.RemoteError,
              args=[],
              kwargs={},
              str=("Remote error: FarcicalError test\n"
                   "[u'traceback\\ntraceback\\n']."),
              msg=("Remote error: FarcicalError test\n"
                   "[u'traceback\\ntraceback\\n']."),
              remote_name='RemoteError',
              remote_args=(),
              remote_kwargs={'exc_type': 'FarcicalError',
                             'value': 'test',
                             'traceback': 'traceback\ntraceback\n'})),
        ('unknown_kwarg',
         dict(allowed=['exceptions'],
              clsname='Exception',
              modname='exceptions',
              cls=messaging.RemoteError,
              args=[],
              kwargs={'foobar': 'blaa'},
              str=("Remote error: Exception test\n"
                   "[u'traceback\\ntraceback\\n']."),
              msg=("Remote error: Exception test\n"
                   "[u'traceback\\ntraceback\\n']."),
              remote_name='RemoteError',
              remote_args=(),
              remote_kwargs={'exc_type': 'Exception',
                             'value': 'test',
                             'traceback': 'traceback\ntraceback\n'})),
        ('system_exit',
         dict(allowed=['exceptions'],
              clsname='SystemExit',
              modname='exceptions',
              cls=messaging.RemoteError,
              args=[],
              kwargs={},
              str=("Remote error: SystemExit test\n"
                   "[u'traceback\\ntraceback\\n']."),
              msg=("Remote error: SystemExit test\n"
                   "[u'traceback\\ntraceback\\n']."),
              remote_name='RemoteError',
              remote_args=(),
              remote_kwargs={'exc_type': 'SystemExit',
                             'value': 'test',
                             'traceback': 'traceback\ntraceback\n'})),
    ]

    def setUp(self):
        super(DeserializeRemoteExceptionTestCase, self).setUp()
        self.conf.register_opts(exceptions._exception_opts)

    def test_deserialize_remote_exception(self):
        self.config(allowed_rpc_exception_modules=self.allowed)

        failure = {
            'class': self.clsname,
            'module': self.modname,
            'message': 'test',
            'tb': ['traceback\ntraceback\n'],
            'args': self.args,
            'kwargs': self.kwargs,
        }

        serialized = jsonutils.dumps(failure)

        ex = exceptions.deserialize_remote_exception(self.conf, serialized)

        self.assertIsInstance(ex, self.cls)
        self.assertEqual(ex.__class__.__name__, self.remote_name)
        self.assertEqual(str(ex), self.str)
        if hasattr(self, 'msg'):
            self.assertEqual(ex.msg, self.msg)
        else:
            self.assertEqual(ex.message, self.message)
        self.assertEqual(ex.args, self.remote_args)