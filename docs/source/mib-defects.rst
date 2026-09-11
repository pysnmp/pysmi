.. _mib-defects:

Defects a patch repairs
=======================

.. toctree::
   :maxdepth: 2

A published MIB that does not compile is repaired by a diff against its text.
The diff carries the correction; it does not name the defect, and the defect is
what decides whether the repair should still exist -- a repair to text the
publisher has since fixed should go, and a local preference dressed as a repair
should never have been written.

So every patch names the defect it repairs, by an identifier from this page:

.. code-block:: diff

    Defect: SMI-UNPUBLISHED-MODULE https://pysnmp.github.io/pysmi/stable/mib-defects.html#smi-unpublished-module

    --- a/SMUX-MIB
    +++ b/SMUX-MIB
    @@ -4,7 +4,7 @@

One ``Defect:`` line per defect, and a patch may repair more than one.
:ref:`mibpatch` describes the format and how ``mibpatch`` writes it;
:ref:`bundled-mib-patches` lists PySMI's own twelve repairs and what each
module's text actually says.

These identifiers name defects against the SMI itself -- :rfc:`2578`,
:rfc:`2579` and :rfc:`2580` -- rather than against any particular collection of
MIBs, so they are as useful over a vendor tree as over this one. A downstream
corpus with repairs of its own defines its own identifiers and its own page;
:py:func:`pysmi.patches.split_patch` reads those exactly the same way.

Reading them back from Python:

.. code-block:: python

   from pysmi.patches import PatchSet

   patches = PatchSet.from_directory("./mib-patches")

   for defect in patches.defects_for("SMUX-MIB"):
       print(defect.id, defect.url)

The catalogue
-------------

.. _smi-missing-import:

``SMI-MISSING-IMPORT``
^^^^^^^^^^^^^^^^^^^^^^

*uses a symbol without naming it in IMPORTS* -- RFC 2578 section 3.2.

Every symbol a module uses that it did not define itself has to be named in its
``IMPORTS`` clause. A module that uses ``TruthValue`` or ``Unsigned32`` without
importing it does not compile under a compiler that will not supply the import
for it -- PySMI's own ``mibdump --strict-imports``, and other SMI tools by
default.

This is the one defect a repair can be *derived* for, and ``mibpatch`` does:
where the omitted symbol is undefined, unimported, and exported by exactly one
base module, the import that was meant is not in doubt. See :ref:`mibpatch`.

The repair adds the symbol to the existing ``FROM`` group for the module that
exports it, or opens a new group at the end of the clause.

.. _smi-unpublished-module:

``SMI-UNPUBLISHED-MODULE``
^^^^^^^^^^^^^^^^^^^^^^^^^^

*imports FROM a module name no publisher ships* -- RFC 2578 section 3.2.

An ``IMPORTS`` clause names the module a symbol comes from, and the name has to
be one something publishes. Several RFC-published MIBs name modules that nobody
ever shipped: ``RFC-1213`` for what is published as ``RFC1213-MIB``,
``RFC-1155`` for ``RFC1155-SMI``, ``RFC1212`` for the macro module PySMI
maintains as ``RFC-1212``. Usually the same clause spells its other imports
correctly, which is what makes these typographical rather than a naming
convention that moved.

The repair is the published spelling. It cannot be left to a search path: a
compiler looking for ``RFC-1213`` has nothing to find.

.. _smi-unexported-import:

``SMI-UNEXPORTED-IMPORT``
^^^^^^^^^^^^^^^^^^^^^^^^^

*imports a symbol the named module does not export* -- RFC 2578 section 3.2.

The ``IMPORTS`` clause names a module that exists and a symbol that exists, and
the named module does not define the symbol. Unlike
:ref:`smi-unpublished-module` the module name resolves, so a search path finds
something; what it finds does not answer for the symbol.

The usual cause is an export withdrawn under a module that was not withdrawn
with it. ``CISCO-TC`` defined an ``Unsigned32`` textual convention in 1996 and
removed it in 2004 -- correctly, since :rfc:`2578` had made ``Unsigned32`` a
base type of ``SNMPv2-SMI`` in the meantime -- and its own revision history
says both. A module importing it ``FROM CISCO-TC`` and never revised since
names an export that was real when it was written.

The repair is the module that does export the symbol today. Where that is a
base module the clause already imports from, the symbol joins the existing
``FROM`` group and the stale one is dropped.

.. _smi-superseded-module:

``SMI-SUPERSEDED-MODULE``
^^^^^^^^^^^^^^^^^^^^^^^^^

*imports FROM a module that was renamed, under a name that now belongs to a different module* -- RFC 2578 section 3.2.

A module imports a symbol ``FROM`` a module that has since been renamed, and
the old name now belongs to a *different* module. This is worse than a name
that resolves to nothing, because it resolves -- to a module that does not
define the symbol.

:rfc:`1565` named the Network Services Monitoring MIB ``APPLICATION-MIB``.
:rfc:`2788` renamed it ``NETWORK-SERVICES-MIB``, and :rfc:`2564` then published
an unrelated Application Management MIB under the freed name. A module written
against :rfc:`1565` and read today finds the wrong one.

The repair is the module's current name, and any symbol renamed with it --
:rfc:`2788` also renamed ``applGroup`` to ``applRFC1565Group``. A
``MODULE-COMPLIANCE`` naming the same group is renamed alongside the
``IMPORTS``.

