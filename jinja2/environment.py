# -*- coding: utf-8 -*-
"""
    jinja2.environment
    ~~~~~~~~~~~~~~~~~~

    Provides a class that holds runtime and parsing time options.

    :copyright: 2007 by Armin Ronacher.
    :license: BSD, see LICENSE for more details.
"""
from jinja2.lexer import Lexer
from jinja2.parser import Parser
from jinja2.optimizer import optimize
from jinja2.compiler import generate
from jinja2.runtime import Undefined
from jinja2.defaults import DEFAULT_FILTERS, DEFAULT_TESTS, DEFAULT_NAMESPACE


class Environment(object):
    """The Jinja environment.

    The core component of Jinja is the `Environment`. It contains
    important shared variables like configuration, filters, tests,
    globals and others.
    """

    #: if this environment is sandboxed.  Modifying this variable won't make
    #: the environment sandboxed though.  For a real sandboxed environment
    #: have a look at jinja2.sandbox
    sandboxed = False

    def __init__(self,
                 block_start_string='{%',
                 block_end_string='%}',
                 variable_start_string='{{',
                 variable_end_string='}}',
                 comment_start_string='{#',
                 comment_end_string='#}',
                 line_statement_prefix=None,
                 trim_blocks=False,
                 optimized=True,
                 undefined=Undefined,
                 loader=None):
        """Here the possible initialization parameters:

        ========================= ============================================
        `block_start_string`      the string marking the begin of a block.
                                  this defaults to ``'{%'``.
        `block_end_string`        the string marking the end of a block.
                                  defaults to ``'%}'``.
        `variable_start_string`   the string marking the begin of a print
                                  statement. defaults to ``'{{'``.
        `comment_start_string`    the string marking the begin of a
                                  comment. defaults to ``'{#'``.
        `comment_end_string`      the string marking the end of a comment.
                                  defaults to ``'#}'``.
        `line_statement_prefix`   If given and a string, this will be used as
                                  prefix for line based statements.  See the
                                  documentation for more details.
        `trim_blocks`             If this is set to ``True`` the first newline
                                  after a block is removed (block, not
                                  variable tag!). Defaults to ``False``.
        `optimized`               should the optimizer be enabled?  Default is
                                  ``True``.
        `undefined`               a subclass of `Undefined` that is used to
                                  represent undefined variables.
        `loader`                  the loader which should be used.
        ========================= ============================================
        """
        assert issubclass(undefined, Undefined), 'undefined must be ' \
               'a subclass of undefined because filters depend on it.'

        # lexer / parser information
        self.block_start_string = block_start_string
        self.block_end_string = block_end_string
        self.variable_start_string = variable_start_string
        self.variable_end_string = variable_end_string
        self.comment_start_string = comment_start_string
        self.comment_end_string = comment_end_string
        self.line_statement_prefix = line_statement_prefix
        self.trim_blocks = trim_blocks
        self.undefined = undefined
        self.optimized = optimized

        # defaults
        self.filters = DEFAULT_FILTERS.copy()
        self.tests = DEFAULT_TESTS.copy()
        self.globals = DEFAULT_NAMESPACE.copy()

        # if no finalize function/method exists we default to unicode.  The
        # compiler check if the finalize attribute *is* unicode, if yes no
        # finalizaion is written where it can be avoided.
        if not hasattr(self, 'finalize'):
            self.finalize = unicode

        # set the loader provided
        self.loader = loader

        # create lexer
        self.lexer = Lexer(self)

    def subscribe(self, obj, argument):
        """Get an item or attribute of an object."""
        try:
            return getattr(obj, str(argument))
        except (AttributeError, UnicodeError):
            try:
                return obj[argument]
            except (TypeError, LookupError):
                return self.undefined(obj, argument)

    def parse(self, source, filename=None):
        """Parse the sourcecode and return the abstract syntax tree. This tree
        of nodes is used by the compiler to convert the template into
        executable source- or bytecode.
        """
        parser = Parser(self, source, filename)
        return parser.parse()

    def lex(self, source, filename=None):
        """Lex the given sourcecode and return a generator that yields tokens.
        The stream returned is not usable for Jinja but can be used if
        Jinja templates should be processed by other tools (for example
        syntax highlighting etc)

        The tuples are returned in the form ``(lineno, token, value)``.
        """
        return self.lexer.tokeniter(source, filename)

    def compile(self, source, filename=None, raw=False, globals=None):
        """Compile a node or source."""
        if isinstance(source, basestring):
            source = self.parse(source, filename)
        if self.optimized:
            node = optimize(source, self, globals or {})
        source = generate(node, self, filename)
        if raw:
            return source
        if isinstance(filename, unicode):
            filename = filename.encode('utf-8')
        return compile(source, filename, 'exec')

    def join_path(self, template, parent):
        """Join a template with the parent.  By default all the lookups are
        relative to the loader root, but if the paths should be relative this
        function can be used to calculate the real filename."""
        return template

    def get_template(self, name, parent=None, globals=None):
        """Load a template."""
        if self.loader is None:
            raise TypeError('no loader for this environment specified')
        if parent is not None:
            name = self.join_path(name, parent)
        globals = self.make_globals(globals)
        return self.loader.load(self, name, globals)

    def from_string(self, source, filename='<string>', globals=None):
        """Load a template from a string."""
        globals = self.make_globals(globals)
        return Template(self, self.compile(source, filename), globals)

    def make_globals(self, d):
        """Return a dict for the globals."""
        if d is None:
            return self.globals
        return dict(self.globals, **d)


