"""Structured logging configuration.

NOTE on the package name: this directory is called `logging/` to match
the module layout in the architecture document. Because absolute imports
are the Python 3 default, `import logging` from anywhere outside this
package resolves to the stdlib — `taskorbit.logging` and the stdlib
`logging` coexist cleanly. Inside this package, use absolute imports:
`import logging` for the stdlib, and `from taskorbit.logging.setup
import ...` for the package helpers.
"""
