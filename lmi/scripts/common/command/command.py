# Copyright (c) 2013, Red Hat, Inc. All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice,
#    this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
# The views and conclusions contained in the software and documentation are
# those of the authors and should not be interpreted as representing official
# policies, either expressed or implied, of the FreeBSD Project.
#
# Authors: Michal Minar <miminar@redhat.com>
#
"""
Module with abstractions for representing subcommand of lmi meta-command.
"""

import abc
import inspect
import re
from docopt import docopt

from lmi.scripts.common import Configuration
from lmi.scripts.common import get_logger
from lmi.scripts.common import errors
from lmi.scripts.common import formatter
from lmi.scripts.common.command import meta
from lmi.scripts.common.command import base

RE_OPT_BRACKET_ARGUMENT = re.compile('^<(?P<name>[^>]+)>$')
RE_OPT_UPPER_ARGUMENT = re.compile('^(?P<name>[A-Z]+(?:[_-][A-Z]+)*)$')
RE_OPT_SHORT_OPTION = re.compile('^-(?P<name>[a-z])$', re.IGNORECASE)
RE_OPT_LONG_OPTION = re.compile('^--(?P<name>[a-z_-]+)$', re.IGNORECASE)

LOG = get_logger(__name__)

def opt_name_sanitize(opt_name):
    """
    Make a function parameter name out of option name. This replaces any
    character not suitable for python identificator with ``'_'`` and
    make the whole string lowercase.

    :param opt_name: (``str``) Option name.
    :rtype: (``str``) Modified option name.
    """
    return re.sub(r'[^a-zA-Z]', '_', opt_name).lower()

def options_dict2kwargs(options):
    """
    Convert option name from resulting docopt dictionary to a valid python
    identificator token used as function argument name.

    :param options: (``dict``) Dictionary returned by docopt call.
    :rtype: (``dict``) New dictionary with keys passeable to function
        as argument names.
    """
    # (new_name, value) for each pair in options dictionary
    kwargs = {}
    # (new_name, name)
    orig_names = {}
    for name, value in options.items():
        for (reg, func) in (
                (RE_OPT_BRACKET_ARGUMENT, lambda m: m.group('name')),
                (RE_OPT_UPPER_ARGUMENT,   lambda m: m.group('name')),
                (RE_OPT_SHORT_OPTION,     lambda m: m.group(0)),
                (RE_OPT_LONG_OPTION,      lambda m: m.group(0)),
                (base.RE_COMMAND_NAME,    lambda m: m.group(0))):
            match = reg.match(name)
            if match:
                new_name = func(match)
                break
        else:
            raise errors.LmiError(
                    'failed to convert argument "%s" to function option' % name)
        new_name = opt_name_sanitize(new_name)
        if new_name in kwargs:
            raise errors.LmiError('option clash for "%s" and "%s", which both'
                ' translate to "%s"' % (name, orig_names[new_name], new_name))
        kwargs[new_name] = value
        orig_names[new_name] = name
    return kwargs

