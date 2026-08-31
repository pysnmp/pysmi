# GitHub Copilot Instructions

## Priority Guidelines

When generating code for this repository:

1. **Version Compatibility**: Always detect and respect the exact versions of languages, frameworks, and libraries used in this project
2. **Context Files**: Prioritize patterns and standards defined in the `.github/copilot` directory
3. **Codebase Patterns**: When context files don't provide specific guidance, scan the codebase for established patterns
4. **Architectural Consistency**: Maintain the layered, composite architecture and established module boundaries
5. **Code Quality**: Prioritize maintainability, performance, security, and testability in all generated code

## Technology Version Detection

Before generating code, scan the codebase to identify:

1. **Language Versions**: Detect the exact versions of programming languages in use
   - Examine `pyproject.toml` for the Python version constraint: `python = "^3.8"`
   - The project targets Python 3.8+; never use language features beyond Python 3.8
   - Note: legacy Python 2 compatibility shims exist in `pysmi/compat.py` and `try/except ImportError` blocks, but new code should target Python 3.8+ only

2. **Framework Versions**: Identify the exact versions of all frameworks
   - Build system: Poetry (`poetry-core>=1.0.0`), declared in `pyproject.toml` `[build-system]`
   - Parser tooling: `ply = "^3.11"` (PLY — Python Lex-Yacc), used by `pysmi/lexer/smi.py` and `pysmi/parser/smi.py`
   - HTTP client: `requests = "^2.31.0"`, used by `pysmi/reader/httpclient.py`
   - Respect version constraints when generating code; never suggest features not available in the detected versions

3. **Library Versions**: Note the exact versions of key libraries and dependencies
   - Runtime dependencies: `ply ^3.11`, `requests ^2.31.0`
   - Dev dependencies: `Sphinx ^4.3.0`, `pysnmp ^4.4.12`, `pytest ^7.2.0`, `pytest-cov ^3.0.0`, `black ^24.3.0`, `isort ^5.10.1`
   - Tests import `pysnmp` (`from pysnmp.smi.builder import MibBuilder`) and `pyasn1` (`from pyasn1.compat.octets import str2octs`)
   - Generate code compatible with these specific versions

## Context Files

Prioritize the following files in `.github/copilot` directory (if they exist):

- **architecture.md**: System architecture guidelines
- **tech-stack.md**: Technology versions and framework details
- **coding-standards.md**: Code style and formatting standards
- **folder-structure.md**: Project organization guidelines
- **exemplars.md**: Exemplary code patterns to follow

## Codebase Scanning Instructions

When context files don't provide specific guidance:

1. Identify similar files to the one being modified or created
2. Analyze patterns for:
   - Naming conventions
   - Code organization
   - Error handling
   - Logging approaches
   - Documentation style
   - Testing patterns

3. Follow the most consistent patterns found in the codebase
4. When conflicting patterns exist, prioritize patterns in newer files or files with higher test coverage
5. Never introduce patterns not found in the existing codebase

## Architecture Overview

PySMI is a pure-Python SNMP SMI MIB parser organized as a **composite, layered library** with pluggable components. The top-level `MibCompiler` (`pysmi/compiler.py`) orchestrates specialized, swappable components:

- **readers** (`pysmi/reader/`) — acquire ASN.1 MIB data from local files, ZIP archives, HTTP/HTTPS, FTP, callbacks
- **searchers** (`pysmi/searcher/`) — determine whether an already-transformed MIB exists and is current
- **parser** (`pysmi/parser/`) — parse ASN.1 MIB into an AST (SMIv1, SMIv2, SMIv1-compat dialects)
- **lexer** (`pysmi/lexer/`) — PLY-based tokenizer for SMI syntax
- **codegen** (`pysmi/codegen/`) — transform AST into pysnmp Python modules, JSON documents, or null output
- **borrower** (`pysmi/borrower/`) — fetch pre-transformed MIBs when transformation fails
- **writer** (`pysmi/writer/`) — store transformed MIB data as Python files, plain files, or via callback
- **scripts** (`pysmi/scripts/`) — CLI entry points `mibdump` and `mibcopy`

Each component family follows the **Abstract Base Class + concrete implementations** pattern:

