"""jRemote host API — the remote surface for the JStack system.

A self-contained, token-authed, versioned API (`/api/jremote/v1/*`) that lets
the jRemote iOS app list and drive Claude Code agent sessions on this Mac.

Mounted into the dashboard FastAPI process for now; isolated here so it can be
lifted into its own service as jRemote grows. The app contract is independent
of the dashboard's cookie auth — jRemote uses its own bearer token.
"""