class LmiCommandMultiplexer(base.LmiBaseCommand):
    """
    Base class for node commands. It consumes just part of command line
    arguments and passes the remainder to one of its subcommands.

    Example usage:

        class MyCommand(LmiCommandMultiplexer):
            '''
            My command description.

            Usage: %(cmd)s mycommand (subcmd1 | subcmd2)
            '''
            COMMANDS = {'subcmd1' : Subcmd1, 'subcmd2' : Subcmd2}

    Where ``Subcmd1`` and ``Subcmd2`` are some other ``LmiBaseCommand``
    subclasses. Documentation string must be parseable with ``docopt``.

    ``COMMANDS`` property will be translated to ``child_commands()`` class
    method by ``MultiplexerMetaClass``.
    """
    __metaclass__ = meta.MultiplexerMetaClass

    @classmethod
    def is_end_point(cls):
        return False

    def run_subcommand(self, cmd_name, args):
        """
        Pass control to a subcommand identified by given name.

        :param cmd_name: (``str``) Name of direct subcommand, whose ``run()``
            method shall be invoked.
        :param args: (``list``) List of arguments for particular subcommand.
        """
        if not isinstance(cmd_name, basestring):
            raise TypeError("cmd_name must be a string")
        if not isinstance(args, (list, tuple)):
            raise TypeError("args must be a list")
        try:
            cmd_cls = self.child_commands()[cmd_name]
            return cmd_cls(self.app, cmd_name, self).run(args)
        except KeyError:
            self.app.stderr.write(self.get_usage())
            LOG().critical('unexpected command "%s"', cmd_name)
            return 1

    def run(self, args):
        """
        Handle optional parameters, retrieve desired subcommand name and
        pass the remainder of arguments to it.

        :param args: (``list``) List of arguments with at least subcommand name.
        """
        if not isinstance(args, (list, tuple)):
            raise TypeError("args must be a list")
        full_args = self.cmd_name_args[1:] + args
        # check the --help ourselves (the default docopt behaviour checks
        # also for --version)
        options = docopt(self.get_usage(), full_args, help=False)
        if options.pop('--help', False):
            self.app.stdout.write(self.get_usage())
            return 0
        return self.run_subcommand(args[0], args[1:])

