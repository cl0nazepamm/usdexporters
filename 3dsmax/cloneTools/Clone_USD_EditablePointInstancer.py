"""
Clone_USD_EditablePointInstancer
================================

Converts a PowerUSD "Assembly Parts" export into 3ds Max 2027.2 native
`Editable_Point` instances.

Consumes:
    <export>/xmodels/<asset>.usdc   per-asset prototype geometry + materials
    <export>/instances.usdc         one instanceable Xform per placement

Produces:
    N hidden Editable_Poly prototype nodes (one per prototype MESH)
    1 Editable_Point carrying one point per (placement x prototype sub-mesh),
      driving #InstanceShape (I32) and #Transform (Matrix3)

Reference numbers, Scrapyard (MW2): 276 assets / 479 prototype meshes /
5,778 placements -> 7,279 points in a single node, 0.8 ms/redraw.

See docs/3dsmax_editable_point_instancing.md for the full behavioural notes.
Requires 3ds Max 2027.2+ (Editable_Point) and the USD for 3ds Max plugin,
which supplies `pxr` to Max's Python.

Usage inside 3ds Max:

    import Clone_USD_EditablePointInstancer as epi
    epi.build(r"D:/exports/my_level_assembly")

MATERIALS -- READ BEFORE CHANGING
---------------------------------
Editable_Point carries prototype material/texture data correctly (collapsing an
EP to Editable Poly yields textured geometry), but the 2027.2 viewport does not
shade instances, so they display flat. Therefore this tool deliberately leaves
`ep.material` UNDEFINED: anything assigned there overrides every instance and
destroys the per-prototype data a later collapse depends on.

Do not "fix" the flat display with any of these -- all tested and failed:
  * Multi/Sub-Object on the EP renders black (3 and 479 slots, correct face
    MatIDs, both MaxUsdPreviewSurface and PhysicalMaterial sub-materials)
  * Material_Switcher applies its single active .selection to every instance
  * #MaterialColor / #MaterialFlags have no observable viewport effect
    (#Color does tint, but flat colour only -- no textures)
"""

import os
import re
import time

import pymxs
from pymxs import runtime as rt

__all__ = ["build", "author_prototype_stage"]

PROTO_STAGE_NAME = "_prototypes.usda"
PROTO_ROOT = "Prototypes"


# ----------------------------------------------------------------- helpers ---
def _sanitize(name):
    """Mirror of Clone_PowerUSD.usd_sanitize_identifier."""
    s = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not s or s[0].isdigit():
        s = "_" + s
    return s


def _asset_from_reference(prim):
    """Asset identity comes from the reference target basename, which is
    authoritative -- sanitized group prim names are lossy."""
    refs = prim.GetMetadata("references")
    if not refs:
        return None
    items = list(getattr(refs, "prependedItems", []) or []) + \
            list(getattr(refs, "addedItems", []) or [])
    if not items:
        return None
    return os.path.splitext(os.path.basename(items[0].assetPath))[0]


def _geometry_descendants(node):
    out, stack = [], list(node.children)
    while stack:
        c = stack.pop()
        if rt.superClassOf(c) == rt.GeometryClass:
            out.append(c)
        stack.extend(list(c.children))
    return out


# --------------------------------------------------------- prototype stage ---
def author_prototype_stage(export_dir, force=False):
    """Author a flat, NON-instanceable stage referencing every xmodel, so Max
    imports real geometry (and real materials) in one operation.

    Ideally the Blender exporter emits this during export -- see the production
    fix note in docs/3dsmax_editable_point_instancing.md.
    """
    from pxr import Usd, UsdGeom

    out = os.path.join(export_dir, PROTO_STAGE_NAME)
    if os.path.isfile(out) and not force:
        return out

    xdir = os.path.join(export_dir, "xmodels")
    assets = sorted(
        os.path.splitext(f)[0]
        for f in os.listdir(xdir)
        if f.endswith(".usdc") and not f.startswith("__")
    )

    stage = Usd.Stage.CreateNew(out)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    root = UsdGeom.Scope.Define(stage, "/%s" % PROTO_ROOT)
    stage.SetDefaultPrim(root.GetPrim())

    for asset in assets:
        p = UsdGeom.Xform.Define(stage, "/%s/%s" % (PROTO_ROOT, _sanitize(asset)))
        p.GetPrim().GetReferences().AddReference("./xmodels/%s.usdc" % asset)
        p.GetPrim().SetInstanceable(False)

    stage.GetRootLayer().Save()
    return out


def _import_prototypes(proto_stage):
    root = rt.getNodeByName(PROTO_ROOT)
    if root is not None:
        return root
    rt.importFile(proto_stage, rt.Name("noPrompt"), using=rt.USDImporter)
    root = rt.getNodeByName(PROTO_ROOT)
    if root is None:
        raise RuntimeError("USD import produced no '%s' root" % PROTO_ROOT)
    return root


def _collect_prototypes(root, proto_stage):
    """asset -> [geometry nodes], resolved through the node HIERARCHY rather
    than by name, because Max renames on collision."""
    from pxr import Usd

    stage = Usd.Stage.Open(proto_stage)
    rev = {}
    for prim in stage.GetPrimAtPath("/%s" % PROTO_ROOT).GetChildren():
        rev[prim.GetName()] = _asset_from_reference(prim) or prim.GetName()

    mapping = {}
    for child in root.children:
        asset = rev.get(child.name)
        if asset is None:
            continue
        geo = _geometry_descendants(child)
        geo.sort(key=lambda o: o.name)          # reproducible shape indices
        if geo:
            mapping[asset] = geo
    return mapping


