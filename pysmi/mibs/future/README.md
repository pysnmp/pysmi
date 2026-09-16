# Held modules

**This tier is empty.** Everything that was here is in `../asn1/` now, and
the wheel carries all 485 modules the manifest names.

The mechanism stays, because a module may earn a hold again. What it is: a
module kept in the source tree, named in `../bundled_mibs.json` with `"tier":
"future"`, and left out of the wheel. `MibCompiler` never registers this
directory, so no compile resolves against it. `hatch_build.py` does not render
anything here into `pysmi/mibs/pysnmp/`. `scripts/update_bundled_mibs.py
--check` does not re-fetch it and does not ask the RFC Editor whether its pins
still stand, so a copy here can be years behind its publisher with nothing
saying so.

## Why it emptied

The hold rested on a survey: nothing in the corpus pysmi is built against
imported one of these, pysnmp shipped none, and neither repository's code,
tests or documentation named one. The survey was accurate. It was the wrong
question.

pysmi is a general-purpose compiler, and its users compile their own MIBs. A
device MIB importing `ADSL2-LINE-MIB` or an IEEE 802.1 module failed with the
file it needed in no release at all: the wheel excluded it, and pysnmp/mibs
had deleted its own copies on the grounds that the bundle supplied them. That
nothing *here* imports a module says nothing about what anyone else imports.

The evidence that settled it came from outside: observium, an independent
monitoring distribution, ships 200 of the 274 modules that were held here.
They were not modules nobody wanted. They were modules nobody here had needed
yet.

Carrying the whole tier costs about 3 MB, against the 3.3 MB the wheel
already was.

## Hold one

A module belongs here when carrying it would be actively wrong, not merely
unused. Superseded text kept for provenance is the shape that fits. "Nothing
imports it yet" is not, and is what emptied this directory.

Set `"tier": "future"` on the manifest entry and move the file here. The entry
keeps its provenance and supersession either way: those are facts about a
module rather than about the directory it sits in, and a promotion should not
mean working them out a second time.

## Promote one

**Any use is reason enough.** A module in the corpus that imports one, a
consumer that asks for one, a test that needs one -- none of those needs a
further case made for it:

    uv run scripts/update_bundled_mibs.py --promote MODULE-NAME

That moves the file into `../asn1/`, clears the `tier` on its manifest entry,
re-fetches it from the publisher recorded there -- the held copy is presumed
stale -- verifies the enlarged bundle still compiles, and rewrites the
inventory page. Nothing else has to be edited by hand.

See `docs/source/bundled-mibs.rst`.