class LmiEndPointCommand(base.LmiBaseCommand):
    """
    Base class for any leaf command.

    List of additional recognized properties:
        * ``CALLABLE``  - Associated function. Will be wrapped in ``execute()``
                          method and will be accessible directly as a
                          ``cmd.execute.dest`` property. It may be specified
                          either as a string in form
                          ``"<module_name>:<callable>"`` or as a reference to
                          callable itself.
        * ``FORMATTER`` - Default formatter factory for instances of given
                          command. This factory accepts an output stream as
                          the only parameter and returns an instance of
                          ``lmi.scripts.common.formatter.Formatter``.
    """
    __metaclass__ = meta.EndPointCommandMetaClass

    def __init__(self, *args, **kwargs):
        super(LmiEndPointCommand, self).__init__(*args, **kwargs)
        self._formatter = None

    @abc.abstractmethod
    def execute(self, *args, **kwargs):
        """
        Subclasses must override this method to pass given arguments to
        command library function. This function shall be specified in
        ``CALLABLE`` property.
        """
        raise NotImplementedError("execute method must be overriden"
                " in subclass")

    @classmethod
    def default_formatter(cls):
        """
        Subclasses shall override this method to provide default formatter
        factory for printing output.

        :rtype: (``type``) Subclass of basic formatter.
        """
        return formatter.Formatter

    def run_with_args(self, args, kwargs):
        """
        Process end-point arguments and exit.

        :param args: (``list``) Positional arguments to pass to associated
            function in command library.
        :param kwargs: (``dict``) Keyword arguments as a dictionary.
        :rtype: (``int``) Exit code of application.
        """
        self.execute(*args, **kwargs)

    @property
    def formatter(self):
        """
        Return instance of default formatter.
        """
        if self._formatter is None:
            self._formatter = self.default_formatter()(self.app.stdout)
        return self._formatter

    def _make_end_point_args(self, options):
        """
        Creates a pair of positional and keyword arguments for a call to
        associated function from command line options. All keyword
        options not expected by target function are removed.

        :param options: (``dict``) Output of ``docopt`` parser.
        :rtype: (``tuple``) Positional and keyword arguments as a pair.
        """
        # if execute method does not have a *dest* attribute, then it's
        # itself a destination
        dest = getattr(self.execute, "dest", self.execute)
        argspec = inspect.getargspec(dest)
        kwargs = options_dict2kwargs(options)
        to_remove = []
        if argspec.keywords is None:
            for opt_name in kwargs:
                if opt_name not in argspec.args[1:]:
                    LOG().debug('option "%s" not handled in function "%s",'
                        ' ignoring', opt_name, self.cmd_name)
                    to_remove.append(opt_name)
        for opt_name in to_remove:
            # remove options unhandled by function
            del kwargs[opt_name]
        args = []
        for arg_name in argspec.args[1:]:
            if arg_name not in kwargs:
                raise errors.LmiCommandError(
                    self.__module__, self.__class__.__name__,
                    'registered command "%s" expects option "%s", which'
                    ' is not covered in usage string'
                    % (self.cmd_name, arg_name))
            args.append(kwargs.pop(arg_name))
        return args, kwargs

    def _parse_args(self, args):
        """
        Run ``docopt`` command line parser on given list of arguments.
        Removes all unrelated commands from created dictionary of options.

        :param args: (``list``) List of command line arguments just after the
            current command.
        :rtype: (``dict``) Dictionary with parsed options. Please refer to
            ``docopt`` documentation for more information on
            http://docopt.org/.
        """
        full_args = self.cmd_name_args[1:] + args
        options = docopt(self.get_usage(), full_args, help=False)

        # remove all command names from options
        cmd = self.parent
        while cmd is not None and not cmd.has_own_usage():
            cmd = cmd.parent
        if cmd is not None:
            for scn in cmd.child_commands():
                try:
                    del options[scn]
                except KeyError:
                    LOG().warn('usage string of "%s.%s" command does not'
                            ' contain registered command "%s" command',
                            cmd.__module__, cmd.__class__.__name__, scn)
        # remove also the root command name from options
        if cmd is not None and cmd.cmd_name in options:
            del options[cmd.cmd_name]
        return options

    def verify_options(self, options):
        """
        This method can be overriden in subclasses to check, whether the
        options given on command line are valid. If any flaw is discovered, an
        ``LmiInvalidOptions`` exception shall be raised. Any returned value is
        ignored. Note, that this is run before ``transform_options()`` method.

        :param options: (``dict``) Dictionary as returned by ``docopt`` parser.
        """
        pass

    def transform_options(self, options):
        """
        This method can be overriden in subclasses if options shall be somehow
        modified before passing them associated function. Run after
        ``verify_options()`` method.

        :param options: (``dict``) Dictionary as returned by ``docopt`` parser.
        """
        pass

    def produce_output(self, data):
        """
        This method can be use to render and print results with default
        formatter.

        :param data: Is an object expected by the ``produce_output()`` method
            of formatter.
        """
        self.formatter.produce_output(data)

    def run(self, args):
        """
        Create options dictionary from input arguments, verify them,
        transform them, make positional and keyword arguments out of them and
        pass them to ``process_session()``.

        :param args: (``list``) List of command arguments.
        :rtype: (``int``) Exit code of application.
        """
        options = self._parse_args(args)
        self.verify_options(options)
        self.transform_options(options)
        args, kwargs = self._make_end_point_args(options)
        return self.run_with_args(args, kwargs)

class LmiSessionCommand(LmiEndPointCommand):
    """
    Base class for end-point commands operating upon a session object.
    """
    __metaclass__ = meta.SessionCommandMetaClass

    @abc.abstractmethod
    def process_session(self, session, args, kwargs):
        """
        Process each host of given session, call the associated command
        function, collect results and print it to standard output.

        This shall be overriden by a subclass.

        :param session: (``Session``) Session object with set of hosts.
        :param args: (``list``) Positional arguments to pass to associated
            function in command library.
        :param kwargs: (``dict``) Keyword arguments as a dictionary.
        :rtype: (``int``) Exit code of application.
        """
        raise NotImplementedError("process_session must be overriden"
                " in subclass")

    def run_with_args(self, args, kwargs):
        self.process_session(self.app.session, args, kwargs)

