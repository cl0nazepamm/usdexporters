# 3ds Max Editable_Point — Native Instancing Research

Date: 2026-08-05
Tested against: 3ds Max 2027.2 (build 29000, `maxVersion()` → `#(29000, 70, 0, 29, 2, 0, 20588, 2027, ".2")`)
Test scene: Scrapyard (MW2), exported via Clone_PowerUSD Assembly Parts mode
(`v16_assembly_mode`): 276 prototype assets / 479 prototype meshes / 5,778
instance placements / 258 source materials.

3ds Max 2027.2 exposes `Editable_Point`, a `GeometryClass` object with a
`PointObject` mixin interface that draws true GPU instances of real Max nodes.
Until now only `USDStageObject` used this machinery. It is directly consumable
from PowerUSD's Assembly Parts output, and this document records what was
verified by test so the behaviour does not have to be rediscovered.

**Headline result:** the entire Scrapyard instance set — 5,778 placements
expanded to 7,279 instanced meshes — collapses to **one** scene node that
redraws in **0.8 ms**, against a 172 MB flattened `.max` for the same content.
The blocker is that the 2027.2 viewport does not shade instances.

---

## Discovering the API

`discover_plugin_classes` does not find it and `inspect_plugin_class` reports
`PLUGIN_MISSING`. Enumerate superclass class lists instead:

```maxscript
for c in GeometryClass.classes do ...   -- finds Editable_Point
```

The interface is only reachable off the **base object**, not the node, and only
via a stringstream capture:

```maxscript
local ep = Editable_Point()
local ss = stringstream ""
showInterface (getInterface ep.baseobject #PointObject) to:ss
```

## Data model

An `Editable_Point` holds:

* an ordered **instance node list** (`.instanceNodes`), appended with
  `AddInstanceNode <node> &indexOut`
* a set of **points**, each with a position
* named **channels** of per-point data

Everything is **0-based**: instance node indices, point IDs, and channel IDs.

### Channels that matter

| Channel | Type | Role |
|---|---|---|
| `#Positions` | point3 | implicit, channel id 0 |
| `#InstanceShape` | I32 | index into `.instanceNodes`; default **-1** (draws nothing) |
| `#Transform` | Matrix3 | per-point rotation/scale basis |
| `#Rotation` | point3 | Euler **degrees** — *not* a quat |
| `#Scale` | point3 | |
| `#Color` | BMMColorFloat | per-instance flat colour tint (works in viewport) |
| `#MaterialColor` / `#MaterialFlags` | point3 / U8 | no observable viewport effect |

### Verified semantics

* **`#Transform` overrides `#Rotation` and `#Scale`.** Setting a Matrix3 wins
  over the Euler/scale channels regardless of write order. Use it — it removes
  all Euler-order ambiguity and carries non-uniform scale and shear.
* **`#Rotation` is Euler degrees.** Passing a `quat` silently no-ops: the values
  do not apply and no error is raised. This cost a debugging cycle.
* **Prototype node transforms are ignored entirely.** Moving, rotating and
  scaling a prototype node (pos `[0,0,500]`, 45°, scale 3) changed nothing about
  the instances. `Editable_Point` instances *object-space geometry only*. Where
  the prototype nodes are parked is irrelevant, and their transforms cannot be
  used to offset instances.
* **Prototype nodes may be hidden** — instances still draw. Park them on a
  hidden layer.
* `instanceDisplayType`: `0` = bounding-box proxy, `1` = full geometry,
  `2` = point/dot proxy. The property does **not** clamp — it accepts any
  integer, so reading it back tells you nothing about the valid range.
* Node bbox (`.min`/`.max`) covers **points only**, not instanced geometry, so
  it is useless as a probe for whether instancing is working.

### USD → Max transform mapping is direct

USD `Gf.Matrix4d` is row-major with translation in row 3 — the same layout as
Max `matrix3`. No transpose, no axis swap (both stages are Z-up):

```python
pos   = Point3(m[3][0]*S, m[3][1]*S, m[3][2]*S)     # translation scales
basis = Matrix3(Point3(m[0][0], m[0][1], m[0][2]),
                Point3(m[1][0], m[1][1], m[1][2]),
                Point3(m[2][0], m[2][1], m[2][2]),
                Point3(0, 0, 0))                     # basis is dimensionless
```

**Only the translation takes the unit scale.** Rows 0–2 are dimensionless
rotation/scale and must not be scaled, because the prototype geometry is already
imported at that scale.

