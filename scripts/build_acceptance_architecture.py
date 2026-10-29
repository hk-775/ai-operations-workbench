"""Authored editable/static topology for optional AWS acceptance services."""
from html import escape
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]/"docs/architecture"
NODES = [
    ("cur", 70, 130, 350, 100, "#e0f2fe", "AWS Cost and Usage Reports", "Optional hourly CSV/gzip export"),
    ("billing", 500, 130, 350, 100, "#e0f2fe", "Amazon S3 · billing", "Private, encrypted, versioned"),
    ("collector", 930, 130, 350, 100, "#ede9fe", "Workbench billing collector", "Owner-scoped import + Ledger checks"),
    ("host", 70, 380, 350, 100, "#fef9c3", "Existing Amazon EC2 host", "Demo + clean workspaces keep serving"),
    ("backups", 500, 380, 350, 100, "#e0f2fe", "Amazon S3 · backups", "Scheduled dumps + private controls"),
    ("restore", 930, 380, 350, 100, "#ede9fe", "Disposable Amazon EC2 host", "Fresh disks · no ingress · SSM only"),
    ("ssm", 930, 570, 350, 100, "#ccfbf1", "AWS Systems Manager", "Readiness, table hashes, cleanup"),
    ("sns", 70, 570, 350, 100, "#ede9fe", "Amazon CloudWatch + SNS", "Existing alarms and machine receipts"),
    ("email", 500, 570, 350, 100, "#fafaf9", "Owner-selected email", "Optional · confirmation + human reply"),
]
EDGES = [
    ("cur", "billing", "delivery"),
    ("billing", "collector", "read only"),
    ("host", "backups", "backup"),
    ("backups", "restore", "read only"),
    ("ssm", "restore", "operate"),
    ("host", "sns", "health"),
    ("sns", "email", "confirm"),
]


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    mxfile = ET.Element("mxfile", host="app.diagrams.net")
    diagram = ET.SubElement(mxfile, "diagram", name="Optional AWS acceptance topology")
    graph = ET.SubElement(diagram, "mxGraphModel", page="1", pageWidth="1350", pageHeight="780")
    cells = ET.SubElement(graph, "root")
    ET.SubElement(cells, "mxCell", id="0")
    ET.SubElement(cells, "mxCell", id="1", parent="0")
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="1350" height="780" viewBox="0 0 1350 780">',
           '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0L8 4L0 8" fill="none" stroke="#7c3aed" stroke-width="1.5"/></marker></defs>',
           '<rect width="1350" height="780" fill="#fafaf9"/>',
           '<g font-family="Arial,sans-serif" fill="#1c1917">',
           '<text x="70" y="56" font-size="28" font-weight="700">Optional AWS acceptance services</text>',
           '<text x="70" y="88" font-size="18">Account-owned tools · independent recovery test · original hosted topology remains unchanged</text>',
           '<text x="70" y="303" font-size="17">Export delivery is asynchronous. Imported charges require captured usage and reviewed scope.</text>',
           '<text x="70" y="728" font-size="17">Temporary recovery resources are deleted after verification. This is not automatic failover or an HA topology.</text>',
           '<text x="70" y="756" font-size="15">No account identifiers, secrets, private endpoints, or customer data are embedded.</text>']
    positions = {item[0]: item[1:5] for item in NODES}
    for source, target, label in EDGES:
        x, y, width, height = positions[source]
        tx, ty, tw, th = positions[target]
        if x == tx:
            start = (x+width/2, y if ty < y else y+height)
            end = (tx+tw/2, ty+th if ty < y else ty)
            lx, ly = start[0]+14, (start[1]+end[1])/2
        else:
            start, end = (x+width, y+height/2), (tx, ty+th/2)
            lx, ly = (start[0]+end[0])/2, start[1]-13
        svg += [f'<path d="M{start[0]} {start[1]}L{end[0]} {end[1]}" fill="none" stroke="#7c3aed" stroke-width="2" marker-end="url(#arrow)"/>',
                f'<text x="{lx}" y="{ly}" text-anchor="middle" font-size="13">{escape(label)}</text>']
        cell = ET.SubElement(cells, "mxCell", id=source+"-"+target, value=label, edge="1",
                             parent="1", source=source, target=target,
                             style="edgeStyle=orthogonalEdgeStyle;rounded=1;strokeColor=#7c3aed;endArrow=block;")
        ET.SubElement(cell, "mxGeometry", relative="1", attrib={"as": "geometry"})
    for identity, x, y, width, height, color, title, subtitle in NODES:
        svg += [f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="18" fill="{color}" stroke="#c4b5fd" stroke-width="1.5"/>',
                f'<text x="{x+width/2}" y="{y+40}" text-anchor="middle" font-size="19" font-weight="700">{escape(title)}</text>',
                f'<text x="{x+width/2}" y="{y+69}" text-anchor="middle" font-size="15">{escape(subtitle)}</text>']
        cell = ET.SubElement(cells, "mxCell", id=identity, value=title+"\n"+subtitle, vertex="1",
                             parent="1", style=f"rounded=1;whiteSpace=wrap;html=0;fillColor={color};strokeColor=#c4b5fd;fontColor=#1c1917;fontSize=17;")
        ET.SubElement(cell, "mxGeometry", x=str(x), y=str(y), width=str(width), height=str(height),
                      attrib={"as": "geometry"})
    svg += ["</g></svg>"]
    (ROOT/"aws-acceptance.svg").write_text("\n".join(svg)+"\n")
    ET.indent(mxfile)
    ET.ElementTree(mxfile).write(ROOT/"aws-acceptance.drawio", encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    main()