- `pysmi/parser/base.py` → `AbstractParser` with `reset()` and `parse(data, **kwargs)` raising `NotImplementedError()`
- `pysmi/reader/base.py` → `AbstractReader` with `getData(filename, **options)` raising `NotImplementedError()`
- `pysmi/searcher/base.py` → `AbstractSearcher` with `fileExists(mibname, mtime, rebuild=False)` raising `NotImplementedError()`
- `pysmi/writer/base.py` → `AbstractWriter` with `putData(mibname, data, comments=(), dryRun=False)` and `getData(filename)` raising `NotImplementedError()`
- `pysmi/codegen/base.py` → `AbstractCodeGen` with shared `baseMibs`, `commonSyms`, `constImports` tables
- `pysmi/borrower/base.py` → `AbstractBorrower` wrapping a reader

When adding a new reader/searcher/writer/codegen/borrower, subclass the corresponding abstract base, implement the required methods, and register it via the package `__init__.py` `__all__` / re-exports.

## Code Quality Standards

### Maintainability
- Write self-documenting code with clear naming
- Follow the naming and organization conventions evident in the codebase
- Follow established patterns for consistency
- Keep functions focused on single responsibilities
- Limit function complexity and length to match existing patterns

### Performance
- Follow existing patterns for memory and resource management
- Match existing patterns for handling computationally expensive operations
- Follow established patterns for asynchronous operations
- Apply caching consistently with existing patterns
- Optimize according to patterns evident in the codebase

### Security
- Follow existing patterns for input validation
- Apply the same sanitization techniques used in the codebase
- Use parameterized queries matching existing patterns
- Follow established authentication and authorization patterns
- Handle sensitive data according to existing patterns

### Testability
- Follow established patterns for testable code
- Match dependency injection approaches used in the codebase
- Apply the same patterns for managing dependencies
- Follow established mocking and test double patterns
- Match the testing style used in existing tests

## Documentation Requirements

- Follow the exact documentation format found in the codebase
- Match the docstring style and completeness of existing comments
- Document parameters, returns, and exceptions in the same style
- Follow existing patterns for usage examples
- Match class-level documentation style and content

### Observed documentation patterns

- **File header**: every `.py` file begins with the standard block:
  ```python
  #
  # This file is part of pysmi software.
  #
  # Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
  # License: http://snmplabs.com/pysmi/license.html
  #
  ```
  New files must include this header verbatim.
- **Class docstrings**: triple-quoted `"""..."""` describing the class purpose and noting that instances are passed to `MibCompiler`. Example from `pysmi/codegen/pysnmp.py`:
  ```python
  class PySnmpCodeGen(AbstractCodeGen):
      """Builds PySnMP-specific Python code representing MIB module supplied
         in form of an Abstract Syntax Tree on input.

         Instance of this class is supposed to be passed to *MibCompiler*,
         the rest is internal to *MibCompiler*.
      """
  ```
- **Method docstrings**: Google-style with `Args:`, `Keyword Args:`, `Returns:` sections. Example from `pysmi/compiler.py`:
  ```python
  def addSources(self, *sources):
      """Add more ASN.1 MIB source repositories.
      ...
         Args:
             sources: reader object(s)

         Returns:
             reference to itself (can be used for call chaining)
      """
  ```
- **Inline comments**: use `#` for explanatory comments; `# XXX` marks known-uncertain areas, `# TODO` / `# TODO(etingof):` marks planned work, `# hack` marks SMIv1 workarounds. Preserve these markers when editing.

## Testing Approach

### Unit Testing
- Match the exact structure and style of existing unit tests
- Follow the same naming conventions for test classes and methods
- Use the same assertion patterns found in existing tests
- Apply the same mocking approach used in the codebase
- Follow existing patterns for test isolation

### Observed testing patterns

- **Framework**: `unittest` (stdlib), with a fallback to `unittest2`:
  ```python
  try:
      import unittest2 as unittest
  except ImportError:
      import unittest
  ```
- **Test runner**: `tests/__main__.py` loads a named suite via `unittest.TestLoader().loadTestsFromNames([...])` and runs with `unittest.TextTestRunner(verbosity=2)`.
- **Test file naming**: `test_<feature>_<smiversion>_<target>.py`, e.g. `test_objecttype_smiv2_pysnmp.py`, `test_typedeclaration_smiv1_pysnmp.py`, `test_zipreader.py`.
- **Test class naming**: `<Feature>TestCase`, e.g. `ObjectTypeBasicTestCase`, `ZipReaderTestCase`.
- **MIB-as-docstring fixture**: each test class stores a full ASN.1 MIB module in the class `__doc__` string, then `setUp` parses it:
  ```python
  class ObjectTypeBasicTestCase(unittest.TestCase):
      """
  TEST-MIB DEFINITIONS ::= BEGIN
  ...
  END
  """
      def setUp(self):
          ast = parserFactory()().parse(self.__class__.__doc__)[0]
          mibInfo, symtable = SymtableCodeGen().genCode(ast, {}, genTexts=True)
          self.mibInfo, pycode = PySnmpCodeGen().genCode(ast, {mibInfo.name: symtable}, genTexts=True)
          codeobj = compile(pycode, 'test', 'exec')
          mibBuilder = MibBuilder()
          mibBuilder.loadTexts = True
          self.ctx = {'mibBuilder': mibBuilder}
          exec(codeobj, self.ctx, self.ctx)
  ```
