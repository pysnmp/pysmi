#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""A browsable rendering of a corpus, written by the build that produced it.

``--emit=site`` is a corpus artifact like the indexes and the database: a
projection of the same jsondoc tree, written by the same build, over whatever
modules the manifest declared. An enterprise pointing ``mibcorpus`` at its own
private collection gets the same site over its own modules.

The alternative -- a generator living in the repository that publishes the
corpus -- is the shape pysnmp/mibs#365 removed: that repository's compiler,
dependency resolver and OID indexer were each a second implementation of
PySMI's, and each had drifted.

See :doc:`/mibcorpus` for the artifact and pysnmp/pysmi#276 for the reasoning.
"""

from pysmi.corpus.site.build import (
    SCHEMA_VERSION,
    STYLESHEET,
    PageSizes,
    SiteReport,
    build_site,
)
from pysmi.corpus.site.model import (
    ArcPage,
    Definition,
    EntityPage,
    ModulePage,
    arc_pages,
    entity_page,
    imported_by,
    module_page,
)
from pysmi.corpus.site.theme import PAGE, PLACEHOLDERS, Theme, load_theme

__all__ = [
    "PAGE",
    "PLACEHOLDERS",
    "SCHEMA_VERSION",
    "STYLESHEET",
    "ArcPage",
    "Definition",
    "EntityPage",
    "ModulePage",
    "PageSizes",
    "SiteReport",
    "Theme",
    "arc_pages",
    "build_site",
    "entity_page",
    "imported_by",
    "load_theme",
    "module_page",
]
