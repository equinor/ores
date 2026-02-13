"""Peek at OSDU records for RESQML conversion."""
import json, pathlib

p = pathlib.Path(r"c:\Users\MAAP\OneDrive - Equinor\source\ores\demo\drogon\records")

# RAW volumes (010)
f010 = list(p.glob("010_*.json"))[0]
d010 = json.loads(f010.read_text("utf-8"))
vol = d010["data"].get("Volumes") or d010["data"].get("Table")
kc = vol.get("KeyColumns", [])
vc = vol.get("Columns", [])
cv = vol.get("ColumnValues", {})

print("=== RAW VOLUMES (010) ===")
print(f"Name: {d010['data'].get('Name')}")
print(f"ID: {d010.get('id')}")
print(f"KeyColumns: {len(kc)}")
for c in kc:
    print(f"  {c['ColumnName']} ({c['ValueType']})")
print(f"ValueColumns: {len(vc)}")
for c in vc:
    uom = c.get("UnitOfMeasureID", "")
    print(f"  {c['ColumnName']} ({c['ValueType']}) UoM={uom}")
print(f"Rows: {len(list(cv.values())[0])}")
print(f"All column names: {list(cv.keys())}")
print()

# STAT volumes (011)
f011 = list(p.glob("011_*.json"))[0]
d011 = json.loads(f011.read_text("utf-8"))
vol2 = d011["data"].get("Volumes") or d011["data"].get("Table")
kc2 = vol2.get("KeyColumns", [])
vc2 = vol2.get("Columns", [])
cv2 = vol2.get("ColumnValues", {})

print("=== STAT VOLUMES (011) ===")
print(f"Name: {d011['data'].get('Name')}")
print(f"ID: {d011.get('id')}")
print(f"KeyColumns: {len(kc2)}")
for c in kc2:
    print(f"  {c['ColumnName']} ({c['ValueType']})")
print(f"ValueColumns: {len(vc2)}")
for c in vc2:
    uom = c.get("UnitOfMeasureID", "")
    print(f"  {c['ColumnName']} ({c['ValueType']}) UoM={uom}")
print(f"Rows: {len(list(cv2.values())[0])}")
print(f"All column names: {list(cv2.keys())}")
