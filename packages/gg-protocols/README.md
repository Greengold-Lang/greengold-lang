# gg-protocols

Avionics, space and drone link layers:

- `arinc429.gg`: 32-bit words (label bit order, SDI, SSM, odd parity), BNR and BCD data fields.
- `mil1553.gg`: MIL-STD-1553B command and status words, the parity bit.
- `ccsds.gg`: CCSDS Space Packets (primary header, CRC-16 packet error control).
- `mavlink.gg`: MAVLink 1 and 2 framing and the checksum. The per-message `CRC_EXTRA` comes from the dialect; none is bundled.

FIX is in the standard library (`std.fix`). Not included: ARINC 664 (AFDX) and the 1553 bus controller (they need the hardware), message definitions for
MAVLink dialects, signature verification, CCSDS TM/TC transfer frames. The label of an ARINC 429 word is written as a plain number (octal 310 is 200).
The byte layouts are checked against an independent Python implementation in `tests/test_ext_packages.py`; they have not been checked against
live equipment. Tests: `gg test packages/gg-protocols/tests`.
