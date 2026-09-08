# Held modules

Same provenance as `../asn1/` beside it, same manifest, same naming
convention -- one extensionless file per module, named exactly as the module
it holds. What differs is that nothing in the corpus pysmi is built against
reaches these: no module in https://github.com/pysnmp/mibs imports one, pysnmp
does not ship one, and neither repository's own code, tests or documentation
names one. They came in as parser pressure tests, which they did their job as,
and the bundle kept carrying them afterwards.

So they are kept, not maintained, and not shipped:

- `MibCompiler` never registers this directory, so no compile resolves against
  it. It is not a package and a wheel does not carry it -- only the source
  tree and the sdist do. Most of these are not at
  https://pysnmp.github.io/mibs/asn1/ either, because that tree is built from
  the bundle: promoting is how one comes back, not fetching.
- `hatch_build.py` does not render these into `pysmi/mibs/pysnmp/`.
- `scripts/update_bundled_mibs.py --check` does not re-fetch any of it, and
  does not ask the RFC Editor whether its pins still stand. A copy here may be
  years behind its publisher and nothing will say so.

Their manifest entries stay in `../bundled_mibs.json`, carrying `"tier":
"future"`. Provenance and supersession are facts about a module rather than
about the directory it sits in, and a promotion should not mean working them
out a second time.

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