- **Assertions**: `self.assertTrue(..., 'message')`, `self.assertEqual(actual, expected, 'message')` — always include a trailing failure-message string.
- **Test method naming**: `test<Feature><Aspect>`, e.g. `testObjectTypeName`, `testObjectTypeDescription`, `testObjectTypeSyntax`.
- New tests must follow this exact fixture style and naming.

## Technology-Specific Guidelines

### Python Guidelines
- Detect and adhere to the specific Python version in use (`^3.8` per `pyproject.toml`)
- Follow the same import organization found in existing modules
- Match type hinting approaches if used in the codebase
- Apply the same error handling patterns found in existing code
- Follow the same module organization patterns

### Observed Python conventions

- **Imports**: stdlib first, then third-party, then `pysmi` internal. Internal imports use the package-relative form `from pysmi import error`, `from pysmi import debug`, `from pysmi.<subpkg> import <Class>`. Example from `pysmi/reader/httpclient.py`:
  ```python
  import socket
  import sys
  import time
  from requests import session
  from pysmi.reader.base import AbstractReader
  from pysmi.mibinfo import MibInfo
  from pysmi.compat import decode
  from pysmi import __version__ as pysmi_version
  from pysmi import error
  from pysmi import debug
  ```
- **Type hints**: not used in the codebase. Do not add type annotations unless modifying a file that already uses them.
- **String formatting**: mixed styles coexist. Newer code uses f-strings (`f'{self.__class__.__name__}{{"{self._path}"}}'`); older code uses `%` formatting (`'looking for MIB %s' % mibname`) and `.format()`. Match the surrounding file's style; prefer f-strings for new code.
- **`__str__` repr pattern**: concrete classes implement `__str__` returning `f'{self.__class__.__name__}{{"{self._path}"}}'` (or equivalent). Follow this for new reader/searcher/writer/borrower classes.
- **Options pattern**: `setOptions(self, **kwargs)` iterates `for k in kwargs: setattr(self, k, kwargs[k])` and returns `self`. Follow this for configurable components.
- **`**kwargs` forwarding**: methods accept `**options` and forward to inner objects (e.g. `AbstractBorrower.getData` forwards `options` to `self._reader.getData`).
- **Python 2/3 compat shims**: `pysmi/compat.py` provides `encode`/`decode` helpers; `try/except ImportError` blocks guard `importlib` vs `imp`, `json` vs `simplejson`, `collections.OrderedDict` vs `ordereddict`. New code may assume Python 3.8+ but must not break these shims when editing existing files.

### Error handling pattern

- All package exceptions derive from `PySmiError(Exception)` in `pysmi/error.py`. The base constructor stores `args[0]` as `self.msg` and sets every kwarg as an attribute:
  ```python
  class PySmiError(Exception):
      def __init__(self, *args, **kwargs):
          Exception.__init__(self, *args)
          self.msg = args and args[0] or ''
          for k in kwargs:
              setattr(self, k, kwargs[k])
  ```
- Specialized exceptions form a hierarchy: `PySmiLexerError` → `PySmiParserError` → `PySmiSyntaxError`; `PySmiSearcherError` → `PySmiFileNotModifiedError` / `PySmiFileNotFoundError`; `PySmiReaderError` → `PySmiReaderFileNotModifiedError` / `PySmiReaderFileNotFoundError`; `PySmiCodegenError` → `PySmiSemanticError`; `PySmiWriterError`.
- Raise the most specific exception class, passing context as kwargs:
  ```python
  raise error.PySmiReaderFileNotFoundError(mibname=mibname, reader=self._reader)
  raise error.PySmiWriterError(f'failure writing file {pyfile}: {exc[1]}', file=pyfile, writer=self)
  ```