class LmiLister(LmiSessionCommand):
    """
    End point command outputting a table for each host. Associated function
    shall return a list of rows. Each row is represented as a tuple holding
    column values.

    List of additional recognized properties:

        * ``COLUMNS`` - Column names. It's a tuple with name for each column.
                        Each row shell then contain the same number of items
                        as this tuple. If omitted, associated function is
                        expected to provide them in the first row of returned
                        list. It's translated to ``get_columns()`` class
                        method.
    """
    __metaclass__ = meta.ListerMetaClass

    @classmethod
    def get_columns(cls):
        """
        Return a column names for resulting table. ``COLUMNS`` property
        will be converted to this class method. If ``None``, the associated
        function shall return column names as the first tuple of returned
        list.

        :rtype: (``list``) Column names.
        """
        return None

    @classmethod
    def default_formatter(cls):
        return formatter.CsvFormatter

    def take_action(self, connection, args, kwargs):
        """
        Collects results of single host.

        :param connection: (``lmi.shell.LMIConnection``) Connection to
            a single host.
        :param args: (``list``) Positional arguments for associated function.
        :param kwargs: (``dict``) Keyword arguments for associated function.
        :rtype: (``tuple``) Column names and item list as a pair.
        """
        res = self.execute(connection, *args, **kwargs)
        columns = self.get_columns()
        if columns is None:
            # let's get columns from the first row
            columns = next(res)
        return (columns, res)

    def process_session(self, session, args, kwargs):
        for connection in session:
            if len(session) > 1:
                self.app.stdout.write("="*79 + "\n")
                self.app.stdout.write("Host: %s\n" % connection.hostname)
                self.app.stdout.write("="*79 + "\n")
            column_names, data = self.take_action(connection, args, kwargs)
            self.produce_output((column_names, data))
            if len(session) > 1:
                self.app.stdout.write("\n")
        return 0

class LmiShowInstance(LmiSessionCommand):
    """
    End point command producing a list of properties of particular CIM
    instance. Either reduced list of properties to print can be specified, or
    the associated function alone can decide, which properties shall be
    printed. Associated function is expected to return CIM instance as a
    result.

    List of additional recognized properties:

        * ``DYNAMIC_PROPERTIES`` - A boolean saying, whether the associated
            function alone shall specify the list of properties of rendered
            instance. If True, the result of function must be a pair: ``(props,
            inst)``. Where props is the same value as can be passed to
            ``PROPERTIES`` property. Defaults to ``False``.
        * ``PROPERTIES`` - May contain list of instance properties, that will
            be produced in the same order as output. Each item of list can be
            either:

            * name - Name of property to render.
            * pair - A tuple ``(Name, render_func)``, where former item an
              arbitraty name for rendered value and the latter is a function
              taking as the only argument particular instance and returning
              value to render.

    ``DYNAMIC_PROPERTIES`` and ``PROPERTIES`` are mutually exclusive. If none
    is given, all instance properties will be printed.
    """
    __metaclass__ = meta.ShowInstanceMetaClass

    @classmethod
    def default_formatter(cls):
        return formatter.SingleFormatter

    @abc.abstractmethod
    def render(self, result):
        """
        This method can either be overriden in a subclass or left alone. In the
        latter case it will be generated by``ShowInstanceMetaClass`` metaclass
        with regard to ``PROPERTIES`` and ``DYNAMIC_PROPERTIES``.

        :param result: (``LMIInstance`` or ``tuple``) Either an instance to
            render or pair of properties and instance.
        :rtype: (``list``) List of pairs, where the first item is a label and
            second a value to render.
        """
        raise NotImplementedError(
                "render method must be overriden in subclass")

    def take_action(self, connection, args, kwargs):
        """
        Process single connection to a host, render result and return a value
        to render.

        :rtype: (``list``) List of pairs, where the first item is a label and
            second a value to render.
        """
        res = self.execute(connection, *args, **kwargs)
        return self.render(res)

    def process_session(self, session, args, kwargs):
        failures = []
        for connection in session:
            if len(session) > 1:
                self.app.stdout.write("="*79 + "\n")
                self.app.stdout.write("Host: %s\n" % connection.hostname)
                self.app.stdout.write("="*79 + "\n")
            try:
                self.produce_output(self.take_action(connection, args, kwargs))
            except Exception as exc:
                if self.app.options.debug:
                    LOG().exception('show instance failed for host "%s"',
                            connection.hostname)
                else:
                    LOG().error('show instance failed for host "%s": %s',
                            connection.hostname, exc)
                failures.append((connection.hostname, exc))
            if len(session) > 1:
                self.app.stdout.write("\n")
        if len(failures) > 0:
            self.app.stdout.write('There were %d unsuccessful runs on hosts:\n'
                    % len(failures))
            fmt = formatter.CsvFormatter(self.app.stdout)
            fmt.produce_output((('Host', 'Error'), failures))
        return 0

