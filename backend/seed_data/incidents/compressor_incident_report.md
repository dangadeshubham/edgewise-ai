# INCIDENT INVESTIGATION REPORT: COMPRESSOR C-102
**Document ID:** INC-2026-031  
**Plant Location:** Site-Alpha / Gas Processing Train B  
**Equipment Tag:** COMP-C102 (Multi-stage Reciprocating Compressor)  
**Date of Incident:** 2026-03-14 03:14 UTC  
**Severity Classification:** High (Unscheduled Process Trip)

## 1. Sequence of Events
- **02:45 UTC:** Bearing temperature transmitter TT-102B indicated steady climb from normal 65 deg C to 78 deg C.
- **03:02 UTC:** High temperature pre-alarm annunciated in DCS console at 80 deg C. Field operator dispatched for visual inspection.
- **03:12 UTC:** Drive-end radial vibration sensor VS-102B spiked from 1.8 mm/s to 4.6 mm/s RMS.
- **03:14 UTC:** Temperature reached 94 deg C, exceeding emergency shutdown threshold (90 deg C). Unit tripped automatically on ESD logic block.

## 2. Root Cause Analysis
Disassembly of drive-end journal bearing revealed:
1. Significant babbit wiping on lower shell half.
2. Contamination of lube oil circuit with metallic particulate (25-50 micron brass shavings).
3. Primary lube oil duplex filter cartridge DP gauge failed to indicate filter bypass condition.

## 3. Corrective Actions Required
- [x] Replace journal bearing assembly and polish shaft journal to 0.4 Ra finish.
- [ ] Flush complete lube oil reservoir with fresh ISO VG 68 lubricant.
- [ ] Calibrate differential pressure transmitter across duplex lube filters.
- [ ] Update shift handover log and verify clearance before restart.