- Use `sys.exc_info()[1]` when interpolating the current exception message into a new error (the codebase's established pattern).
- `try/except` blocks commonly catch `(OSError, UnicodeEncodeError)` for file I/O and broad `Exception` for optional-import shims.

### Logging / debug pattern

- `pysmi/debug.py` defines a flag-based debug system, not stdlib `logging` directly. Module-level singleton `debug.logger` is a `Debug` instance; flags live in `pysmi/debug.py` (`flagReader`, `flagLexer`, `flagParser`, `flagGrammar`, `flagCodegen`, `flagWriter`, `flagCompiler`, `flagBorrower`, `flagSearcher`, `flagAll`).
- Emit debug lines using the bitwise-and short-circuit form (do not use `if` statements):
  ```python
  debug.logger & debug.flagReader and debug.logger(f'looking for MIB {mibname}')
  ```
- For components that need the underlying stdlib logger (e.g. PLY), call `debug.logger.getCurrentLogger()`.
- New components must follow this exact debug-logging idiom.

### Code generation patterns

- `pysmi/codegen/base.py` (`AbstractCodeGen`) holds shared `baseMibs`, `commonSyms` (SMIv1→SMIv2 mapping), and `constImports` tables. Both `PySnmpCodeGen` and `JsonCodeGen` and `SymtableCodeGen` subclass it and reuse these tables.
- `transOpers(symbol)` replaces `-` with `_` (and prefixes `pysmi_` for Python keywords) to turn SMI identifiers into valid Python symbols.
- `prepData` walks the AST tuple tree dispatching through `handlersTable`; `genCode(ast, symbolTable, **kwargs)` is the entry point returning `(MibInfo, output)`.
- `baseMibs` lists MIBs never compiled (MACRO-defining / conflicting OIDs): `RFC1065-SMI`, `RFC1155-SMI`, `RFC1158-MIB`, `RFC-1212`, `RFC1213-MIB`, `RFC-1215`, `SNMPv2-SMI`, `SNMPv2-TC`, `SNMPv2-TM`, `SNMPv2-CONF`.
- New code generators must subclass `AbstractCodeGen`, implement `genCode`, and register in `pysmi/codegen/__init__.py`.

### CLI scripts pattern

- `pysmi/scripts/mibdump.py` and `pysmi/scripts/mibcopy.py` expose `start()` functions registered as console scripts in `pyproject.toml` (`[tool.poetry.scripts]`).
- They use `getopt` (not `argparse`) for option parsing and follow `sysexits.h` exit codes (`EX_OK=0`, `EX_USAGE=64`, `EX_SOFTWARE=70`, `EX_MIB_MISSING=79`).
- Help text is a multi-line string built with `.format(...)`. Errors print to `sys.stderr` with the help message and exit with the appropriate code.
- New CLI scripts must follow this `getopt` + `sysexits.h` pattern and be registered in `pyproject.toml`.

## Version Control Guidelines

- Follow Semantic Versioning patterns as applied in the codebase
- Match existing patterns for documenting breaking changes
- Follow the same approach for deprecation notices

### Observed versioning pattern

- Version is `1.1.12` (Semantic Versioning), declared in both `pyproject.toml` (`version = "1.1.12"`) and `pysmi/__init__.py` (`__version__ = "1.1.12"`). Keep these two in sync.
- `CHANGES.rst` uses the reStructuredText format with `Revision <version>, <date>` headers and bullet entries. Match this format for changelog entries.

## General Best Practices

- Follow naming conventions exactly as they appear in existing code
- Match code organization patterns from similar files
- Apply error handling consistent with existing patterns
- Follow the same approach to testing as seen in the codebase
- Match logging patterns from existing code
- Use the same approach to configuration as seen in the codebase

## Project-Specific Guidance

- Scan the codebase thoroughly before generating any code
- Respect existing architectural boundaries without exception
- Match the style and patterns of surrounding code
- When in doubt, prioritize consistency with existing code over external best practices
- Preserve the standard file header, the `pysmi` debug-logging idiom, the `PySmiError` hierarchy, and the abstract-base-class component pattern
- New components must be registered in the relevant `__init__.py` (`pysmi/reader/__init__.py`, `pysmi/searcher/__init__.py`, `pysmi/writer/__init__.py`, `pysmi/codegen/__init__.py`, `pysmi/borrower/__init__.py`)
- Linting: `.flake8.ini` ignores `E123,E125,D104,D100,D101,D102,D103,D106,D107,D412,W504` and sets `builtins = _`; respect these when adding code
- Formatting: `black ^24.3.0` and `isort ^5.10.1` are declared as dev dependencies (pre-commit hooks are currently commented out in `.pre-commit-config.yaml`); prefer black-compatible formatting