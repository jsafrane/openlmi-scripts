# Copyright (C) 2012 Red Hat, Inc.  All rights reserved.
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA
#
# Authors: Michal Minar <miminar@redhat.com>
# -*- coding: utf-8 -*-
"""
Meta classes simplyfying declaration of user commands.

Each command is defined as a class with a set of properties. Some are
mandatory, the others have some default values. These properties are
transformed by metaclasses some function, classmethod or other property
depending on command type and semantic of property. Property itself
is removed from resulting class after being processed by meta class.
"""

import abc
import re

from lmi.scripts.common import get_logger
from lmi.scripts.common import errors
from lmi.scripts.common.command import base
from lmi.scripts.common.command import util
from lmi.shell.LMIReturnValue import LMIReturnValue

RE_CALLABLE = re.compile(
        r'^(?P<module>[a-z_]+(?:\.[a-z_]+)*):(?P<func>[a-z_]+)$',
        re.IGNORECASE)

LOG = get_logger(__name__)

def _handle_usage(name, dcl):
    """
    Take care of ``OWN_USAGE`` property. Supported values:

        * ``True``  - Means that documentation string of class is a usage
                      string.
        * ``False`` - No usage string for this command is defined.
        * ``"usage string"`string`` - This property is a usage string.

    Defaults to ``False``.

    Usage string is an input parameter to ``docopt`` command-line options
    parser.

    :param name: (``str``) Name o command class.
    :param bases: (``tuple``) Base classes of command class.
    :param dcl: (``dict``) Class dictionary, which is modified by this
        function.
    """
    has_own_usage = False
    hlp = dcl.pop('OWN_USAGE', False)
    if hlp is True:
        if dcl['__doc__'] is None:
            raise errors.LmiCommandInvalidProperty(dcl['__module__'], name,
                    "OWN_USAGE set to True, but no __doc__ string present!")
        has_own_usage = True
    elif isinstance(hlp, basestring):
        if not '__doc__' in dcl:
            dcl['__doc__'] = hlp
        else:
            if not 'get_usage' in dcl:
                def _new_get_usage(_self, proper=False):
                    """ Get the usage string for ``doctopt`` parser. """
                    return hlp
                dcl['get_usage'] = _new_get_usage
        has_own_usage = True
    if has_own_usage:
        if not 'has_own_usage' in dcl:
            dcl['has_own_usage'] = classmethod(lambda _cls: True)

class EndPointCommandMetaClass(abc.ABCMeta):
    """
    End point command does not have any subcommands. It's a leaf of
    command tree. It wraps some function in command library being
    referred to as an *associated function*. It handles following class
    properties:

        * ``CALLABLE`` - An associated function. Mandatory property.
        * ``OWN_USAGE`` - Usage string. Optional property.
    """

    @classmethod
    def _make_execute_method(mcs, bases, dcl, func):
        """
        Creates ``execute()`` method of a new end point command.

        :param mcs: (``type``) This meta class.
        :param bases: (``tuple``) Base classes of new command.
        :param dcl: (``dict``) Class dictionary being modified by this method.
        :param func: A callable wrapped by this new command. It's usually
            referred as *associated function*. If ``None``, no function will be
            created -- ``dcl`` won't be modified.
        """
        if func is not None and util.is_abstract_method(
                bases, 'execute', missing_is_abstract=True):
            del dcl['CALLABLE']
            def _execute(_self, *args, **kwargs):
                """ Invokes associated function with given arguments. """
                return func(*args, **kwargs)
            _execute.dest = func
            dcl['execute'] = _execute

    def __new__(mcs, name, bases, dcl):
        _handle_usage(name, dcl)
        try:
            func = dcl.get('CALLABLE')
            if isinstance(func, basestring):
                match = RE_CALLABLE.match(func)
                if not match:
                    raise errors.LmiCommandInvalidCallable(
                            dcl['__module__'], name,
                            'Callable "%s" has invalid format (\':\' expected)'
                            % func)
                mod_name = match.group('module')
                try:
                    func = getattr(__import__(mod_name, globals(), locals(),
                            [match.group('func')], 0),
                            match.group('func'))
                except (ImportError, AttributeError):
                    raise errors.LmiCommandImportFailed(
                            dcl['__module__'], name, func)
        except KeyError:
            mod = dcl['__module__']
            if not name.lower() in mod:
                raise errors.LmiCommandMissingCallable(
                        'Missing CALLABLE attribute for class "%s.%s".' % (
                            mod.__name__, name))
            func = mod[name.lower()]
        if func is not None and not callable(func):
            raise errors.LmiCommandInvalidCallable(
                '"%s" is not a callable object or function.' % (
                    func.__module__ + '.' + func.__name__))

        mcs._make_execute_method(bases, dcl, func)

        return super(EndPointCommandMetaClass, mcs).__new__(
                mcs, name, bases, dcl)


