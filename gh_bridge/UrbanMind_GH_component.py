"""UrbanMind Grasshopper client component (Rhino 8, Python 3 script component).

Paste this into a Grasshopper "Python 3 Script" component with:
  Inputs : canopy (float), albedo (float), run (bool)
  Outputs: meshes (list of Mesh), latency (str), log (str)

It POSTs the intervention parameters to the local UrbanMind backend
(demo/serve_demo.py or gh_bridge/server.py on port 8787), receives the
four-domain response fields, and builds one colored mesh per domain laid
out left to right: thermal, air quality, building energy, vegetation.
"""

import json
import urllib.request

import Rhino.Geometry as rg
import System.Drawing as sd

PALETTES = {
    "thermal": [(255, 211, 189), (255, 154, 104), (255, 92, 10), (131, 57, 20)],
    "air_quality": [(165, 201, 199), (112, 151, 149), (73, 108, 106), (16, 37, 36)],
    "building_energy": [(233, 228, 255), (178, 161, 255), (119, 89, 255), (96, 60, 255)],
    "vegetation": [(237, 255, 217), (196, 255, 133), (134, 219, 42), (92, 153, 28)],
}
CELL = 2.0     # model units per grid cell
GAP = 8.0      # spacing between domain panels
Z_SCALE = 4.0  # field value -> relief height


def colormap(v, stops):
    v = max(0.0, min(1.0, v))
    seg = min(len(stops) - 2, int(v * (len(stops) - 1)))
    t = v * (len(stops) - 1) - seg
    a, b = stops[seg], stops[seg + 1]
    return sd.Color.FromArgb(*[int(a[i] + (b[i] - a[i]) * t) for i in range(3)])


def field_mesh(field, palette, x_offset):
    n = len(field)
    flat = [v for row in field for v in row]
    lo, hi = min(flat), max(flat)
    rng = (hi - lo) or 1.0
    mesh = rg.Mesh()
    for j in range(n):
        for i in range(n):
            norm = (field[j][i] - lo) / rng
            mesh.Vertices.Add(x_offset + i * CELL, -j * CELL, norm * Z_SCALE)
            mesh.VertexColors.Add(colormap(norm, palette))
    for j in range(n - 1):
        for i in range(n - 1):
            a = j * n + i
            mesh.Faces.AddFace(a, a + 1, a + n + 1, a + n)
    mesh.Normals.ComputeNormals()
    return mesh


meshes, latency, log = [], "", ""
if run:
    body = json.dumps({"canopy_delta": canopy or 0.0,
                       "albedo_delta": albedo or 0.0}).encode()
    req = urllib.request.Request("http://127.0.0.1:8787/evaluate", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())

    size = data["size"]
    for d, name in enumerate(data["domains"]):
        meshes.append(field_mesh(data["fields"][d], PALETTES[name],
                                 d * (size * CELL + GAP)))
    latency = "%.1f ms" % data["elapsed_ms"]
    log = "domains: %s | params: %s" % (", ".join(data["domains"]), data["params"])