class Template(object):
    """Represents a template."""

    def __init__(self, environment, code, globals):
        namespace = {'environment': environment}
        exec code in namespace
        self.environment = environment
        self.name = namespace['filename']
        self.root_render_func = namespace['root']
        self.blocks = namespace['blocks']
        self.globals = globals

    def render(self, *args, **kwargs):
        return u''.join(self.generate(*args, **kwargs))

    def stream(self, *args, **kwargs):
        return TemplateStream(self.generate(*args, **kwargs))

    def generate(self, *args, **kwargs):
        # assemble the context
        local_context = dict(*args, **kwargs)
        context = self.globals.copy()
        context.update(local_context)

        # if the environment is using the optimizer locals may never
        # override globals as optimizations might have happened
        # depending on values of certain globals.  This assertion goes
        # away if the python interpreter is started with -O
        if __debug__ and self.environment.optimized:
            overrides = set(local_context) & set(self.globals)
            if overrides:
                plural = len(overrides) != 1 and 's' or ''
                raise AssertionError('the per template variable%s %s '
                                     'override%s global variable%s. '
                                     'With an enabled optimizer this '
                                     'will lead to unexpected results.' %
                    (plural, ', '.join(overrides), plural or ' a', plural))
        gen = self.root_render_func(context)
        # skip the first item which is a reference to the stream
        gen.next()
        return gen

    def __repr__(self):
        return '<%s %r>' % (
            self.__class__.__name__,
            self.name
        )


class TemplateStream(object):
    """Wraps a genererator for outputing template streams."""

    def __init__(self, gen):
        self._gen = gen
        self._next = gen.next
        self.buffered = False

    def disable_buffering(self):
        """Disable the output buffering."""
        self._next = self._gen.next
        self.buffered = False

    def enable_buffering(self, size=5):
        """Enable buffering. Buffer `size` items before yielding them."""
        if size <= 1:
            raise ValueError('buffer size too small')
        self.buffered = True

        def buffering_next():
            buf = []
            c_size = 0
            push = buf.append
            next = self._gen.next

            try:
                while 1:
                    item = next()
                    if item:
                        push(item)
                        c_size += 1
                    if c_size >= size:
                        raise StopIteration()
            except StopIteration:
                if not c_size:
                    raise
            return u''.join(buf)

        self._next = buffering_next

    def __iter__(self):
        return self

    def next(self):
        return self._next()