class SessionCommandMetaClass(EndPointCommandMetaClass):
    """
    Meta class for commands operating upon a session object.
    """
    pass


class ListerMetaClass(SessionCommandMetaClass):
    """
    Meta class for end-point lister commands. Handles following class
    properties:

        * ``COLUMNS`` - List of column names. Optional property.
    """

    def __new__(mcs, name, bases, dcl):
        cols = dcl.pop('COLUMNS', None)
        if cols is not None:
            if not isinstance(cols, (list, tuple)):
                raise errors.LmiCommandInvalidProperty(dcl['__module__'], name,
                        'COLUMNS class property must be either list or tuple')
            if not all(isinstance(c, basestring) for c in cols):
                raise errors.LmiCommandInvalidProperty(dcl['__module__'], name,
                        'COLUMNS must contain just column names as strings')
            def _new_get_columns(_cls):
                """ Return column names. """
                return cols
            dcl['get_columns'] = classmethod(_new_get_columns)

        return super(ListerMetaClass, mcs).__new__(mcs, name, bases, dcl)

class ShowInstanceMetaClass(SessionCommandMetaClass):
    """
    Meta class for end-point show instance commands. Additional handled
    properties:

        * DYNAMIC_PROPERTIES - Whether the associated function itself provides
            list of properties. Optional property.
        * PROPERTIES - List of instance properties to print. Optional property.

    These are translated in a ``render()``, which should be marked as
    abstract in base lister class.
    """

    @classmethod
    def _check_properties(mcs, name, dcl, props):
        """
        Make sanity check for ``PROPERTIES`` class property. Exception will
        be raised when any flaw discovered.

        :param mcs: (``type``) This meta-class.
        :param name: (``str``) Name of resulting command class.
        :param dcl: (``dict``) Class dictionary.
        :param props: (``list``) List of properties of ``None``.
        """
        if props is not None:
            for prop in props:
                if not isinstance(prop, (basestring, tuple, list)):
                    raise errors.LmiCommandInvalidProperty(
                            dcl['__module__'], name,
                            'PROPERTIES must be a list of strings or tuples')
                if isinstance(prop, (tuple, list)):
                    if (  len(prop) != 2
                       or not isinstance(prop[0], basestring)
                       or not callable(prop[1])):
                        raise errors.LmiCommandInvalidProperty(
                                dcl['__module__'], name,
                            'tuples in PROPERTIES must be: ("name", callable)')

    @classmethod
    def _make_render_all_properties(mcs, bases, dcl):
        """
        Creates ``render()`` method, rendering all properties of instance.

        :param bases: (``tuple``) Base classes of new command class.
        :param dcl: (``dict``) Class dictionary, it gets gets modified.
        """
        if util.is_abstract_method(bases, 'render', missing_is_abstract=True):
            def _render(_self, inst):
                """
                Return tuple of ``(column_names, values)`` ready for output by
                formatter.
                """
                column_names, values = [], []
                for prop_name, value in inst.properties.items():
                    column_names.append(prop_name)
                    if value is None:
                        value = ''
                    values.append(value)
                return (column_names, values)
            dcl['render'] = _render

    @classmethod
    def _make_render_with_properties(mcs, properties):
        """
        Creates ``render()`` method, rendering given instance properties.

        :param properties: (``list``) List of properties to render.
        :rtype: (``function``) Rendering method taking CIM instance as an
            argument.
        """
        def _render(self, inst):
            """
            Renders a limited set of properties and returns a pair of
            column names and values.
            """
            column_names, values = [], []
            for prop in properties:
                if isinstance(prop, basestring):
                    prop_name = prop
                    if not prop in inst.properties():
                        LOG().warn('property "%s" not present in instance'
                                ' of "%s"', prop, inst.path)
                        value = "UNKNOWN"
                    else:
                        value = getattr(inst, prop)
                else:
                    prop_name = prop[0]
                    try:
                        value = prop[1](inst)
                    except Exception as exc:
                        if self.app.options.debug:
                            LOG().exception(
                                    'failed to render property "%s"', prop[0])
                        else:
                            LOG().error(
                                    'failed to render property "%s": %s',
                                    prop[0], exc)
                        value = "ERROR"
                column_names.append(prop_name)
                values.append(value)
            return (column_names, values)
        return _render

    def __new__(mcs, name, bases, dcl):
        dynamic_properties = dcl.pop('DYNAMIC_PROPERTIES', False)
        if dynamic_properties and 'PROPERTIES' in dcl:
            raise errors.LmiCommandError(
                    dcl['__module__'], name,
                    'DYNAMIC_PROPERTIES and PROPERTIES are mutually exclusive')
        properties = dcl.pop('PROPERTIES', None)
        mcs._check_properties(name, dcl, properties)
        if properties is None and not dynamic_properties:
            dcl['render'] = mcs._make_render_all_properties(bases, dcl)
        elif properties is None and dynamic_properties:
            def _render_dynamic(self, return_value):
                """ Renderer of dynamic properties. """
                properties, inst = return_value
                return mcs._make_render_with_properties(properties)(self, inst)
            dcl['render'] = _render_dynamic
        elif properties is not None:
            dcl['render'] = mcs._make_render_with_properties(properties)

        return super(ShowInstanceMetaClass, mcs).__new__(
                mcs, name, bases, dcl)

