# Changelog

Generated from the commit history at release time. The narrative history
through 1.0.5 is in [CHANGES.rst](https://github.com/pysnmp/pysmi/blob/main/CHANGES.rst).

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
