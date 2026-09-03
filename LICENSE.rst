Copyright (c) 2015-2019 Ilya Etingof <etingof@gmail.com>
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

  * Redistributions of source code must retain the above copyright notice, 
    this list of conditions and the following disclaimer.

  * Redistributions in binary form must reproduce the above copyright notice,
    this list of conditions and the following disclaimer in the documentation
    and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE 
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE 
ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.

Third-party MIB sources
========================

``pysmi/mibs/asn1/`` bundles a handful of standard ASN.1 MIB modules pysmi
falls back to compiling when no other source has them (see
pysnmp/pysmi#113). These are unmodified upstream text, not code covered by
the license above, and carry their own copyright notices:

  * ``RFC1213-MIB``, ``SNMPv2-TC``, ``SNMPv2-CONF`` -- Copyright (c) 1994,
    1996 by cisco Systems, Inc. All rights reserved.

  * ``RFC1158-MIB`` -- (C)opyright 2004-2014 bintec elmeg GmbH.

``RFC1155-SMI``, ``RFC-1212``, ``RFC-1215``, and ``SNMPv2-SMI``,
``SNMPv2-MIB`` carry no copyright notice of their own, being definitions
excerpted directly from their respective IETF RFCs.