class CheckResultMetaClass(SessionCommandMetaClass):
    """
    Meta class for end-point command "check result". Additional handled
    properties:

        * ``EXPECT`` - Value to compare against the return value.
            Mandatory property.

    ``EXPECT`` property is transformed into a ``check_result()`` method taking
    two arguments ``(options, result)`` and returning a boolean.
    """

    def __new__(mcs, name, bases, dcl):
        try:
            expect = dcl['EXPECT']
            if callable(expect):
                def _new_expect(_self, options, result):
                    """
                    Comparison function testing return value with *expect*
                    function.
                    """
                    if isinstance(result, LMIReturnValue):
                        result = result.rval
                    passed = expect(options, result)
                    return passed
            else:
                def _new_expect(_self, _options, result):
                    """ Comparison function testing by equivalence. """
                    if isinstance(result, LMIReturnValue):
                        result = result.rval
                    return expect == result
                _new_expect.expected = expect
            del dcl['EXPECT']
            dcl['check_result'] = _new_expect
        except KeyError:
            # EXPECT might be defined in some subclass
            pass

        return super(CheckResultMetaClass, mcs).__new__(mcs, name, bases, dcl)

class MultiplexerMetaClass(abc.ABCMeta):
    """
    Meta class for node command (not an end-point command). It handles
    following class properties:

        * ``COMMANDS`` - List of subcommands of this command. Mandatory
            property.
    """

    @classmethod
    def is_root_multiplexer(mcs, bases):
        """
        Check, whether particular class is root multiplexer class. It's the
        first class in an inheritance chain (from top to bottom) with assigned
        metaclass ``MultiplexerMetaClass``.

        :param bases: (``tuple``) List of base classes of particular class.
            This is equavalent of ``__class__`` attribute.
        :rtype: (``bool``) Is the 
        """
        for bcls in bases:
            if issubclass(type(bcls), MultiplexerMetaClass):
                return False
        return True

    def __new__(mcs, name, bases, dcl):
        if not mcs.is_root_multiplexer(bases):
            # check COMMANDS property and make it a classmethod
            if not 'COMMANDS' in dcl:
                raise errors.LmiCommandError('missing COMMANDS property')
            cmds = dcl.pop('COMMANDS')
            if not isinstance(cmds, dict):
                raise errors.LmiCommandInvalidProperty(dcl['__module__'], name,
                        'COMMANDS must be a dictionary')
            if not all(isinstance(c, basestring) for c in cmds.keys()):
                raise errors.LmiCommandInvalidProperty(dcl['__module__'], name,
                        'keys of COMMANDS dictionary must contain command'
                        ' names as strings')
            for cmd_name, cmd in cmds.items():
                if not base.RE_COMMAND_NAME.match(cmd_name):
                    raise errors.LmiCommandInvalidName(cmd, cmd_name)
                if not issubclass(cmd, base.LmiBaseCommand):
                    raise errors.LmiCommandError(dcl['__module__'], cmd_name,
                            'COMMANDS dictionary must be composed of'
                            ' LmiCommandBase subclasses, failed class: "%s"'
                            % cmd.__name__)
                if not cmd.is_end_point():
                    cmd.__doc__ = dcl['__doc__']
            def _new_child_commands(_cls):
                """ Returns list of subcommands. """
                return cmds
            dcl['child_commands'] = classmethod(_new_child_commands)

            # check documentation
            if dcl.get('__doc__', None) is None:
                LOG().warn('Command "%s.%s" is missing description string.',
                    dcl['__module__'], name)

            _handle_usage(name, dcl)

        return super(MultiplexerMetaClass, mcs).__new__(mcs, name, bases, dcl)
