"""Imported by every interpreter the suite starts, after the last .pth has run.

Nothing but the pin — jstack_pin.py carries the why. A test that needs a
sitecustomize of its own (scheduler-bare.sh and schedule-self.sh each install
one to block dateutil) shadows this file, since only the first sitecustomize
on the path is imported; those tests import jstack_pin from their own shim and
re-assert the pin afterwards.
"""

import jstack_pin  # noqa: F401  — the import IS the effect
