import json
from datetime import datetime

# Defaults pulled from the attached file (zfacetrole.json)
ACL = {
    "owners": ["data.default.owners@dev.dataservices.energy"],
    "viewers": ["data.office.global.viewers@dev.dataservices.energy"],
}
LEGAL = {
    "legaltags": ["dev-equinor-osdu-reference-default"],
    "otherRelevantDataCountries": ["NO"],
}

# Partition/namespace
partition = "dev"

# FacetType to use for these roles
facet_type = "statistics"

# Name/Code pairs provided by user
pairs = [
    ("Arithmetic Mean", "ArithmeticMean"),
    ("P10", "P10"),
    ("P50", "P50"),
    ("P90", "P90"),
    ("Minimum", "Minimum"),
    ("Maximum", "Maximum"),
    ("Standard Deviation", "StardardDeviation"),
    ("Geometric Mean", "GeometricMean"),
    ("Harmonic Mean", "HarmonicMean"),
]

reference_entries = []
for name, code in pairs:
    reference_entries.append({
        "kind": "osdu:wks:reference-data--FacetRole:1.1.0",
        # Record IDs in OSDU are canonical without trailing ':'; natural-key form is acceptable
        "id": f"{partition}:reference-data--FacetRole:{code}",
        "acl": ACL,
        "legal": LEGAL,
        "data": {
            "Name": name,
            "Code": code,
            "Description": f"Facet role '{name}' under FacetType '{facet_type}'.",
            # FacetRole 1.1.0 uses FacetType as a string field
            "FacetType": facet_type,
        }
    })

manifest = {
    "kind": "osdu:wks:Manifest:1.0.0",
    "ReferenceData": reference_entries,
    "MasterData": [],
    "Data": {
        "Datasets": [],
        "WorkProductComponents": [],
        "WorkProduct": []
    }
}

out_name = "reftypes_facetroles.json"
with open(out_name, "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2)

print(out_name)
print("Entries:", len(reference_entries))