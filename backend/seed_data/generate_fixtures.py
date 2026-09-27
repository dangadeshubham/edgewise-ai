"""
Helper script to generate real industrial fixture files:
- PDF (with text pages)
- PDF (image-only / scanned without text)
- DOCX (with paragraphs, headings, tables)
- TXT
- Markdown
- JSON
"""

import json
from pathlib import Path
import pymupdf as fitz
from docx import Document as DocxDocument

base_dir = Path(__file__).resolve().parent

manuals_dir = base_dir / "manuals"
incidents_dir = base_dir / "incidents"
maintenance_dir = base_dir / "maintenance"
equipment_dir = base_dir / "equipment"

for d in [manuals_dir, incidents_dir, maintenance_dir, equipment_dir]:
    d.mkdir(parents=True, exist_ok=True)

# 1. TXT: Centrifugal Pump Technical Manual
txt_content = """CENTRIFUGAL PUMP CP-400 TECHNICAL OPERATION MANUAL
Model: CP-400 High Pressure Horizontal Split-Case Pump
Manufacturer: FlowServe Industrial Systems
Revision: 3.2 | Date: 2026-01-15

1. SYSTEM SPECIFICATIONS
- Design Flow Rate: 450 m3/h at 2950 RPM
- Total Dynamic Head: 92 meters (8.9 bar differential)
- Impeller Diameter: 315 mm (Double-suction bronze alloy)
- Motor Rating: 55 kW, 400V, 3-phase, 50 Hz, TEFC enclosure
- Mechanical Seal: Plan 11 flush arrangement with carbon vs. silicon carbide faces
- Bearing Arrangement: Deep groove ball bearings (DE: 6312-C3, NDE: 7312-BEP paired)

2. LUBRICATION AND OPERATING LIMITS
- Lubricant: ISO VG 46 synthetic turbine oil
- Oil Sump Capacity: 1.4 Liters
- Maximum Continuous Operating Temperature: 82 deg C (alarm at 85 deg C, trip at 90 deg C)
- Maximum Allowable Vibration Velocity: 2.8 mm/s RMS (ISO 10816-3 Category Class II)

3. COMMISSIONING PROCEDURES
a. Ensure suction valve is fully open and discharge valve is throttled to 10%.
b. Vent all entrapped air from casing bleed valve until steady liquid stream appears.
c. Verify rotation direction clockwise viewed from coupling end.
d. Start motor and gradually open discharge valve within 30 seconds to avoid cavitation.
"""
with open(manuals_dir / "centrifugal_pump_manual.txt", "w", encoding="utf-8") as f:
    f.write(txt_content)

# 2. Markdown: Compressor Incident Report
md_content = """# INCIDENT INVESTIGATION REPORT: COMPRESSOR C-102
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
"""
with open(incidents_dir / "compressor_incident_report.md", "w", encoding="utf-8") as f:
    f.write(md_content)

# 3. JSON: Equipment Registry Specs
json_data = {
    "plant_site": "site-alpha",
    "last_audit_date": "2026-02-01",
    "assets": [
        {
            "tag": "PUMP-CP-400A",
            "type": "Centrifugal Pump",
            "location": "Pump Room 1",
            "criticality": "Critical",
            "operating_envelope": {
                "rated_flow_m3h": 450,
                "rated_head_m": 92,
                "max_temp_c": 85,
                "max_vibration_mms": 2.8
            },
            "last_overhaul": "2025-11-10"
        },
        {
            "tag": "COMP-C102",
            "type": "Reciprocating Compressor",
            "location": "Compressor House B",
            "criticality": "High",
            "operating_envelope": {
                "stages": 3,
                "discharge_pressure_bar": 42.5,
                "max_temp_c": 90,
                "max_vibration_mms": 3.5
            },
            "last_overhaul": "2026-03-15"
        },
        {
            "tag": "TURB-T800",
            "type": "Industrial Gas Turbine",
            "location": "Turbine Enclosure 3",
            "criticality": "Critical",
            "operating_envelope": {
                "power_output_mw": 12.5,
                "exhaust_gas_temp_c": 510,
                "rotor_speed_rpm": 11200
            },
            "last_overhaul": "2025-08-20"
        }
    ]
}
with open(equipment_dir / "equipment_registry.json", "w", encoding="utf-8") as f:
    json.dump(json_data, f, indent=2)

# 4. DOCX: Gas Turbine Maintenance SOP
doc = DocxDocument()
doc.add_heading("SOP-PM-440: Gas Turbine T-800 Inspection Procedure", level=0)
doc.add_paragraph("Standard Operating Procedure for preventative maintenance and hot-section borescope inspection.")