class LmiCheckResult(LmiSessionCommand):
    """
    Run an associated action and check its result. It implicitly makes no
    output if the invocation is successful and expected result matches.

    List of additional recognized properties:

        * ``EXPECT`` - A value, that is expected to be returned by invoked
            associated function. This can also be a callable taking two
            arguments:

                1. options - Dictionary with parsed command line options
                   returned by ``docopt``.
                2. result - Return value of associated function.
    """
    __metaclass__ = meta.CheckResultMetaClass

    def __init__(self, *args, **kwargs):
        LmiSessionCommand.__init__(self, *args, **kwargs)
        # dictionary of hosts with associated results
        self.results = {}

    @classmethod
    def default_formatter(cls):
        return formatter.CsvFormatter

    @abc.abstractmethod
    def check_result(self, options, result):
        """
        Check the returned value of associated function.

        :param options: (``dict``) Dictionary as returned by ``docopt`` parser.
        :param result: Any return value that will be compared against what is
            expected.
        :rtype: (``bool``) Whether the result is expected value or not.
        """
        raise NotImplementedError("check_result must be overriden in subclass")

    def take_action(self, connection, args, kwargs):
        """
        Invoke associated method and check its return value for single host.

        :param args: (``list``) List of arguments to pass to the associated
            function.
        :param kwargs: (``dict``) Keyword arguments to pass to the associated
            function.
        :rtype: (``tuple``) A pair of ``(passed, error)``, where `error`` is an
            instance of exception if any occured.
        """
        try:
            res = self.execute(connection, *args, **kwargs)
            self.results[connection.hostname] = res
            return (self.check_result(args, res), None)
        except Exception as exc:
            if self.app.config.trace:
                LOG().exception("failed to execute wrapped function")
            else:
                LOG().warn("failed to execute wrapped function: %s", exc)
            return (False, exc)

    def process_session(self, session, args, kwargs):
        # first list contain passed hosts, the second one failed ones
        results = ([], [])
        for connection in session:
            passed, error = self.take_action(connection, args, kwargs)
            results[0 if passed else 1].append((connection.hostname, error))
            if not passed and error:
                LOG().warn('invocation failed on host "%s": %s',
                        connection.hostname, error)
                if self.app.config.verbosity >= Configuration.OUTPUT_DEBUG:
                    self.app.stdout.write('invocation failed on host "%s":'
                            ' %s\n"' % (connection.hostname, str(error)))
        if self.app.config.verbosity >= Configuration.OUTPUT_INFO:
            self.app.stdout.write('Successful runs: %d\n' % len(results[0]))
        failed_runs = len(results[1]) + len(session.get_unconnected())
        if failed_runs:
            self.app.stdout.write('There were %d unsuccessful runs on hosts:\n'
                    % failed_runs)
            data = []
            for hostname in session.get_unconnected():
                data.append((hostname, 'failed to connect'))
            for hostname, error in results[1]:
                if error is None:
                    error = "failed"
                    if (self.app.config.verbosity >= Configuration.OUTPUT_INFO
                       and hasattr(self.check_result, 'expected')):
                        error = error + (" (%s != %s)" % (
                            self.check_result.expected,
                            self.results[hostname]))
                data.append((hostname, error))
            self.produce_output((('Name', 'Error'), data))