### Unit scale must be measured, never assumed

Max's USD importer applied **×100** (metersPerUnit 1.0 → centimetres) to a stage
authored with `metersPerUnit = 1.0`. Hardcoding `1.0` places the whole map at
1/100 scale, silently, with no error anywhere.

Derive it at runtime by comparing a prototype's Max bbox against its USD
`extent`:

```
measured unit scale from '727_cross_section01':
  max_span=584.2000  usd_span=5.8420  ->  scale=100.000002
```

Verified: resulting EP bbox `[-41915.1, -27122.9, -15110.7] → [21667, 40646.4,
10259.1]` matches the Blender depsgraph extent exactly ×100.

## Calling the interface from pymxs

Max 2027 ships `pxr` (from the USD for 3ds Max plugin), so a single in-process
Python script can read the USD *and* build the geometry.

By-reference out-parameters do **not** expose a `.value`. They come back in the
**function's return tuple**:

```python
ok, index    = b.AddInstanceNode(node, pymxs.byref(None))    # (True, 0)
ok, chan_id  = b.AddStandardChannel(rt.Name("Transform"), pymxs.byref(None))
```

Parameters documented as *In and Out* (`AddPoints`' `idsOut`, `GetChannelValue`'s
`valueOut`) must be seeded with a real value — `byref(None)` raises
`Unable to convert: undefined to type: Integer`:

```python
ids = b.AddPoints(positions, pymxs.byref([]))[1]     # seed with a list
val = b.GetChannelValue(ch, pid, pymxs.byref(0))[1]  # seed with an int
```

`SetChannelValues` accepts plain Python lists of `Point3` / `Matrix3` / int
directly — no MAXScript array conversion needed.

---

## Materials — the current blocker

**`Editable_Point` carries prototype material and texture data correctly.
Collapsing an EP to Editable Poly yields properly textured geometry. The 2027.2
viewport instanced-draw path simply does not shade it, so instances display
flat.** This is a display gap, not a data-model limitation, and it is the single
thing standing between this technique and production use.

### Consequence for tooling

**Do not assign a material to the EP node.** Any material assigned there
overrides every instance (verified) and destroys the per-prototype data a later
collapse depends on. Leave `.material` undefined.

### Dead ends — do not re-litigate

Each of these was tested and failed:

* **Multi/Sub-Object renders black.** Tested at both 3 slots and 479 slots, with
  correct per-prototype face MatIDs stamped via `polyop.setFaceMatID`, using
  both `MaxUsdPreviewSurface` and plain `PhysicalMaterial` sub-materials. Always
  black. Sub-material class and slot count are irrelevant.
* **`Material_Switcher` resolves but does not dispatch.** It applies its single
  active `.selection` to *every* instance. It is a variant toggler, not a
  per-instance material container.
* **`#MaterialColor` and `#MaterialFlags` do nothing observable.** Setting
  `#MaterialColor` with `#MaterialFlags` at 0 or 1 left instances untinted.
  `#Color` is the channel that actually tints — flat colour only, no textures.
* **`USDStageObject` has no Max material at all** (`.material` → `None`). It
  shades through its own Hydra delegate with
  `PointInstancesDrawMode` / `MeshMergeMode` / `MeshMergeMaxInstances`. Its
  multi-material display is therefore **not** reproducible through the Max
  material system, and it is not a pattern EP can borrow.
* **`instanceDisplayType` has no material-bearing mode.** Modes 0/1/2 are
  bbox / geometry / dots.

### Rendering

`Editable_Point` does not render at all: *"Object <Editable Point> doesn't
implement GetRenderMesh - can't render"*. This blocks every renderer that
acquires geometry the standard way, not just Scanline. Renderers must opt in
through a dedicated instancing path, as Arnold does for `USDStageObject`. Treat
EP as a viewport/authoring representation only, and collapse or maintain a
parallel representation for rendering.

---

## Performance

Measured as mean wall time over 10 `redrawViews()` calls after a warm-up frame.

**Node count is free.** Same total points, trivial geometry, one flat material,
only the number of EP nodes varying:

| EP nodes | points/EP | ms/redraw |
|---|---|---|
| 1 | 7,279 | 1.4 |
| 25 | 291 | 1.9 |
| 100 | 72 | 1.6 |
| 413 | 17 | 1.3 |

