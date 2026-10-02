"""The three processes that exist inside the guest, plus their shared view.

* :mod:`atlas.sandbox.guest.launcher` runs as root in the guest for just long
  enough to create a workspace, a cgroup, and a namespace, then reports one
  envelope. It enforces the wall clock.
* :mod:`atlas.sandbox.guest.worker` runs inside the confinement as an
  unprivileged user. It refuses to proceed if it is not who it was supposed to
  be, calls the tool body, and validates the result.
* :mod:`atlas.sandbox.guest.selftest` is the adversary. It runs inside the same
  confinement and tries every prohibited thing, so the security tests measure the
  real namespaces rather than a mock of them.
* :mod:`atlas.sandbox.guest.view` is the owner-scoped read view that replaces the
  database accessor, serving an authorized snapshot instead.

All four are installed into the guest by :mod:`atlas.sandbox.provision`, and the
package initializer here is a stub on the guest side precisely because the real
one re-exports the Windows-only supervisor.
"""
