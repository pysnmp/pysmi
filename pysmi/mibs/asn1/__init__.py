"""Base ASN.1 MIB sources, read by
:py:class:`~pysmi.reader.package.PackageReader`.

Every file here is named exactly as the MIB module it holds, with no
extension -- the same convention https://pysnmp.github.io/mibs/asn1/ uses. That
mirror is not where these come from: for the modules bundled here pysmi is the
source of truth, each one fetched from the body that publishes it, and the
mirror follows. ``--check-mirror`` is what says whether it still does.

Membership is decided by ``scripts/bundled_mibs.json``, which pins each module
to the publisher its text is fetched from. A module still being revised
upstream is fine: ``scripts/update_bundled_mibs.py --check`` re-fetches
everything on a schedule, so a revision is reported rather than sat on, and a
caller supplying a properly dated newer copy wins on the MODULE-IDENTITY
comparison. What disqualifies a module is having no publisher to re-fetch from.

The exception is a module with no MODULE-IDENTITY. Nothing can outrank the copy
here on revision, so those must be text an RFC froze. See
``docs/source/bundled-mibs.rst`` and pysnmp/pysmi#113.
"""