**Real geometry is also cheap.** Full Scrapyard prototypes (479 meshes),
7,279 instances, single EP, one flat material, no textures:

| Config | ms/redraw |
|---|---|
| full geometry (`instanceDisplayType 1`) | 2.5 |
| bbox proxy (`instanceDisplayType 0`) | 1.1 |

Build cost is negligible — for 7,279 points, `AddPoints` 0.002 s and
`SetChannelValues` 0.003 s. A 100,000-instance synthetic case measured
`AddPoints` 15 ms, `SetChannelValues` 16 ms, full redraw 146 ms.

**Note on an earlier misattribution.** A build that split instances into 413
per-material EP nodes ran at 2–5 fps, and the split was initially blamed. The
scaling table above shows node count is not the cause; that same build also
enabled viewport display on 411 `MaxUsdPreviewSurface` shaders backed by ~900
TGA textures, which is the far more likely cost. The texture/shader hypothesis
was not isolated before the material question was settled, so it remains
**unconfirmed** — but the split is exonerated by measurement.

Throughout, the Max viewport statistics panel reports **Polys: 0, Verts: 0** —
instanced geometry does not count toward scene statistics.

---

## Consuming PowerUSD Assembly Parts output

`build_instances_usd` (`blender/Clone_PowerUSD/operators.py`) already authors
exactly the right substrate:

* `xmodels/<asset>.usdc` — per-asset prototype geometry with materials
* `instances.usdc` — one `UsdGeom.Xform` per placement at
  `/Instances/<asset>/<empty>`, `SetInstanceable(True)`, referencing the xmodel,
  with the world matrix on a single `xformOp:transform`

Verified properties of that output that make the conversion mechanical:

* every mesh inside every xmodel has an **identity** local-to-world transform
  (479/479), so no per-sub-mesh offset compensation is needed
* no collection carries a non-zero `instance_offset`
* asset identity is best recovered from the **reference target basename**
  (`./xmodels/<asset>.usdc`), not from the sanitized group prim name

### Multi-mesh prototypes

72 of 276 assets contain 2–30 meshes. `#InstanceShape` selects exactly one node
per point, so a k-mesh asset must emit **k points** at the same position sharing
one transform. Scrapyard: 5,778 placements → **7,279 points**, matching the
Blender depsgraph instance count exactly. Attaching sub-meshes into single nodes
instead would force Multi/Sub materials, which do not work (above).

### Prototype import

Author one flat, **non-instanceable** stage referencing every xmodel, and import
that once — 479 meshes and 413 materials in ~6 s:

```python
stage = Usd.Stage.CreateNew(out)
UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
root = UsdGeom.Scope.Define(stage, "/Prototypes")
stage.SetDefaultPrim(root.GetPrim())
for asset in assets:
    p = UsdGeom.Xform.Define(stage, "/Prototypes/%s" % sanitize(asset))
    p.GetPrim().GetReferences().AddReference("./xmodels/%s.usdc" % asset)
    p.GetPrim().SetInstanceable(False)   # we want real geometry, not instances
```

Map imported Max nodes back to assets via the **node hierarchy** (children of
the `Prototypes` root), not by name matching — Max renames on collision and
sanitized prim names are lossy.

---

## Production fixes

### `_prototypes.usda` should be authored by the exporter

Source area: `blender/Clone_PowerUSD/operators.py`, alongside
`build_instances_usd`.

The flat prototype stage is currently generated by an external script and
written into the export folder after the fact. It is ~20 lines and derives
entirely from `asset_paths`, which `build_instances_usd` already receives.
Authoring it during export makes the Assembly Parts output self-sufficient for
any DCC that wants prototypes as real geometry rather than instances.

### Assembly Parts output should carry a manifest

Source area: `blender/Clone_PowerUSD/operators.py`, export completion.

The consumer currently re-derives facts the exporter already knows: asset →
mesh-count expansion, prototype mesh ordering, and source `metersPerUnit`.
Emitting a small JSON manifest alongside `instances.usdc` (asset list, per-asset
mesh count, instance count, unit metadata) removes an entire class of drift
between exporter and importer, and lets an importer validate its expansion
instead of trusting it.

### Unit scale should never be assumed by importers

Any DCC-side importer must measure the host's applied unit conversion rather
than trusting stage `metersPerUnit`. Max applies ×100 to a `metersPerUnit = 1.0`
stage. This failure is silent and produces a plausible-looking scene at the
wrong scale.
