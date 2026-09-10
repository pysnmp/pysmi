# Changelog

Generated from the commit history at release time. The narrative history
through 1.0.5 is in [CHANGES.rst](https://github.com/pysnmp/pysmi/blob/main/CHANGES.rst).

## [4.0.0](https://github.com/pysnmp/pysmi/compare/v3.1.0...v4.0.0) (2026-09-10)

### ⚠ BREAKING CHANGES

* **patches:** readers implement fetch_data() rather than get_data(); a
subclass overriding get_data() still works but skips patching. Patching is on
by default -- mibdump --no-mib-patches turns it off, --mib-patch-source
replaces the bundled set, and AbstractReader.usePatches/patchSet are the
library equivalents. pysmi/mibs/asn1 in the source tree now holds the
published text for the twelve patched modules; the wheel is unchanged.

Closes #185.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
* **mibs:** pysmi.mibs.behavior() is gone and generated modules no longer
carry a spliced runtime-behavior tail. Consumers relying on that tail must
apply their own behavior at load time, as pysnmp now does. PYSNMP-USM-MIB is
no longer in PySnmpCodeGen.baseMibs, so a StubSearcher built from it no longer
reports that module as up to date.

### Features

* **codegen:** declare the pysnmp API the generator emits ([fe233aa](https://github.com/pysnmp/pysmi/commit/fe233aa467883571f25df52f237779db9b1148db))
* **corpus:** check a build for the invariants a corpus must not violate ([08fa621](https://github.com/pysnmp/pysmi/commit/08fa621201a1198aa55f6f98339b2bac8aa79c5e)), closes [#230](https://github.com/pysnmp/pysmi/issues/230) [#230](https://github.com/pysnmp/pysmi/issues/230) [pysnmp/mibs#363](https://github.com/pysnmp/mibs/issues/363) [pysnmp/pysnmp#199](https://github.com/pysnmp/pysnmp/issues/199)
* **corpus:** let a build stamp the database it writes ([ba93a13](https://github.com/pysnmp/pysmi/commit/ba93a1314ad88dcb6c789dfe550196752308d8bc)), closes [#230](https://github.com/pysnmp/pysmi/issues/230) [pysnmp/pysnmp#199](https://github.com/pysnmp/pysnmp/issues/199)
* **corpus:** make the key encoding part of the conformance contract ([ee392d0](https://github.com/pysnmp/pysmi/commit/ee392d0c4353eddc36937698653638dbe05ddb55)), closes [#184](https://github.com/pysnmp/pysmi/issues/184) [#230](https://github.com/pysnmp/pysmi/issues/230) [pysnmp/pysnmp#199](https://github.com/pysnmp/pysnmp/issues/199)
* **corpus:** publish the precedence rule as vectors both projects run ([26f0262](https://github.com/pysnmp/pysmi/commit/26f0262013f31b633711767c8d43c7e313696563)), closes [#248](https://github.com/pysnmp/pysmi/issues/248)
* **mibs:** attach hand-written runtime behavior to a bundled module ([888b944](https://github.com/pysnmp/pysmi/commit/888b944eede7b617755ae34f501fdccec6e4b692)), closes [#231](https://github.com/pysnmp/pysmi/issues/231)
* **mibs:** give snmpEngineTime the elapsed-seconds read RFC 3411 describes ([7a8e948](https://github.com/pysnmp/pysmi/commit/7a8e9488d04e023bc819de8eb613592c127bb004)), closes [#236](https://github.com/pysnmp/pysmi/issues/236) [#231](https://github.com/pysnmp/pysmi/issues/231)
* **patches:** carry the patch with the MIB, not with the bundle ([8e22340](https://github.com/pysnmp/pysmi/commit/8e2234042c4c9cb3a4b54557ea9671fb55cc1805))

### Bug Fixes

* **ci:** keep the behavior fragments out of mypy's file list and name the codegen by its module ([7dd4952](https://github.com/pysnmp/pysmi/commit/7dd495206d32ebb0b6b8b47cba075ce3864cd4e5))
* **codegen:** set the encoding a UTF-8 DISPLAY-HINT states ([58a3e3f](https://github.com/pysnmp/pysmi/commit/58a3e3f2a26d19d53cce4f5c4d252029c8417519))
* **corpus:** report a damaged corpus rather than raising sqlite3 out of validate ([93c40cf](https://github.com/pysnmp/pysmi/commit/93c40cf989bde668b48b82ceb455ff18d9bbc658))
* **mibs:** re-seed the objects a behavior fragment's class attribute built ([6d91544](https://github.com/pysnmp/pysmi/commit/6d915448d4076e9335e3bf23d393ea82184c25b7)), closes [#236](https://github.com/pysnmp/pysmi/issues/236)
* **tests:** do not name a directory "we?ird" on a platform that forbids it ([d325e5f](https://github.com/pysnmp/pysmi/commit/d325e5f3ca8d94fa2c96d5315334e46622091e78)), closes [#235](https://github.com/pysnmp/pysmi/issues/235) [#235](https://github.com/pysnmp/pysmi/issues/235)

### Code Refactoring

* **mibs:** hand MIB runtime behavior back to pysnmp ([40c7f22](https://github.com/pysnmp/pysmi/commit/40c7f225ebbbd9ba7ab424441ed8b903ac651e42)), closes [#236](https://github.com/pysnmp/pysmi/issues/236) [#231](https://github.com/pysnmp/pysmi/issues/231) [#236](https://github.com/pysnmp/pysmi/issues/236)

## [4.0.0-rc.4](https://github.com/pysnmp/pysmi/compare/v4.0.0-rc.3...v4.0.0-rc.4) (2026-09-10)

> **Corrected.** The notes generated for this release announced a breaking
> reader API — `fetch_data()`, `AbstractReader.usePatches`/`patchSet`,
> `mibdump --no-mib-patches`/`--mib-patch-source` — that the tag does not
> contain. That API was added and then withdrawn within the same pull request,
> and only the first commit's `BREAKING CHANGE:` footer reached the generator.
> Nothing in `4.0.0-rc.4` breaks a caller of `4.0.0-rc.3`. See
> [#254](https://github.com/pysnmp/pysmi/issues/254).
>
> The `4.0.0` major is still warranted by
> [4.0.0-rc.1](https://github.com/pysnmp/pysmi/releases/tag/v4.0.0-rc.1), which
> removed `pysmi.mibs.behavior()`.

### Changes

* **patches:** apply the twelve MIB repairs when a distribution is built
rather than when the bundle is refreshed
([8e22340](https://github.com/pysnmp/pysmi/commit/8e2234042c4c9cb3a4b54557ea9671fb55cc1805),
[84bb507](https://github.com/pysnmp/pysmi/commit/84bb50707192244b54ae4f09462c03b4407d039a)).
The source tree now holds each publisher's text verbatim and the diffs live in
`scripts/mib-patches/`, so a refresh diffs against the publisher and what pysmi
repairs is a diff of its own. `hatch_build.py` applies them into the
distribution, whose `pysmi/mibs/asn1/` is byte-identical to rc.3's. Neither
`scripts/patches.py` nor the diffs are installed. Closes
[#185](https://github.com/pysnmp/pysmi/issues/185).
* **corpus:** conformance vectors now cover every column the DDL declares, and
the schema version is pinned so a schema change cannot land without the vectors
moving with it
([c97f985](https://github.com/pysnmp/pysmi/commit/c97f985803d351140d860db858b8d6fc778f7d07)). Closes
[#251](https://github.com/pysnmp/pysmi/issues/251).

## [4.0.0-rc.3](https://github.com/pysnmp/pysmi/compare/v4.0.0-rc.2...v4.0.0-rc.3) (2026-09-10)

### Features

* **corpus:** publish the precedence rule as vectors both projects run ([26f0262](https://github.com/pysnmp/pysmi/commit/26f0262013f31b633711767c8d43c7e313696563)), closes [#248](https://github.com/pysnmp/pysmi/issues/248)

## [3.1.0](https://github.com/pysnmp/pysmi/compare/v3.0.0...v3.1.0) (2026-09-10)

### Features

* **corpus:** build core.db, the corpus laid out for lookup ([2f7769b](https://github.com/pysnmp/pysmi/commit/2f7769bff54afe3011c0a5fefecf229d14d4f040)), closes [pysnmp/pysmi#183](https://github.com/pysnmp/pysmi/issues/183) [pysnmp/pysnmp#196](https://github.com/pysnmp/pysnmp/issues/196) [pysnmp/pysnmp#199](https://github.com/pysnmp/pysnmp/issues/199)
* **corpus:** publish a conformance fixture for corpus readers ([b4b749a](https://github.com/pysnmp/pysmi/commit/b4b749a707ab2e7e9806de592f80ddb172b0707b)), closes [pysnmp/pysmi#184](https://github.com/pysnmp/pysmi/issues/184) [pysnmp/pysnmp#199](https://github.com/pysnmp/pysnmp/issues/199)

### Bug Fixes

* **corpus:** keep core.db opt-in, key the corpus cache, count nodes once ([a12187c](https://github.com/pysnmp/pysmi/commit/a12187cba3409d6ba3d03463d6dcff3baaa2f302))

## [4.0.0-rc.2](https://github.com/pysnmp/pysmi/compare/v4.0.0-rc.1...v4.0.0-rc.2) (2026-09-09)

### Features

* **codegen:** declare the pysnmp API the generator emits ([fe233aa](https://github.com/pysnmp/pysmi/commit/fe233aa467883571f25df52f237779db9b1148db))

## [4.0.0-rc.1](https://github.com/pysnmp/pysmi/compare/v3.1.0-rc.4...v4.0.0-rc.1) (2026-09-09)

### ⚠ BREAKING CHANGES

* **mibs:** pysmi.mibs.behavior() is gone and generated modules no longer
carry a spliced runtime-behavior tail. Consumers relying on that tail must
apply their own behavior at load time, as pysnmp now does. PYSNMP-USM-MIB is
no longer in PySnmpCodeGen.baseMibs, so a StubSearcher built from it no longer
reports that module as up to date.

### Code Refactoring

* **mibs:** hand MIB runtime behavior back to pysnmp ([40c7f22](https://github.com/pysnmp/pysmi/commit/40c7f225ebbbd9ba7ab424441ed8b903ac651e42)), closes [#236](https://github.com/pysnmp/pysmi/issues/236) [#231](https://github.com/pysnmp/pysmi/issues/231) [#236](https://github.com/pysnmp/pysmi/issues/236)

## [3.1.0-rc.4](https://github.com/pysnmp/pysmi/compare/v3.1.0-rc.3...v3.1.0-rc.4) (2026-09-09)

### Features

* **mibs:** give snmpEngineTime the elapsed-seconds read RFC 3411 describes ([7a8e948](https://github.com/pysnmp/pysmi/commit/7a8e9488d04e023bc819de8eb613592c127bb004)), closes [#236](https://github.com/pysnmp/pysmi/issues/236) [#231](https://github.com/pysnmp/pysmi/issues/231)

## [3.1.0-rc.3](https://github.com/pysnmp/pysmi/compare/v3.1.0-rc.2...v3.1.0-rc.3) (2026-09-09)

### Bug Fixes

* **mibs:** re-seed the objects a behavior fragment's class attribute built ([6d91544](https://github.com/pysnmp/pysmi/commit/6d915448d4076e9335e3bf23d393ea82184c25b7)), closes [#236](https://github.com/pysnmp/pysmi/issues/236)

## [3.1.0-rc.2](https://github.com/pysnmp/pysmi/compare/v3.1.0-rc.1...v3.1.0-rc.2) (2026-09-09)

### Features

* **corpus:** check a build for the invariants a corpus must not violate ([08fa621](https://github.com/pysnmp/pysmi/commit/08fa621201a1198aa55f6f98339b2bac8aa79c5e)), closes [#230](https://github.com/pysnmp/pysmi/issues/230) [#230](https://github.com/pysnmp/pysmi/issues/230) [pysnmp/mibs#363](https://github.com/pysnmp/mibs/issues/363) [pysnmp/pysnmp#199](https://github.com/pysnmp/pysnmp/issues/199)
* **corpus:** let a build stamp the database it writes ([ba93a13](https://github.com/pysnmp/pysmi/commit/ba93a1314ad88dcb6c789dfe550196752308d8bc)), closes [#230](https://github.com/pysnmp/pysmi/issues/230) [pysnmp/pysnmp#199](https://github.com/pysnmp/pysnmp/issues/199)
* **corpus:** make the key encoding part of the conformance contract ([ee392d0](https://github.com/pysnmp/pysmi/commit/ee392d0c4353eddc36937698653638dbe05ddb55)), closes [#184](https://github.com/pysnmp/pysmi/issues/184) [#230](https://github.com/pysnmp/pysmi/issues/230) [pysnmp/pysnmp#199](https://github.com/pysnmp/pysnmp/issues/199)

### Bug Fixes

* **corpus:** report a damaged corpus rather than raising sqlite3 out of validate ([93c40cf](https://github.com/pysnmp/pysmi/commit/93c40cf989bde668b48b82ceb455ff18d9bbc658))
* **tests:** do not name a directory "we?ird" on a platform that forbids it ([d325e5f](https://github.com/pysnmp/pysmi/commit/d325e5f3ca8d94fa2c96d5315334e46622091e78)), closes [#235](https://github.com/pysnmp/pysmi/issues/235) [#235](https://github.com/pysnmp/pysmi/issues/235)

## [3.1.0-rc.1](https://github.com/pysnmp/pysmi/compare/v3.0.0...v3.1.0-rc.1) (2026-09-09)

### Features

* **corpus:** build core.db, the corpus laid out for lookup ([2f7769b](https://github.com/pysnmp/pysmi/commit/2f7769bff54afe3011c0a5fefecf229d14d4f040)), closes [pysnmp/pysmi#183](https://github.com/pysnmp/pysmi/issues/183) [pysnmp/pysnmp#196](https://github.com/pysnmp/pysnmp/issues/196) [pysnmp/pysnmp#199](https://github.com/pysnmp/pysnmp/issues/199)
* **corpus:** publish a conformance fixture for corpus readers ([b4b749a](https://github.com/pysnmp/pysmi/commit/b4b749a707ab2e7e9806de592f80ddb172b0707b)), closes [pysnmp/pysmi#184](https://github.com/pysnmp/pysmi/issues/184) [pysnmp/pysnmp#199](https://github.com/pysnmp/pysnmp/issues/199)
* **mibs:** attach hand-written runtime behavior to a bundled module ([888b944](https://github.com/pysnmp/pysmi/commit/888b944eede7b617755ae34f501fdccec6e4b692)), closes [#231](https://github.com/pysnmp/pysmi/issues/231)

### Bug Fixes

* **ci:** keep the behavior fragments out of mypy's file list and name the codegen by its module ([7dd4952](https://github.com/pysnmp/pysmi/commit/7dd495206d32ebb0b6b8b47cba075ce3864cd4e5))
* **codegen:** set the encoding a UTF-8 DISPLAY-HINT states ([58a3e3f](https://github.com/pysnmp/pysmi/commit/58a3e3f2a26d19d53cce4f5c4d252029c8417519))
* **corpus:** keep core.db opt-in, key the corpus cache, count nodes once ([a12187c](https://github.com/pysnmp/pysmi/commit/a12187cba3409d6ba3d03463d6dcff3baaa2f302))

## [3.0.0](https://github.com/pysnmp/pysmi/compare/v2.3.0...v3.0.0) (2026-09-09)

### ⚠ BREAKING CHANGES

* **mibs:** the wheel carries 210 ASN.1 modules and 207 precompiled pysnmp
modules where it carried 485 and 484. A caller compiling a module that imports
one of the 275 now resolves it from its own --mib-source instead of from the
bundle. pysmi.mibs.manifest() still names all 485; pysmi.mibs.bundled() is the
set an install actually supplies.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018PviAP7g1mTiiSDn4fRQsq
* **compiler:** a failed MIB no longer suppresses the output of unrelated
MIBs compiled in the same call; they are written. mibdump --ignore-errors
no longer changes which modules are written -- it now suppresses the
non-zero exit status instead. A caller that relied on an all-or-nothing
batch should compile one module per call.

Refs #182.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EBV5NVv7NB6R1Wx9vRypt6
* **codegen:** generated pysnmp modules no longer test mibBuilder.version
before calling setStatus, setProductRelease, setRevisionsDescriptions or
setObjects(append=True), and they now call setReference() on ObjectGroup,
NotificationGroup and ModuleCompliance. Loading one requires a pysnmp that
implements those setters: pysnmplib 6.0.0rc5 or later, or pysnmp 7.x. A
pysnmp 4.4.x runtime, which the removed branches existed for, is no longer
supported -- recompile against a supported release rather than loading
newly generated modules into it.

Closes #194. Refs pysnmp/pysnmp#197.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EBV5NVv7NB6R1Wx9vRypt6
* **compiler:** `mibdump --repair-imports` is replaced by
`mibdump --strict-imports`. The repair it used to request is now what happens;
the new flag asks for the old strict behaviour, which is what a caller
validating a MIB rather than consuming one wants. Programmatically,
`repairImports=False` is the same opt-out and is unchanged. A repair is never
silent: every one is listed on the "Repaired MIBs" line of the report and
recorded in the symbol table under `_symtable_repaired`.

### Features

* **codegen:** canonical form and content hash over the module model ([965e559](https://github.com/pysnmp/pysmi/commit/965e55963d352e4cbc276f5edcb7f9cfccf3a740)), closes [#190](https://github.com/pysnmp/pysmi/issues/190) [#191](https://github.com/pysnmp/pysmi/issues/191) [#180](https://github.com/pysnmp/pysmi/issues/180)
* **codegen:** target the loader contract instead of inferring it ([bd5db61](https://github.com/pysnmp/pysmi/commit/bd5db61ca4a1553d3850548eff4abbcc83370034)), closes [pysnmp/pysnmp#133](https://github.com/pysnmp/pysnmp/issues/133) [pysnmp/pysnmp#197](https://github.com/pysnmp/pysnmp/issues/197)
* **compiler:** repair a forced missing import by default, and drop 9 patches ([c091932](https://github.com/pysnmp/pysmi/commit/c091932e8d01d99e45207eb7036ede4a4a7b191f)), closes [#185](https://github.com/pysnmp/pysmi/issues/185) [#185](https://github.com/pysnmp/pysmi/issues/185)
* **compiler:** swap sources on a live compiler, keeping the parse cache ([cf1ce44](https://github.com/pysnmp/pysmi/commit/cf1ce44f46c1ebb0f3ead5f0f8eb37a39a2bd31d)), closes [#181](https://github.com/pysnmp/pysmi/issues/181)
* **corpus:** build a corpus from many source namespaces, deterministically ([138d99c](https://github.com/pysnmp/pysmi/commit/138d99cb329abe5a84fc87c03825ad7bcdea59bb)), closes [pysnmp/pysnmp#196](https://github.com/pysnmp/pysnmp/issues/196) [#183](https://github.com/pysnmp/pysmi/issues/183) [#182](https://github.com/pysnmp/pysmi/issues/182)
* **corpus:** let a namespace be resolved against without being published ([beffff6](https://github.com/pysnmp/pysmi/commit/beffff6ff161154a72f012bc6fa3c00fa4300b4a)), closes [#182](https://github.com/pysnmp/pysmi/issues/182)
* **mibdump:** --build-all compiles every module the sources hold ([9d92921](https://github.com/pysnmp/pysmi/commit/9d92921dae459b0e4cbf380f3fc25073b3d8d83a))
* **mibdump:** --emit writes every format from one read of the sources ([27c5711](https://github.com/pysnmp/pysmi/commit/27c5711fe54cde1c1d9d6347079251cdc7db70f3))
* **mibs:** bundle IPSEC-ISAKMP-IKE-DOI-TC from the draft that defines it ([185d962](https://github.com/pysnmp/pysmi/commit/185d962207233e2b61b3c6055586018e6d35a236)), closes [#212](https://github.com/pysnmp/pysmi/issues/212) [#212](https://github.com/pysnmp/pysmi/issues/212)
* **mibs:** bundle sFlow.org's SFLOW-MIB, not RFC 3176's ([cad444e](https://github.com/pysnmp/pysmi/commit/cad444e6aff18e3e8ffed2c21c717b0a4b5cb83a))
* **mibs:** bundle the 119 RFC MIB modules the bundle was still missing ([f44d363](https://github.com/pysnmp/pysmi/commit/f44d36321edbd3dcdbae954ed32c32208f99fca9)), closes [#212](https://github.com/pysnmp/pysmi/issues/212) [#212](https://github.com/pysnmp/pysmi/issues/212)
* **mibs:** bundle the SMIv1 compatibility shims ([ed27c8c](https://github.com/pysnmp/pysmi/commit/ed27c8caaf56a5c105a576a00e31e170c1e507c1)), closes [#161](https://github.com/pysnmp/pysmi/issues/161)
* **mibs:** bundle the standards modules from pysnmp/mibs src/standard ([b18f6e9](https://github.com/pysnmp/pysmi/commit/b18f6e9fb1cbd44cbe6512104ba1ec7bcf03e733)), closes [#187](https://github.com/pysnmp/pysmi/issues/187)
* **mibs:** hold the 275 bundled modules nothing in the corpus imports ([32042ea](https://github.com/pysnmp/pysmi/commit/32042ea19f007c6bf7bbdeb2e04bbf41422ede79))
* **parser:** tolerate an OBJECT-TYPE descriptor that starts upper case ([51a689b](https://github.com/pysnmp/pysmi/commit/51a689be0acdc4f70bf3fd5f7fdb013c195a6553))
* **pysnmp:** state the MODULE-IDENTITY revision as a constant in emitted modules ([4ef57ca](https://github.com/pysnmp/pysmi/commit/4ef57ca6f5c1876e9bfb7d92ababb05d3a61b90a)), closes [pysnmp/pysnmp#198](https://github.com/pysnmp/pysnmp/issues/198)
* **reader:** ask a source what MIB modules it holds ([ee42ca3](https://github.com/pysnmp/pysmi/commit/ee42ca339796f14d101c7cb1e05162ffd34d4daa))

### Bug Fixes

* **build:** stop generating the three modules that cannot be generated ([95d56fe](https://github.com/pysnmp/pysmi/commit/95d56fe019e78640b7b05189e2b7ab3a5a7493cc)), closes [pysnmp/pysnmp#198](https://github.com/pysnmp/pysnmp/issues/198) [pysnmp/pysnmp#198](https://github.com/pysnmp/pysnmp/issues/198) [#196](https://github.com/pysnmp/pysmi/issues/196)
* **cache:** identify a parser by its dialect, not just its class ([1141971](https://github.com/pysnmp/pysmi/commit/11419719a74aba006ca9c40e7004eb4e989dd844)), closes [#181](https://github.com/pysnmp/pysmi/issues/181)
* **cache:** size the in-memory parse cache above a real source set ([95ceadc](https://github.com/pysnmp/pysmi/commit/95ceadce24cd312a61d918f903d3998777f27bf5))
* **compiler:** make comment stripping string-aware, and apply it to the inventory ([d0f12fa](https://github.com/pysnmp/pysmi/commit/d0f12fa84179f891c57931d02febd0a47fc93a24)), closes [pysnmp/pysnmp#198](https://github.com/pysnmp/pysnmp/issues/198)
* **compiler:** omit only the failed MIB and what imports it ([472d6c8](https://github.com/pysnmp/pysmi/commit/472d6c82000c55eda96b04f9c0bdd2b59cd7a162))
* **compiler:** the newest revision decides every name, not only bundled ones ([86304df](https://github.com/pysnmp/pysmi/commit/86304df36cc6aa460e336532716fbed263446e2b))
* **corpus:** keep the docs build and Windows green ([bf06c16](https://github.com/pysnmp/pysmi/commit/bf06c16d3d0763a4dd42389aab8adbcaa03d7585)), closes [#182](https://github.com/pysnmp/pysmi/issues/182)
* **jsondoc:** emit a module whose symbol is spelled like a Python keyword ([dd7e2d9](https://github.com/pysnmp/pysmi/commit/dd7e2d9f429f75fa604f8a397e9b9257e3a43d5c)), closes [#225](https://github.com/pysnmp/pysmi/issues/225)
* **jsondoc:** keep AGENT-CAPABILITIES variations when texts are off ([e5d67a2](https://github.com/pysnmp/pysmi/commit/e5d67a2a2f42289d570c9f1a9748fd355406cdb0)), closes [#196](https://github.com/pysnmp/pysmi/issues/196) [#198](https://github.com/pysnmp/pysmi/issues/198) [#190](https://github.com/pysnmp/pysmi/issues/190) [pysnmp/pysnmp#198](https://github.com/pysnmp/pysnmp/issues/198) [pysnmp/pysnmp#198](https://github.com/pysnmp/pysnmp/issues/198) [#186](https://github.com/pysnmp/pysmi/issues/186)
* **jsondoc:** suppress prose and nothing else when texts are off ([e9f74e2](https://github.com/pysnmp/pysmi/commit/e9f74e23f3021af73ae1ad9fb82438c5a9968ab8)), closes [#191](https://github.com/pysnmp/pysmi/issues/191) [#192](https://github.com/pysnmp/pysmi/issues/192) [#190](https://github.com/pysnmp/pysmi/issues/190) [#190](https://github.com/pysnmp/pysmi/issues/190) [#191](https://github.com/pysnmp/pysmi/issues/191) [#192](https://github.com/pysnmp/pysmi/issues/192)
* **mibinfo:** refuse a revision stamp that is not a date ([349d7e3](https://github.com/pysnmp/pysmi/commit/349d7e3e41d30b3b438b9fea245417c00421e0f0)), closes [#185](https://github.com/pysnmp/pysmi/issues/185)
* **mibs:** keep the three patches that were correcting more than an import ([d992cf9](https://github.com/pysnmp/pysmi/commit/d992cf982efae2cab655dc958791daf838c41cb7))
* **mibs:** make DSA-MIB and RDBMS-MIB load, by naming the module their symbols are in ([bf2008c](https://github.com/pysnmp/pysmi/commit/bf2008ca5ccd0d5713e72be95bafa26d0308a623)), closes [#199](https://github.com/pysnmp/pysmi/issues/199)
* **pysnmp:** carry LAST-UPDATED in the revision constant, not the newest REVISION ([73f4202](https://github.com/pysnmp/pysmi/commit/73f42026dde84b630cf7778e061ce261acc8f2f8)), closes [pysnmp/pysnmp#198](https://github.com/pysnmp/pysnmp/issues/198)
* **schema:** declare agentcapabilities, and make the schema itself valid ([54f85b1](https://github.com/pysnmp/pysmi/commit/54f85b1a0599d664aced5fa3671f5233f70aef22)), closes [#190](https://github.com/pysnmp/pysmi/issues/190)
* **schema:** require status on agentcapabilities, and list it as a class ([126bf58](https://github.com/pysnmp/pysmi/commit/126bf589e1c90f4efd2e97ed1d48d5af3ff87b5a))
* **tests:** fail when a bundled module compiles to nothing ([62cedd6](https://github.com/pysnmp/pysmi/commit/62cedd6d7ff9fe39f815c53494605b2d53a7b78a)), closes [#203](https://github.com/pysnmp/pysmi/issues/203)
* **writer:** create the temporary file with the mode a new file gets ([9ff800b](https://github.com/pysnmp/pysmi/commit/9ff800b01a1e3e3c38ec6fe38846ad81259a2902)), closes [#227](https://github.com/pysnmp/pysmi/issues/227) [#227](https://github.com/pysnmp/pysmi/issues/227)
* **writer:** store a module anyone can read, not only the user who built it ([33943bf](https://github.com/pysnmp/pysmi/commit/33943bfdc95052407e9c7bbd86fef7b0a82bd21a)), closes [#182](https://github.com/pysnmp/pysmi/issues/182)

## [3.0.0-rc.8](https://github.com/pysnmp/pysmi/compare/v3.0.0-rc.7...v3.0.0-rc.8) (2026-09-08)

### Bug Fixes

* **writer:** store a module anyone can read, not only the user who built it ([33943bf](https://github.com/pysnmp/pysmi/commit/33943bfdc95052407e9c7bbd86fef7b0a82bd21a)), closes [#182](https://github.com/pysnmp/pysmi/issues/182)

## [3.0.0-rc.7](https://github.com/pysnmp/pysmi/compare/v3.0.0-rc.6...v3.0.0-rc.7) (2026-09-08)

### Features

* **corpus:** build a corpus from many source namespaces, deterministically ([138d99c](https://github.com/pysnmp/pysmi/commit/138d99cb329abe5a84fc87c03825ad7bcdea59bb)), closes [pysnmp/pysnmp#196](https://github.com/pysnmp/pysnmp/issues/196) [#183](https://github.com/pysnmp/pysmi/issues/183) [#182](https://github.com/pysnmp/pysmi/issues/182)
* **corpus:** let a namespace be resolved against without being published ([beffff6](https://github.com/pysnmp/pysmi/commit/beffff6ff161154a72f012bc6fa3c00fa4300b4a)), closes [#182](https://github.com/pysnmp/pysmi/issues/182)

### Bug Fixes

* **corpus:** keep the docs build and Windows green ([bf06c16](https://github.com/pysnmp/pysmi/commit/bf06c16d3d0763a4dd42389aab8adbcaa03d7585)), closes [#182](https://github.com/pysnmp/pysmi/issues/182)
* **jsondoc:** emit a module whose symbol is spelled like a Python keyword ([dd7e2d9](https://github.com/pysnmp/pysmi/commit/dd7e2d9f429f75fa604f8a397e9b9257e3a43d5c)), closes [#225](https://github.com/pysnmp/pysmi/issues/225)

## [3.0.0-rc.6](https://github.com/pysnmp/pysmi/compare/v3.0.0-rc.5...v3.0.0-rc.6) (2026-09-08)

### Bug Fixes

* **mibs:** make DSA-MIB and RDBMS-MIB load, by naming the module their symbols are in ([bf2008c](https://github.com/pysnmp/pysmi/commit/bf2008ca5ccd0d5713e72be95bafa26d0308a623)), closes [#199](https://github.com/pysnmp/pysmi/issues/199)

## [3.0.0-rc.5](https://github.com/pysnmp/pysmi/compare/v3.0.0-rc.4...v3.0.0-rc.5) (2026-09-08)

### ⚠ BREAKING CHANGES

* **mibs:** the wheel carries 210 ASN.1 modules and 207 precompiled pysnmp
modules where it carried 485 and 484. A caller compiling a module that imports
one of the 275 now resolves it from its own --mib-source instead of from the
bundle. pysmi.mibs.manifest() still names all 485; pysmi.mibs.bundled() is the
set an install actually supplies.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018PviAP7g1mTiiSDn4fRQsq

### Features

* **mibdump:** --build-all compiles every module the sources hold ([9d92921](https://github.com/pysnmp/pysmi/commit/9d92921dae459b0e4cbf380f3fc25073b3d8d83a))
* **mibs:** hold the 275 bundled modules nothing in the corpus imports ([32042ea](https://github.com/pysnmp/pysmi/commit/32042ea19f007c6bf7bbdeb2e04bbf41422ede79))
* **reader:** ask a source what MIB modules it holds ([ee42ca3](https://github.com/pysnmp/pysmi/commit/ee42ca339796f14d101c7cb1e05162ffd34d4daa))

## [3.0.0-rc.4](https://github.com/pysnmp/pysmi/compare/v3.0.0-rc.3...v3.0.0-rc.4) (2026-09-08)

### Features

* **mibs:** bundle sFlow.org's SFLOW-MIB, not RFC 3176's ([cad444e](https://github.com/pysnmp/pysmi/commit/cad444e6aff18e3e8ffed2c21c717b0a4b5cb83a))

## [3.0.0-rc.3](https://github.com/pysnmp/pysmi/compare/v3.0.0-rc.2...v3.0.0-rc.3) (2026-09-08)

### Features

* **mibdump:** --emit writes every format from one read of the sources ([27c5711](https://github.com/pysnmp/pysmi/commit/27c5711fe54cde1c1d9d6347079251cdc7db70f3))
* **mibs:** bundle IPSEC-ISAKMP-IKE-DOI-TC from the draft that defines it ([185d962](https://github.com/pysnmp/pysmi/commit/185d962207233e2b61b3c6055586018e6d35a236)), closes [#212](https://github.com/pysnmp/pysmi/issues/212) [#212](https://github.com/pysnmp/pysmi/issues/212)

### Bug Fixes

* **cache:** size the in-memory parse cache above a real source set ([95ceadc](https://github.com/pysnmp/pysmi/commit/95ceadce24cd312a61d918f903d3998777f27bf5))
* **compiler:** the newest revision decides every name, not only bundled ones ([86304df](https://github.com/pysnmp/pysmi/commit/86304df36cc6aa460e336532716fbed263446e2b))

## [3.0.0-rc.2](https://github.com/pysnmp/pysmi/compare/v3.0.0-rc.1...v3.0.0-rc.2) (2026-09-08)

### Features

* **parser:** tolerate an OBJECT-TYPE descriptor that starts upper case ([51a689b](https://github.com/pysnmp/pysmi/commit/51a689be0acdc4f70bf3fd5f7fdb013c195a6553))

## [3.0.0-rc.1](https://github.com/pysnmp/pysmi/compare/v2.4.0-rc.2...v3.0.0-rc.1) (2026-09-08)

### ⚠ BREAKING CHANGES

* **compiler:** a failed MIB no longer suppresses the output of unrelated
MIBs compiled in the same call; they are written. mibdump --ignore-errors
no longer changes which modules are written -- it now suppresses the
non-zero exit status instead. A caller that relied on an all-or-nothing
batch should compile one module per call.

Refs #182.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EBV5NVv7NB6R1Wx9vRypt6
* **codegen:** generated pysnmp modules no longer test mibBuilder.version
before calling setStatus, setProductRelease, setRevisionsDescriptions or
setObjects(append=True), and they now call setReference() on ObjectGroup,
NotificationGroup and ModuleCompliance. Loading one requires a pysnmp that
implements those setters: pysnmplib 6.0.0rc5 or later, or pysnmp 7.x. A
pysnmp 4.4.x runtime, which the removed branches existed for, is no longer
supported -- recompile against a supported release rather than loading
newly generated modules into it.

Closes #194. Refs pysnmp/pysnmp#197.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EBV5NVv7NB6R1Wx9vRypt6
* **compiler:** `mibdump --repair-imports` is replaced by
`mibdump --strict-imports`. The repair it used to request is now what happens;
the new flag asks for the old strict behaviour, which is what a caller
validating a MIB rather than consuming one wants. Programmatically,
`repairImports=False` is the same opt-out and is unchanged. A repair is never
silent: every one is listed on the "Repaired MIBs" line of the report and
recorded in the symbol table under `_symtable_repaired`.

### Features

* **codegen:** target the loader contract instead of inferring it ([bd5db61](https://github.com/pysnmp/pysmi/commit/bd5db61ca4a1553d3850548eff4abbcc83370034)), closes [pysnmp/pysnmp#133](https://github.com/pysnmp/pysnmp/issues/133) [pysnmp/pysnmp#197](https://github.com/pysnmp/pysnmp/issues/197)
* **compiler:** repair a forced missing import by default, and drop 9 patches ([c091932](https://github.com/pysnmp/pysmi/commit/c091932e8d01d99e45207eb7036ede4a4a7b191f)), closes [#185](https://github.com/pysnmp/pysmi/issues/185) [#185](https://github.com/pysnmp/pysmi/issues/185)
* **compiler:** swap sources on a live compiler, keeping the parse cache ([cf1ce44](https://github.com/pysnmp/pysmi/commit/cf1ce44f46c1ebb0f3ead5f0f8eb37a39a2bd31d)), closes [#181](https://github.com/pysnmp/pysmi/issues/181)
* **mibs:** bundle the 119 RFC MIB modules the bundle was still missing ([f44d363](https://github.com/pysnmp/pysmi/commit/f44d36321edbd3dcdbae954ed32c32208f99fca9)), closes [#212](https://github.com/pysnmp/pysmi/issues/212) [#212](https://github.com/pysnmp/pysmi/issues/212)

### Bug Fixes

* **cache:** identify a parser by its dialect, not just its class ([1141971](https://github.com/pysnmp/pysmi/commit/11419719a74aba006ca9c40e7004eb4e989dd844)), closes [#181](https://github.com/pysnmp/pysmi/issues/181)
* **compiler:** omit only the failed MIB and what imports it ([472d6c8](https://github.com/pysnmp/pysmi/commit/472d6c82000c55eda96b04f9c0bdd2b59cd7a162))
* **mibinfo:** refuse a revision stamp that is not a date ([349d7e3](https://github.com/pysnmp/pysmi/commit/349d7e3e41d30b3b438b9fea245417c00421e0f0)), closes [#185](https://github.com/pysnmp/pysmi/issues/185)
* **mibs:** keep the three patches that were correcting more than an import ([d992cf9](https://github.com/pysnmp/pysmi/commit/d992cf982efae2cab655dc958791daf838c41cb7))

## [2.4.0-rc.2](https://github.com/pysnmp/pysmi/compare/v2.4.0-rc.1...v2.4.0-rc.2) (2026-09-07)

### Features

* **pysnmp:** state the MODULE-IDENTITY revision as a constant in emitted modules ([4ef57ca](https://github.com/pysnmp/pysmi/commit/4ef57ca6f5c1876e9bfb7d92ababb05d3a61b90a)), closes [pysnmp/pysnmp#198](https://github.com/pysnmp/pysnmp/issues/198)

### Bug Fixes

* **compiler:** make comment stripping string-aware, and apply it to the inventory ([d0f12fa](https://github.com/pysnmp/pysmi/commit/d0f12fa84179f891c57931d02febd0a47fc93a24)), closes [pysnmp/pysnmp#198](https://github.com/pysnmp/pysnmp/issues/198)
* **pysnmp:** carry LAST-UPDATED in the revision constant, not the newest REVISION ([73f4202](https://github.com/pysnmp/pysmi/commit/73f42026dde84b630cf7778e061ce261acc8f2f8)), closes [pysnmp/pysnmp#198](https://github.com/pysnmp/pysnmp/issues/198)
* **tests:** fail when a bundled module compiles to nothing ([62cedd6](https://github.com/pysnmp/pysmi/commit/62cedd6d7ff9fe39f815c53494605b2d53a7b78a)), closes [#203](https://github.com/pysnmp/pysmi/issues/203)

## [2.4.0-rc.1](https://github.com/pysnmp/pysmi/compare/v2.3.0...v2.4.0-rc.1) (2026-09-07)

### Features

* **codegen:** canonical form and content hash over the module model ([965e559](https://github.com/pysnmp/pysmi/commit/965e55963d352e4cbc276f5edcb7f9cfccf3a740)), closes [#190](https://github.com/pysnmp/pysmi/issues/190) [#191](https://github.com/pysnmp/pysmi/issues/191) [#180](https://github.com/pysnmp/pysmi/issues/180)
* **mibs:** bundle the SMIv1 compatibility shims ([ed27c8c](https://github.com/pysnmp/pysmi/commit/ed27c8caaf56a5c105a576a00e31e170c1e507c1)), closes [#161](https://github.com/pysnmp/pysmi/issues/161)
* **mibs:** bundle the standards modules from pysnmp/mibs src/standard ([b18f6e9](https://github.com/pysnmp/pysmi/commit/b18f6e9fb1cbd44cbe6512104ba1ec7bcf03e733)), closes [#187](https://github.com/pysnmp/pysmi/issues/187)

### Bug Fixes

* **build:** stop generating the three modules that cannot be generated ([95d56fe](https://github.com/pysnmp/pysmi/commit/95d56fe019e78640b7b05189e2b7ab3a5a7493cc)), closes [pysnmp/pysnmp#198](https://github.com/pysnmp/pysnmp/issues/198) [pysnmp/pysnmp#198](https://github.com/pysnmp/pysnmp/issues/198) [#196](https://github.com/pysnmp/pysmi/issues/196)
* **jsondoc:** keep AGENT-CAPABILITIES variations when texts are off ([e5d67a2](https://github.com/pysnmp/pysmi/commit/e5d67a2a2f42289d570c9f1a9748fd355406cdb0)), closes [#196](https://github.com/pysnmp/pysmi/issues/196) [#198](https://github.com/pysnmp/pysmi/issues/198) [#190](https://github.com/pysnmp/pysmi/issues/190) [pysnmp/pysnmp#198](https://github.com/pysnmp/pysnmp/issues/198) [pysnmp/pysnmp#198](https://github.com/pysnmp/pysnmp/issues/198) [#186](https://github.com/pysnmp/pysmi/issues/186)
* **jsondoc:** suppress prose and nothing else when texts are off ([e9f74e2](https://github.com/pysnmp/pysmi/commit/e9f74e23f3021af73ae1ad9fb82438c5a9968ab8)), closes [#191](https://github.com/pysnmp/pysmi/issues/191) [#192](https://github.com/pysnmp/pysmi/issues/192) [#190](https://github.com/pysnmp/pysmi/issues/190) [#190](https://github.com/pysnmp/pysmi/issues/190) [#191](https://github.com/pysnmp/pysmi/issues/191) [#192](https://github.com/pysnmp/pysmi/issues/192)
* **schema:** declare agentcapabilities, and make the schema itself valid ([54f85b1](https://github.com/pysnmp/pysmi/commit/54f85b1a0599d664aced5fa3671f5233f70aef22)), closes [#190](https://github.com/pysnmp/pysmi/issues/190)
* **schema:** require status on agentcapabilities, and list it as a class ([126bf58](https://github.com/pysnmp/pysmi/commit/126bf589e1c90f4efd2e97ed1d48d5af3ff87b5a))

## [2.3.0](https://github.com/pysnmp/pysmi/compare/v2.2.0...v2.3.0) (2026-09-06)

### Features

* **mibs:** ship the bundle manifest, and answer which module replaced a subtree ([ea4bded](https://github.com/pysnmp/pysmi/commit/ea4bdeda4bd7a20fe931d0112a3a66f4bea19d23)), closes [#174](https://github.com/pysnmp/pysmi/issues/174)

### Bug Fixes

* **mibs:** drop the three withdrawn IPv6 modules nothing imports ([c7c4fb7](https://github.com/pysnmp/pysmi/commit/c7c4fb7e05109fa48185cc4101ac94ab5e72ef90)), closes [#173](https://github.com/pysnmp/pysmi/issues/173)

## [2.2.0-rc.3](https://github.com/pysnmp/pysmi/compare/v2.2.0-rc.2...v2.2.0-rc.3) (2026-09-07)

### Features

* **codegen:** canonical form and content hash over the module model ([965e559](https://github.com/pysnmp/pysmi/commit/965e55963d352e4cbc276f5edcb7f9cfccf3a740)), closes [#190](https://github.com/pysnmp/pysmi/issues/190) [#191](https://github.com/pysnmp/pysmi/issues/191) [#180](https://github.com/pysnmp/pysmi/issues/180)
* **mibs:** bundle the SMIv1 compatibility shims ([ed27c8c](https://github.com/pysnmp/pysmi/commit/ed27c8caaf56a5c105a576a00e31e170c1e507c1)), closes [#161](https://github.com/pysnmp/pysmi/issues/161)

### Bug Fixes

* **build:** stop generating the three modules that cannot be generated ([95d56fe](https://github.com/pysnmp/pysmi/commit/95d56fe019e78640b7b05189e2b7ab3a5a7493cc)), closes [pysnmp/pysnmp#198](https://github.com/pysnmp/pysnmp/issues/198) [pysnmp/pysnmp#198](https://github.com/pysnmp/pysnmp/issues/198) [#196](https://github.com/pysnmp/pysmi/issues/196)
* **jsondoc:** keep AGENT-CAPABILITIES variations when texts are off ([e5d67a2](https://github.com/pysnmp/pysmi/commit/e5d67a2a2f42289d570c9f1a9748fd355406cdb0)), closes [#196](https://github.com/pysnmp/pysmi/issues/196) [#198](https://github.com/pysnmp/pysmi/issues/198) [#190](https://github.com/pysnmp/pysmi/issues/190) [pysnmp/pysnmp#198](https://github.com/pysnmp/pysnmp/issues/198) [pysnmp/pysnmp#198](https://github.com/pysnmp/pysnmp/issues/198) [#186](https://github.com/pysnmp/pysmi/issues/186)
* **jsondoc:** suppress prose and nothing else when texts are off ([e9f74e2](https://github.com/pysnmp/pysmi/commit/e9f74e23f3021af73ae1ad9fb82438c5a9968ab8)), closes [#191](https://github.com/pysnmp/pysmi/issues/191) [#192](https://github.com/pysnmp/pysmi/issues/192) [#190](https://github.com/pysnmp/pysmi/issues/190) [#190](https://github.com/pysnmp/pysmi/issues/190) [#191](https://github.com/pysnmp/pysmi/issues/191) [#192](https://github.com/pysnmp/pysmi/issues/192)
* **mibs:** drop the three withdrawn IPv6 modules nothing imports ([c7c4fb7](https://github.com/pysnmp/pysmi/commit/c7c4fb7e05109fa48185cc4101ac94ab5e72ef90)), closes [#173](https://github.com/pysnmp/pysmi/issues/173)
* **schema:** declare agentcapabilities, and make the schema itself valid ([54f85b1](https://github.com/pysnmp/pysmi/commit/54f85b1a0599d664aced5fa3671f5233f70aef22)), closes [#190](https://github.com/pysnmp/pysmi/issues/190)
* **schema:** require status on agentcapabilities, and list it as a class ([126bf58](https://github.com/pysnmp/pysmi/commit/126bf589e1c90f4efd2e97ed1d48d5af3ff87b5a))

## [2.2.0](https://github.com/pysnmp/pysmi/compare/v2.1.1...v2.2.0) (2026-09-06)

### Features

* **mibdump:** write out the base MIBs a JSON tree needs to stand alone ([d37c274](https://github.com/pysnmp/pysmi/commit/d37c2749740f6366bcbcc1db49fc5396cb6924a8))
* **mibs:** bundle the standard MIB set, each pinned to its publisher ([4533c62](https://github.com/pysnmp/pysmi/commit/4533c626aa40d5b3875e2242ac89e6c7a3df65b9)), closes [#161](https://github.com/pysnmp/pysmi/issues/161)
* **mibs:** compile the bundled MIBs into pysnmp modules at build time ([47e9891](https://github.com/pysnmp/pysmi/commit/47e9891d6008f4f2907992eafcc07a4b736be219))
* **mibs:** report where the pysnmp/mibs mirror disagrees with the bundle ([a7c4853](https://github.com/pysnmp/pysmi/commit/a7c4853296afb97d6abac952f85d02bdfb5d651a)), closes [pysnmp/mibs#345](https://github.com/pysnmp/mibs/issues/345)
* say which rule picked a MIB, and let --mib-source outrank the bundle ([b2b1448](https://github.com/pysnmp/pysmi/commit/b2b1448bf0f3493fcae754dde484b49cc3dec560)), closes [#155](https://github.com/pysnmp/pysmi/issues/155)

### Bug Fixes

* let a module compiled from a fallback copy report as compiled ([26b1927](https://github.com/pysnmp/pysmi/commit/26b1927003555c6f98d75aa586ab49255cb884b1)), closes [#157](https://github.com/pysnmp/pysmi/issues/157) [#155](https://github.com/pysnmp/pysmi/issues/155)
* **mibdump:** report the base MIBs a run may write, not the ones it did ([01309b1](https://github.com/pysnmp/pysmi/commit/01309b134c0f3a865718743676f54cf5b56a699e))
* **mibs:** bundle IANA-GBOND-TC-MIB, and make verify catch what hid it ([a2d077c](https://github.com/pysnmp/pysmi/commit/a2d077c98ca933e982532b8935054b99be6bef50)), closes [pysnmp/mibs#343](https://github.com/pysnmp/mibs/issues/343)
* **mibs:** keep git's line-ending filters off the bundled MIB bytes ([f6741ce](https://github.com/pysnmp/pysmi/commit/f6741ceaa93bb20e0dded584b683fb191140d890))
* **mibs:** track IEEE 802.1 at its current revision, not a pinned file ([579da07](https://github.com/pysnmp/pysmi/commit/579da07e54d0dee11c6a2d98d68cea19226743c6))
* name the copy that actually parsed, under the name it parsed as ([f211f0d](https://github.com/pysnmp/pysmi/commit/f211f0dd106c998624ebbb06baf5cbfb85617558)), closes [#155](https://github.com/pysnmp/pysmi/issues/155)
* **reader:** report an over-long MIB name as missing, not a crash ([82699fe](https://github.com/pysnmp/pysmi/commit/82699fef859c4642887a9185a9badb2aef61546d)), closes [#163](https://github.com/pysnmp/pysmi/issues/163)
* report the resolved copy on runs that recompile nothing ([25e1e8e](https://github.com/pysnmp/pysmi/commit/25e1e8efbfd2aefb5682c9fdb84cb0cefbea83c4)), closes [#156](https://github.com/pysnmp/pysmi/issues/156) [#155](https://github.com/pysnmp/pysmi/issues/155)

## [2.2.0-rc.2](https://github.com/pysnmp/pysmi/compare/v2.2.0-rc.1...v2.2.0-rc.2) (2026-09-06)

### Features

* **mibdump:** write out the base MIBs a JSON tree needs to stand alone ([d37c274](https://github.com/pysnmp/pysmi/commit/d37c2749740f6366bcbcc1db49fc5396cb6924a8))
* **mibs:** bundle the standard MIB set, each pinned to its publisher ([4533c62](https://github.com/pysnmp/pysmi/commit/4533c626aa40d5b3875e2242ac89e6c7a3df65b9)), closes [#161](https://github.com/pysnmp/pysmi/issues/161)
* **mibs:** compile the bundled MIBs into pysnmp modules at build time ([47e9891](https://github.com/pysnmp/pysmi/commit/47e9891d6008f4f2907992eafcc07a4b736be219))
* **mibs:** report where the pysnmp/mibs mirror disagrees with the bundle ([a7c4853](https://github.com/pysnmp/pysmi/commit/a7c4853296afb97d6abac952f85d02bdfb5d651a)), closes [pysnmp/mibs#345](https://github.com/pysnmp/mibs/issues/345)

### Bug Fixes

* **mibdump:** report the base MIBs a run may write, not the ones it did ([01309b1](https://github.com/pysnmp/pysmi/commit/01309b134c0f3a865718743676f54cf5b56a699e))
* **mibs:** bundle IANA-GBOND-TC-MIB, and make verify catch what hid it ([a2d077c](https://github.com/pysnmp/pysmi/commit/a2d077c98ca933e982532b8935054b99be6bef50)), closes [pysnmp/mibs#343](https://github.com/pysnmp/mibs/issues/343)
* **mibs:** keep git's line-ending filters off the bundled MIB bytes ([f6741ce](https://github.com/pysnmp/pysmi/commit/f6741ceaa93bb20e0dded584b683fb191140d890))
* **mibs:** track IEEE 802.1 at its current revision, not a pinned file ([579da07](https://github.com/pysnmp/pysmi/commit/579da07e54d0dee11c6a2d98d68cea19226743c6))
* **reader:** report an over-long MIB name as missing, not a crash ([82699fe](https://github.com/pysnmp/pysmi/commit/82699fef859c4642887a9185a9badb2aef61546d)), closes [#163](https://github.com/pysnmp/pysmi/issues/163)

## [2.2.0-rc.1](https://github.com/pysnmp/pysmi/compare/v2.1.0...v2.2.0-rc.1) (2026-09-06)

### Features

* say which rule picked a MIB, and let --mib-source outrank the bundle ([b2b1448](https://github.com/pysnmp/pysmi/commit/b2b1448bf0f3493fcae754dde484b49cc3dec560)), closes [#155](https://github.com/pysnmp/pysmi/issues/155)

### Bug Fixes

* **ci:** publish docs from a branch, not a detached HEAD ([8ff1ecc](https://github.com/pysnmp/pysmi/commit/8ff1eccf667bf25cf55bb843b0ddbba45e8f9181))
* **ci:** publish docs from a branch, not a detached HEAD ([212f083](https://github.com/pysnmp/pysmi/commit/212f083df413a9073d2074b02bf325a5c4301666))
* let a module compiled from a fallback copy report as compiled ([26b1927](https://github.com/pysnmp/pysmi/commit/26b1927003555c6f98d75aa586ab49255cb884b1)), closes [#157](https://github.com/pysnmp/pysmi/issues/157) [#155](https://github.com/pysnmp/pysmi/issues/155)
* name the copy that actually parsed, under the name it parsed as ([f211f0d](https://github.com/pysnmp/pysmi/commit/f211f0dd106c998624ebbb06baf5cbfb85617558)), closes [#155](https://github.com/pysnmp/pysmi/issues/155)
* report the resolved copy on runs that recompile nothing ([25e1e8e](https://github.com/pysnmp/pysmi/commit/25e1e8efbfd2aefb5682c9fdb84cb0cefbea83c4)), closes [#156](https://github.com/pysnmp/pysmi/issues/156) [#155](https://github.com/pysnmp/pysmi/issues/155)

## [2.1.0](https://github.com/pysnmp/pysmi/compare/v2.0.1...v2.1.0) (2026-09-06)

### Features

* bundle every base MIB a code generator names ([9f1137a](https://github.com/pysnmp/pysmi/commit/9f1137a1c1f9e4bd2984be119b92f20d211bd761))
* bundle the standard MIBs real product MIBs import ([983a61a](https://github.com/pysnmp/pysmi/commit/983a61a8abdf3ef1e301fd9707bfeb574c61fc4b))
* define source precedence, and let it be checked ([28bd6bf](https://github.com/pysnmp/pysmi/commit/28bd6bfc7777ea038a7356891ec1cf74c17abb2d)), closes [#133](https://github.com/pysnmp/pysmi/issues/133)
* repair missing IMPORTS for SMIv2 base symbols behind --repair-imports ([c20d753](https://github.com/pysnmp/pysmi/commit/c20d7534c74af3aa74d4882cc591969344c9be91)), closes [#61](https://github.com/pysnmp/pysmi/issues/61)
* repair SNMPv2-MIB symbols that no SMIv1 MIB also defines ([94ce1ef](https://github.com/pysnmp/pysmi/commit/94ce1ef853d767883afce58d2f426f5f4eb397a6))

### Bug Fixes

* **release:** give the changelog a title semantic-release owns ([32d800a](https://github.com/pysnmp/pysmi/commit/32d800ae9ef17434812a5e7b383b0b0af47838f8))
* take the superseded MIBs from their RFC, not the mirror ([29350cf](https://github.com/pysnmp/pysmi/commit/29350cfdceeff34f21e78ff32070cc52b6453820))
* validate a DEFVAL against the object's own SYNTAX before emitting it ([b6fac5a](https://github.com/pysnmp/pysmi/commit/b6fac5a3122cc60c7875c1d80bc407b317071a07)), closes [#134](https://github.com/pysnmp/pysmi/issues/134)

## [2.1.0-rc.3](https://github.com/pysnmp/pysmi/compare/v2.1.0-rc.2...v2.1.0-rc.3) (2026-09-06)

### Bug Fixes

* **ci:** publish docs from a branch, not a detached HEAD ([212f083](https://github.com/pysnmp/pysmi/commit/212f083df413a9073d2074b02bf325a5c4301666))

## [2.1.0-rc.2](https://github.com/pysnmp/pysmi/compare/v2.1.0-rc.1...v2.1.0-rc.2) (2026-09-06)

### Bug Fixes

* **release:** give the changelog a title semantic-release owns ([32d800a](https://github.com/pysnmp/pysmi/commit/32d800ae9ef17434812a5e7b383b0b0af47838f8))

## [2.1.0-rc.1](https://github.com/pysnmp/pysmi/compare/v2.0.1...v2.1.0-rc.1) (2026-09-05)

### Features

* bundle every base MIB a code generator names ([9f1137a](https://github.com/pysnmp/pysmi/commit/9f1137a1c1f9e4bd2984be119b92f20d211bd761))
* bundle the standard MIBs real product MIBs import ([983a61a](https://github.com/pysnmp/pysmi/commit/983a61a8abdf3ef1e301fd9707bfeb574c61fc4b))
* define source precedence, and let it be checked ([28bd6bf](https://github.com/pysnmp/pysmi/commit/28bd6bfc7777ea038a7356891ec1cf74c17abb2d)), closes [#133](https://github.com/pysnmp/pysmi/issues/133)
* repair missing IMPORTS for SMIv2 base symbols behind --repair-imports ([c20d753](https://github.com/pysnmp/pysmi/commit/c20d7534c74af3aa74d4882cc591969344c9be91)), closes [#61](https://github.com/pysnmp/pysmi/issues/61)
* repair SNMPv2-MIB symbols that no SMIv1 MIB also defines ([94ce1ef](https://github.com/pysnmp/pysmi/commit/94ce1ef853d767883afce58d2f426f5f4eb397a6))

### Bug Fixes

* take the superseded MIBs from their RFC, not the mirror ([29350cf](https://github.com/pysnmp/pysmi/commit/29350cfdceeff34f21e78ff32070cc52b6453820))
* validate a DEFVAL against the object's own SYNTAX before emitting it ([b6fac5a](https://github.com/pysnmp/pysmi/commit/b6fac5a3122cc60c7875c1d80bc407b317071a07)), closes [#134](https://github.com/pysnmp/pysmi/issues/134)