def _measure_unit_scale(mapping, proto_stage):
    """Derive the unit conversion Max's USD importer actually applied.

    Max applies x100 to a metersPerUnit=1.0 stage. Assuming 1.0 silently places
    the scene at 1/100 scale with no error, so this is measured, never assumed.
    """
    from pxr import Usd, UsdGeom

    stage = Usd.Stage.Open(proto_stage)
    for asset, nodes in mapping.items():
        node = nodes[0]
        span_max = max(node.max.x - node.min.x,
                       node.max.y - node.min.y,
                       node.max.z - node.min.z)
        if span_max < 1e-6:
            continue
        prim = stage.GetPrimAtPath("/%s/%s" % (PROTO_ROOT, _sanitize(asset)))
        if not prim or not prim.IsValid():
            continue
        span_usd = 0.0
        for d in Usd.PrimRange(prim):
            if d.GetTypeName() != "Mesh":
                continue
            ext = UsdGeom.Boundable(d).GetExtentAttr().Get()
            if ext:
                span_usd = max(span_usd, max(ext[1][i] - ext[0][i] for i in range(3)))
        if span_usd > 1e-6:
            return span_max / span_usd
    return 1.0


def _read_instances(instances_usd):
    """[(asset, Gf.Matrix4d), ...] from instances.usdc."""
    from pxr import Usd, UsdGeom

    stage = Usd.Stage.Open(instances_usd)
    rows = []
    for prim in stage.Traverse():
        if not prim.IsInstanceable():
            continue
        asset = _asset_from_reference(prim)
        if asset is None:
            continue
        ops = UsdGeom.Xformable(prim).GetOrderedXformOps()
        if ops:
            rows.append((asset, ops[0].Get()))
    return rows


# ------------------------------------------------------------------- build ---
def build(export_dir, ep_name="EP_Instances", proto_layer="EP_Prototypes",
          hide_prototypes=True, verbose=True):
    """Build a single Editable_Point from a PowerUSD Assembly Parts export.

    Returns dict of stats.
    """
    t_all = time.time()
    instances_usd = os.path.join(export_dir, "instances.usdc")
    if not os.path.isfile(instances_usd):
        raise RuntimeError("no instances.usdc in %r -- not an Assembly Parts "
                           "export?" % export_dir)

    proto_stage = author_prototype_stage(export_dir)
    root = _import_prototypes(proto_stage)
    mapping = _collect_prototypes(root, proto_stage)
    scale = _measure_unit_scale(mapping, proto_stage)
    rows = _read_instances(instances_usd)

    for o in [x for x in rt.objects if rt.classOf(x) == rt.Editable_Point]:
        rt.delete(o)

    ep = rt.Editable_Point(name=ep_name)
    b = ep.baseObject

    # register prototype meshes; shape index is position in this list
    shape_of = {}
    for asset in sorted(mapping.keys()):
        for node in mapping[asset]:
            shape_of[(asset, node.name)] = \
                b.AddInstanceNode(node, pymxs.byref(None))[1]

    shape_ch = b.AddStandardChannel(rt.Name("InstanceShape"), pymxs.byref(None))[1]
    tm_ch = b.AddStandardChannel(rt.Name("Transform"), pymxs.byref(None))[1]

    # A k-mesh asset emits k points at one position sharing one transform,
    # because #InstanceShape selects exactly one node per point.
    positions, shapes, transforms = [], [], []
    unknown = {}
    for asset, m in rows:
        nodes = mapping.get(asset)
        if not nodes:
            unknown[asset] = unknown.get(asset, 0) + 1
            continue
        # USD Gf.Matrix4d is row-major with translation in row 3 -- identical
        # to Max matrix3. Rows 0-2 are dimensionless, so only translation is
        # unit-scaled; the prototype geometry already carries the scale.
        pos = rt.Point3(m[3][0] * scale, m[3][1] * scale, m[3][2] * scale)
        basis = rt.Matrix3(rt.Point3(m[0][0], m[0][1], m[0][2]),
                           rt.Point3(m[1][0], m[1][1], m[1][2]),
                           rt.Point3(m[2][0], m[2][1], m[2][2]),
                           rt.Point3(0, 0, 0))
        for node in nodes:
            positions.append(pos)
            shapes.append(shape_of[(asset, node.name)])
            transforms.append(basis)

    ids = b.AddPoints(positions, pymxs.byref([]))[1]
    b.SetChannelValues(shape_ch, ids, shapes)
    b.SetChannelValues(tm_ch, ids, transforms)

    # NOTE: ep.material is intentionally left undefined -- see module docstring.
    ep.instanceDisplay = True
    ep.instanceDisplayType = 1          # 0 = bbox proxy, 1 = geometry, 2 = dots
    ep.displayLimit = len(positions)
    ep.displayPoints = False

    if hide_prototypes:
        layer = rt.LayerManager.getLayerFromName(proto_layer) \
            or rt.LayerManager.newLayerFromName(proto_layer)
        stack = [root]
        while stack:
            c = stack.pop()
            layer.addNode(c)
            stack.extend(list(c.children))
        layer.ishidden = True

    rt.redrawViews()

    stats = {
        "assets": len(mapping),
        "prototype_meshes": sum(len(v) for v in mapping.values()),
        "placements": len(rows),
        "points": len(positions),
        "unit_scale": scale,
        "unknown_assets": unknown,
        "seconds": time.time() - t_all,
    }
    if verbose:
        print("[EditablePointInstancer] %d assets / %d prototype meshes / "
              "%d placements -> %d points (scale %.4f) in %.1fs"
              % (stats["assets"], stats["prototype_meshes"], stats["placements"],
                 stats["points"], stats["unit_scale"], stats["seconds"]))
        if unknown:
            print("[EditablePointInstancer] WARNING: %d placements referenced "
                  "unknown assets: %s"
                  % (sum(unknown.values()), list(unknown.items())[:5]))
    return stats