.. _smi-undefined-name:

``SMI-UNDEFINED-NAME``
^^^^^^^^^^^^^^^^^^^^^^

*references a descriptor the module does not define* -- RFC 2578 section 3.1.

A descriptor is referenced that the module does not define and does not import.
In practice this is a misspelling: a ``NOTIFICATION-GROUP`` declared as
``mipSecNotifcationsGroup`` where the ``MODULE-COMPLIANCE`` that names it spells
it ``mipSecNotificationsGroup``, or a ``MODULE-IDENTITY`` registered
``::= { mdmMIB 1 }`` in a module whose node is ``mdmMib``. SMI descriptors are
case-sensitive, so the second of those registers a node under itself.

The repair is the spelling the rest of the module uses. Where the two spellings
disagree and only one is defined, the defined one wins.

.. _smi-clause-out-of-order:

``SMI-CLAUSE-OUT-OF-ORDER``
^^^^^^^^^^^^^^^^^^^^^^^^^^^

*defines something before the module's MODULE-IDENTITY* -- RFC 2578 section 3.

A module's ``MODULE-IDENTITY`` invocation comes before anything else it
defines. A module that registers an ``OBJECT-IDENTITY`` above its
``MODULE-IDENTITY`` is not in the order the SMI gives.

The repair moves the misplaced definition below the ``MODULE-IDENTITY``. A
forward reference is not the problem -- the SMI allows one -- the order of the
invocation is.

.. _smi-invalid-date:

``SMI-INVALID-DATE``
^^^^^^^^^^^^^^^^^^^^

*gives a date in neither of the two forms the SMI allows* -- RFC 2578 section 2.

``LAST-UPDATED`` and ``REVISION`` take a UTC time in one of two forms:
``YYMMDDHHMMZ``, eleven characters, or ``YYYYMMDDHHMMZ``, thirteen. A value of
twelve digits and a ``Z`` is thirteen characters and so reads as the wide form,
which is how :rfc:`2238`'s ``"970514000000Z"`` becomes year 9705, month 14.

The repair writes the same date in the form the module plainly meant. It never
invents one: a date that cannot be read as either form and cannot be read as a
mistyping of one is a defect to report rather than to repair.

.. _smi-invalid-access:

``SMI-INVALID-ACCESS``
^^^^^^^^^^^^^^^^^^^^^^

*gives an access value the SMI does not define* -- RFC 2578 section 7.3, RFC 2580 section 4.1.

``MAX-ACCESS`` and a conformance ``MIN-ACCESS`` take one of a fixed set of
values. Text that carries something else -- a truncated ``read-wr`` where
``read-write`` was meant -- names no access at all.

Where the intended value is unambiguous, as it is when the correct line is
published immediately below the truncated one, the repair drops the defective
line. Where it is not, the module needs a human.

.. _smi-misdeclared-access:

``SMI-MISDECLARED-ACCESS``
^^^^^^^^^^^^^^^^^^^^^^^^^^

*gives an access the object's own use contradicts* -- RFC 2578 section 7.3.

The access is one the SMI defines, and it contradicts what the object is for.
``accessible-for-notify`` is for an object that is only ever sent in a
notification; giving it to an ordinary column that a manager reads makes the
object unreadable.

This is the one defect class here that is a judgement rather than a rule
violation, so it wants more care than the others: the repair is only right
where the module's own text says what the object is read for. Where it does
not, leave it alone -- a module doing something unusual is not the same as a
module doing something wrong.

.. _smi-range-outside-type:

``SMI-RANGE-OUTSIDE-TYPE``
^^^^^^^^^^^^^^^^^^^^^^^^^^

*bounds a value outside the type it is declared as* -- RFC 2578 section 7.1.1.

A range constrains the values a type may take, and cannot widen it.
``Integer32`` is ``-2147483648`` to ``2147483647``, so
``INTEGER (-1..2147483648)`` bounds a value one past the top of the type it is
declared as. :rfc:`1628` does this twice; RFC Errata 3276 records it.

The repair is the top of the type. An erratum saying so is what makes it a
repair rather than a reading.

.. _smi-display-hint-mismatch:

``SMI-DISPLAY-HINT-MISMATCH``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

*gives a DISPLAY-HINT format the SYNTAX does not allow* -- RFC 2579 section 3.1.

A ``DISPLAY-HINT`` format has to match the ``SYNTAX`` it is given for. An
integer takes ``d`` with an optional decimal point, ``x``, ``o`` or ``b``; an
octet string takes an octet count and a format character, as in ``2d`` or
``1x:``. An ``INTEGER`` with ``DISPLAY-HINT "2d"`` on it is asking for the
octet-string form, and an ``OCTET STRING`` with ``"d"`` on it for the integer
form.

The repair is the form the ``SYNTAX`` allows, or -- where the hint says nothing
the syntax can carry -- commenting the line out, which leaves the published text
visible in the module.

.. _smi-unmarked-comment:

``SMI-UNMARKED-COMMENT``
^^^^^^^^^^^^^^^^^^^^^^^^

*continues a comment onto a line that does not start one* -- RFC 2578 section 3.1.

A comment runs from ``--`` to the end of the line, and a comment that wraps
needs ``--`` on the next line too. A continuation published without it is read
as ASN.1, and a stray word in the middle of a ``SEQUENCE`` is a syntax error
some distance from anything that looks wrong.

The repair marks the continuation.