doc.add_heading("1. Safety Prerequisites", level=1)
doc.add_paragraph("Lockout/Tagout (LOTO) procedure #LOTO-GT-08 must be executed prior to unlatching enclosure access doors.")
doc.add_paragraph("Allow turbine casing temperature to fall below 50 deg C before inserting optical borescope guide tubes.")

doc.add_heading("2. Inspection Criteria Table", level=1)
table = doc.add_table(rows=1, cols=3)
hdr_cells = table.rows[0].cells
hdr_cells[0].text = "Component"
hdr_cells[1].text = "Acceptable Limit"
hdr_cells[2].text = "Action Threshold"

criteria = [
    ("Stage 1 Nozzle Guide Vanes", "Thermal oxidation < 0.2 mm depth", "Cracks exceeding 1.5 mm require blade set replacement"),
    ("Combustor Liner Transition Piece", "Minor surface crazing allowable", "Perforations or buckling require immediate overhaul"),
    ("Power Turbine Rotor Shrouds", "Rub depth <= 0.35 mm", "Blade tip clearance deficit under 0.8 mm"),
]
for comp, limit, action in criteria:
    row_cells = table.add_row().cells
    row_cells[0].text = comp
    row_cells[1].text = limit
    row_cells[2].text = action

doc.add_heading("3. Handover and Restart Authorizations", level=1)
doc.add_paragraph("Inspection results must be logged into the local Edge intelligence database. Lead maintenance technician signoff required.")
doc.save(maintenance_dir / "turbine_inspection_sop.docx")

# 5. Multi-page PDF: Industrial Maintenance Manual
pdf_doc = fitz.open()

# Page 1
page1 = pdf_doc.new_page(width=595, height=842)
page1.insert_text((50, 80), "EDGE INDUSTRIAL SYSTEMS - TECHNICAL SPECIFICATION", fontsize=16)
page1.insert_text((50, 120), "Equipment Type: Heavy Duty Process Pump Overhaul Guide", fontsize=12)
page1.insert_text((50, 150), "Document Reference: EIS-MAN-2026-V1", fontsize=10)
page1.insert_text((50, 190), "Section 1: Disassembly & Rotor Inspection", fontsize=14)
page1.insert_text((50, 220), "1.1 Drain casing and disconnect all auxiliary seal flush and cooling lines.", fontsize=10)
page1.insert_text((50, 240), "1.2 Mount dial test indicators (DTI) on both driving and non-driving ends.", fontsize=10)
page1.insert_text((50, 260), "1.3 Record total axial float before loosening bearing locknuts (nominal: 0.12 - 0.18 mm).", fontsize=10)
page1.insert_text((50, 280), "1.4 Carefully hoist top casing half using certified spreader beam and rated shackles.", fontsize=10)
page1.insert_text((50, 800), "Page 1 of 2 - Confidential Plant Documentation", fontsize=8)

# Page 2
page2 = pdf_doc.new_page(width=595, height=842)
page2.insert_text((50, 80), "Section 2: Mechanical Seal Installation & Alignment", fontsize=14)
page2.insert_text((50, 120), "2.1 Clean stuffing box face and verify perpendicularity within 0.05 mm TIR.", fontsize=10)
page2.insert_text((50, 140), "2.2 Slide mechanical seal cartridge over shaft sleeve using soapy water lubricant.", fontsize=10)
page2.insert_text((50, 160), "2.3 Tighten gland retaining nuts in cross pattern to torque of 45 Nm.", fontsize=10)
page2.insert_text((50, 180), "2.4 Perform laser shaft alignment: angular tolerance 0.05 mm/100mm, parallel offset 0.03 mm.", fontsize=10)
page2.insert_text((50, 220), "2.5 Rotate pump shaft by hand to confirm smooth, binding-free rotation.", fontsize=10)
page2.insert_text((50, 800), "Page 2 of 2 - Confidential Plant Documentation", fontsize=8)

pdf_doc.save(manuals_dir / "pump_overhaul_guide.pdf")
pdf_doc.close()

# 6. Image-only PDF (No extractable text) for testing OCR rejection requirement
image_pdf = fitz.open()
blank_page = image_pdf.new_page(width=595, height=842)
# Draw a rectangle/shape without text characters
shape = blank_page.new_shape()
shape.draw_rect(fitz.Rect(50, 50, 500, 750))
shape.finish(color=(0.2, 0.2, 0.2), fill=(0.9, 0.9, 0.9))
shape.commit()
image_pdf.save(manuals_dir / "image_only_scanned_sample.pdf")
image_pdf.close()

print("All realistic fixture files generated successfully.")
