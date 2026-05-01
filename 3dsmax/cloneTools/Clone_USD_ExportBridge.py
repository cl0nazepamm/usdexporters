import os
import traceback

from pxr import Sdf, Usd, UsdShade
from pymxs import runtime as mxs


def _set_result(ok, message=""):
    mxs.g_PowerUSD_PythonExportOk = bool(ok)
    mxs.g_PowerUSD_PythonExportError = str(message or "")


def _get_runtime_input(name, default=None):
    try:
        return getattr(mxs, name)
    except Exception:
        return default


def _to_max_array(items):
    items = list(items or [])
    if items:
        return mxs.Array(*items)
    return mxs.Array()


def _collect_nodes_from_handles(node_handles):
    nodes = []
    for handle in node_handles or []:
        try:
            node = mxs.getAnimByHandle(int(handle))
        except Exception:
            node = None
        if node:
            nodes.append(node)
    return nodes


def _collect_materials(nodes):
    """
    Collect the flat set of LEAF materials used by the given nodes.

    MtlXIOUtil.ExportMtlX does not know how to serialize composite materials
    like MultiSubObject or Shell — it silently drops them, leaving the .mtlx
    empty for any mesh that ships materials via face-ID submaterials. Work
    around the Autodesk limitation by recursing through any material that
    reports `getNumSubMtls > 0` and emitting each submaterial individually.
    maxUsd's preview-surface writer names preview materials by the same
    submaterial names, so the bridge's name-based MaterialX relocation still
    pairs each MTLX Material with the correct preview binding.
    """
    materials = []
    seen = set()

    def add(material):
        if not material:
            return

        try:
            key = int(mxs.getHandleByAnim(material))
        except Exception:
            key = (str(getattr(material, "name", material)),
                   str(mxs.classOf(material)))

        if key in seen:
            return
        seen.add(key)

        try:
            num_subs = int(mxs.getNumSubMtls(material))
        except Exception:
            num_subs = 0

        if num_subs > 0:
            for i in range(1, num_subs + 1):
                try:
                    sub = mxs.getSubMtl(material, i)
                except Exception:
                    sub = None
                add(sub)
            return

        materials.append(material)

    for node in nodes:
        try:
            material = node.material
        except Exception:
            material = None
        add(material)

    return materials


def _configure_export_options(start_frame, end_frame):
    options = mxs.USDExporter.CreateOptions()

    options.ContextNames = _to_max_array(["usdPropertiesContext", "cleanMaterialContextV2"])
    options.ChaserNames = _to_max_array(["cleanMaterialStructureV2"])
    options.AllMaterialConversions = _to_max_array(["UsdPreviewSurface"])
    options.UseLastResortUSDPreviewSurfaceWriter = True
    options.TranslateMaterials = True

    if start_frame is not None:
        options.StartFrame = int(start_frame)
    if end_frame is not None:
        options.EndFrame = int(end_frame)

    if start_frame is not None and end_frame is not None and int(end_frame) > int(start_frame):
        options.TimeMode = 1
        options.SamplesPerFrame = 1

    return options


def _detect_materialx(stage):
    mtlx_found = False
    asset_attrs = []

    for prim in stage.Traverse():
        for prop in prim.GetAuthoredProperties():
            prop_name = prop.GetName()
            lower_name = prop_name.lower()
            if "mtlx" in lower_name:
                mtlx_found = True

        for attr in prim.GetAuthoredAttributes():
            prop_name = attr.GetName()
            try:
                value = attr.Get()
            except Exception:
                value = None

            if prop_name == "info:id" and value:
                token_value = str(value)
                if token_value.startswith("ND_") or "mtlx" in token_value.lower():
                    mtlx_found = True

            if isinstance(value, Sdf.AssetPath):
                asset_path = value.path or ""
                if asset_path.lower().endswith(".mtlx"):
                    mtlx_found = True
                    asset_attrs.append((attr, asset_path))
            elif isinstance(value, (list, tuple)):
                paths = []
                for item in value:
                    if isinstance(item, Sdf.AssetPath) and (item.path or "").lower().endswith(".mtlx"):
                        paths.append(item.path)
                if paths:
                    mtlx_found = True
                    asset_attrs.append((attr, paths))

    return mtlx_found, asset_attrs


def _is_same_or_descendant_path(path, root_path):
    path = str(path)
    root_path = str(root_path)
    return path == root_path or path.startswith(root_path + "/")


def _is_materialx_shader_id(shader_id):
    if not shader_id:
        return False

    shader_id = str(shader_id)
    shader_id_lower = shader_id.lower()
    return (
        shader_id.startswith("ND_")
        or shader_id_lower.startswith("mtlx")
        or "materialx" in shader_id_lower
    )


def _is_safe_preview_nodegraph(nodegraph_prim):
    allowed_shader_ids = {"UsdUVTexture", "UsdPrimvarReader_float2"}
    found_texture = False

    for child in nodegraph_prim.GetChildren():
        if child.GetTypeName() == "NodeGraph":
            return False

        if not child.IsA(UsdShade.Shader):
            return False

        shader = UsdShade.Shader(child)
        shader_id = shader.GetIdAttr().Get() if shader.GetIdAttr() else None
        if _is_materialx_shader_id(shader_id):
            return False
        if shader_id not in allowed_shader_ids:
            return False
        if shader_id == "UsdUVTexture":
            found_texture = True

    return found_texture


def _has_external_reference_to_path(stage, candidate_path):
    candidate_path = str(candidate_path)

    for prim in stage.Traverse():
        source_path = str(prim.GetPath())
        if _is_same_or_descendant_path(source_path, candidate_path):
            continue

        for attr in prim.GetAuthoredAttributes():
            try:
                for conn in attr.GetConnections():
                    if _is_same_or_descendant_path(conn.GetPrimPath(), candidate_path):
                        return True
            except Exception:
                pass

        for rel in prim.GetAuthoredRelationships():
            try:
                for target in rel.GetTargets():
                    if _is_same_or_descendant_path(target.GetPrimPath(), candidate_path):
                        return True
            except Exception:
                pass

        for prim_spec in prim.GetPrimStack():
            for list_name in ("referenceList", "payloadList", "inheritPathList", "specializesList"):
                list_op = getattr(prim_spec, list_name, None)
                if not list_op:
                    continue

                for item_attr in ("prependedItems", "explicitItems", "addedItems", "appendedItems"):
                    items = getattr(list_op, item_attr, None)
                    if not items:
                        continue

                    for item in items:
                        prim_path = getattr(item, "primPath", item)
                        if prim_path and _is_same_or_descendant_path(prim_path, candidate_path):
                            return True

    return False


def _wrap_single_content_as_asset(stage):
    """
    If the root layer's defaultPrim is a single Gprim-like prim with a nested
    mtl/Looks/Materials Scope, wrap it as a proper USD asset:

        def Xform "<name>" (kind = "component") {
            def Mesh "Geom" { ... material:binding = </<name>/mtl/...> ... }
            def Scope "mtl" { def Material ... }
        }

    Runs on the reopened post-export stage where layer.Save() actually persists
    (the equivalent transform during a chaser PostExport does not persist, even
    through layer-direct APIs — likely because maxUsd serializes the export
    stage ahead of chaser edits for stage-level operations).

    Returns True if the wrap was applied.
    """
    from pxr import UsdGeom, UsdShade

    layer = stage.GetRootLayer()
    default_name = layer.defaultPrim
    if not default_name or default_name == "root":
        return False

    content_path = Sdf.Path("/" + default_name)
    content_spec = layer.GetPrimAtPath(content_path)
    if not content_spec:
        return False

    container_types = {"Xform", "Scope", "SkelRoot", "Skeleton", "Material", ""}
    if content_spec.typeName in container_types:
        return False
    if content_spec.specifier != Sdf.SpecifierDef:
        return False

    mtl_child_name = None
    for child in content_spec.nameChildren:
        if child.name in ("mtl", "Looks", "Materials") and child.typeName == "Scope":
            mtl_child_name = child.name
            break
    if not mtl_child_name:
        return False

    original_type = content_spec.typeName
    tmp_name = "__asset_wrap_tmp__"
    if layer.GetPrimAtPath(Sdf.Path("/" + tmp_name)):
        print(f"Asset wrap: /{tmp_name} already exists, skipping wrap")
        return False

    tmp_path = Sdf.Path("/" + tmp_name)
    geom_name = "Geom"
    geom_path = content_path.AppendChild(geom_name)
    mtl_final_path = content_path.AppendChild(mtl_child_name)

    rename_edit = Sdf.BatchNamespaceEdit()
    rename_edit.Add(content_path, tmp_path)
    if not layer.Apply(rename_edit):
        print(f"Asset wrap: could not rename {content_path} -> {tmp_path}")
        return False

    _remap_paths_after_move(stage, str(content_path), str(tmp_path))

    Sdf.CreatePrimInLayer(layer, content_path)
    new_spec = layer.GetPrimAtPath(content_path)
    if new_spec is None:
        print(f"Asset wrap: failed to create root spec at {content_path}")
        return False
    new_spec.specifier = Sdf.SpecifierDef
    new_spec.typeName = "Xform"
    new_spec.SetInfo("kind", "component")

    move_edit = Sdf.BatchNamespaceEdit()
    move_edit.Add(tmp_path.AppendChild(mtl_child_name), mtl_final_path)
    move_edit.Add(tmp_path, geom_path)
    if not layer.Apply(move_edit):
        print(f"Asset wrap: move step failed for {tmp_path}")
        return False

    mtl_tmp_prefix = str(tmp_path.AppendChild(mtl_child_name))
    _remap_paths_after_move(stage, mtl_tmp_prefix, str(mtl_final_path))
    _remap_paths_after_move(stage, str(tmp_path), str(geom_path))

    layer.Save()
    print(
        f"Asset wrap: /{default_name} -> def Xform (kind=component) "
        f"{{ {original_type} '{geom_name}', Scope '{mtl_child_name}' }}"
    )
    return True


def _remap_paths_after_move(stage, old_prefix, new_prefix):
    """Rewrite relationship targets and attribute connections after a move."""

    def remap(path_str):
        if path_str == old_prefix:
            return new_prefix
        if path_str.startswith(old_prefix + "/"):
            return new_prefix + path_str[len(old_prefix):]
        return None

    for prim in stage.TraverseAll():
        for rel in prim.GetRelationships():
            targets = rel.GetTargets()
            if not targets:
                continue
            new_targets = []
            changed = False
            for t in targets:
                replaced = remap(str(t))
                if replaced is not None:
                    new_targets.append(Sdf.Path(replaced))
                    changed = True
                else:
                    new_targets.append(t)
            if changed:
                rel.SetTargets(new_targets)

        for attr in prim.GetAttributes():
            conns = attr.GetConnections()
            if not conns:
                continue
            new_conns = []
            changed = False
            for c in conns:
                replaced = remap(str(c))
                if replaced is not None:
                    new_conns.append(Sdf.Path(replaced))
                    changed = True
                else:
                    new_conns.append(c)
            if changed:
                attr.SetConnections(new_conns)


def _remove_orphan_preview_nodegraphs(stage):
    nodegraphs_to_remove = []

    for prim in stage.Traverse():
        if prim.GetTypeName() != "NodeGraph":
            continue
        if _has_external_reference_to_path(stage, prim.GetPath()):
            continue
        if _is_safe_preview_nodegraph(prim):
            nodegraphs_to_remove.append(str(prim.GetPath()))

    for prim_path in nodegraphs_to_remove:
        stage.RemovePrim(prim_path)

    if nodegraphs_to_remove:
        stage.GetRootLayer().Save()
        print(f"MaterialX bridge: removed {len(nodegraphs_to_remove)} orphan preview NodeGraph(s)")

    return nodegraphs_to_remove


def _export_materialx_sidecar(usd_path, nodes):
    materials = _collect_materials(nodes)
    if not materials:
        print("MaterialX bridge: no materials found on exported nodes")
        return None

    usd_dir = os.path.dirname(usd_path)
    usd_stem = os.path.splitext(os.path.basename(usd_path))[0]
    sidecar_path = os.path.join(usd_dir, usd_stem + ".mtlx")
    temp_path = sidecar_path + ".tmp"

    os.makedirs(usd_dir, exist_ok=True)

    if os.path.exists(temp_path):
        os.remove(temp_path)

    # Default to referencing textures in place (relative paths, no copy) so
    # that exporting into a project with a shared texture library doesn't
    # duplicate bitmaps next to every USD. The bulkexporter UI exposes this
    # as a checkbox ("Reference Textures (no copy)"), and the corresponding
    # runtime var is _powerusd_reference_textures.
    reference_textures = bool(_get_runtime_input("_powerusd_reference_textures", True))

    mxs.MtlXIOUtil.SetDefaults()
    if mxs.isProperty(mxs.MtlXIOUtil, "CopyTexturesToSaveLocation"):
        mxs.MtlXIOUtil.CopyTexturesToSaveLocation = not reference_textures
    if mxs.isProperty(mxs.MtlXIOUtil, "UseRelativePaths"):
        mxs.MtlXIOUtil.UseRelativePaths = True
    if mxs.isProperty(mxs.MtlXIOUtil, "ResolveTexturePaths"):
        mxs.MtlXIOUtil.ResolveTexturePaths = True

    ok = bool(mxs.MtlXIOUtil.ExportMtlX(temp_path, _to_max_array(materials)))
    if not ok:
        err = ""
        try:
            err = mxs.MtlXIOUtil.GetError()
        except Exception:
            err = "Unknown MaterialX export error"
        raise RuntimeError(f"MaterialX sidecar export failed: {err}")

    os.replace(temp_path, sidecar_path)
    print(f"MaterialX bridge: wrote sidecar {sidecar_path}")
    return sidecar_path


def _rewrite_materialx_asset_paths(stage, asset_attrs, sidecar_path):
    if not asset_attrs:
        return False

    sidecar_name = os.path.basename(sidecar_path)
    changed = False

    for attr, value in asset_attrs:
        if isinstance(value, str):
            if value != sidecar_name:
                attr.Set(Sdf.AssetPath(sidecar_name))
                changed = True
        elif isinstance(value, (list, tuple)):
            new_values = []
            local_change = False
            for item in value:
                if str(item) != sidecar_name:
                    local_change = True
                new_values.append(Sdf.AssetPath(sidecar_name))
            if local_change:
                attr.Set(new_values)
                changed = True

    if changed:
        stage.GetRootLayer().Save()
        print(f"MaterialX bridge: repathed USD MaterialX assets to {sidecar_name}")

    return changed


def _remap_layer_paths_prefix(usd_layer, old_prefix, new_prefix):
    """
    Walk every prim spec in the layer and rewrite any relationship target,
    attribute connection, or references-list asset path whose path starts with
    old_prefix so it points at new_prefix instead. Operates purely on Sdf
    layer specs so the edits persist on layer.Save().
    """
    def remap_path(path):
        s = str(path)
        if s == old_prefix:
            return Sdf.Path(new_prefix)
        if s.startswith(old_prefix + "/") or s.startswith(old_prefix + "."):
            return Sdf.Path(new_prefix + s[len(old_prefix):])
        return None

    def visit(prim_spec):
        for rel_spec in prim_spec.relationships:
            for key in ("targetPathList",):
                path_list = getattr(rel_spec, key, None)
                if path_list is None:
                    continue
                for attr in ("explicitItems", "addedItems", "prependedItems",
                             "appendedItems", "deletedItems", "orderedItems"):
                    items = list(getattr(path_list, attr, []))
                    changed = False
                    for i, p in enumerate(items):
                        replaced = remap_path(p)
                        if replaced is not None:
                            items[i] = replaced
                            changed = True
                    if changed:
                        getattr(path_list, attr)[:] = items
        for attr_spec in prim_spec.attributes:
            path_list = attr_spec.connectionPathList
            for attr in ("explicitItems", "addedItems", "prependedItems",
                         "appendedItems", "deletedItems", "orderedItems"):
                items = list(getattr(path_list, attr, []))
                changed = False
                for i, p in enumerate(items):
                    replaced = remap_path(p)
                    if replaced is not None:
                        items[i] = replaced
                        changed = True
                if changed:
                    getattr(path_list, attr)[:] = items
        for child in prim_spec.nameChildren:
            visit(child)

    for root in usd_layer.rootPrims:
        visit(root)


def _collect_material_binding_targets(usd_layer):
    """
    Walk every relationship spec in the layer and return a map
    {material_basename: Sdf.Path} of every path that a material:binding points
    at, skipping anything inside /MaterialX. Used to discover where maxUsd
    actually placed the preview material scope so the MaterialX relocation
    can target the exact path the meshes are already bound to.

    For single-object exports maxUsd nests the scope at /<asset>/mtl/, but for
    multi-object exports (two or more top-level meshes) the scope is shared
    at the root as /mtl/, so a defaultPrim-based assumption is wrong.
    """
    targets = {}

    def visit(prim_spec):
        for rel_spec in prim_spec.relationships:
            if rel_spec.name != "material:binding":
                continue
            path_list = rel_spec.targetPathList
            for attr in ("explicitItems", "prependedItems", "appendedItems",
                         "addedItems", "orderedItems"):
                for target in getattr(path_list, attr, []):
                    p = Sdf.Path(target)
                    if str(p).startswith("/MaterialX"):
                        continue
                    targets[p.name] = p
        for child in prim_spec.nameChildren:
            visit(child)

    for root in usd_layer.rootPrims:
        if root.name == "MaterialX":
            continue
        visit(root)
    return targets


def _relocate_materialx_under_asset(usd_layer):
    """
    After Sdf.CopySpec brings /MaterialX into the USD layer, the MaterialX
    Materials live at /MaterialX/Materials/<Name> but the meshes are bound to
    preview materials elsewhere in the layer (a UsdPreviewSurface-only
    Material emitted by maxUsd). Move each MaterialX Material onto the bound
    path so the existing material:binding relationships resolve to real
    MaterialX.

    The target path is discovered from live material:binding relationships,
    not assumed — maxUsd uses /<asset>/mtl/<N> for single-object exports and
    /mtl/<N> (shared scope at root) for multi-object exports.

    /MaterialX/Shaders and /MaterialX/NodeGraphs stay in place — the moved
    Material's child Shader/NodeGraph specs reference them via
    `prepend references = </MaterialX/Shaders/...>`, so removing them would
    strip the authoritative MaterialX definitions.

    BatchNamespaceEdit's docs claim it auto-remaps within-subtree connection
    paths, but in practice on material subtrees containing referenced
    child shaders it does not — so we remap manually after the move.
    """
    mtlx_materials_path = Sdf.Path("/MaterialX/Materials")
    mtlx_materials_spec = usd_layer.GetPrimAtPath(mtlx_materials_path)
    if mtlx_materials_spec is None:
        return

    binding_targets = _collect_material_binding_targets(usd_layer)

    default_name = usd_layer.defaultPrim
    fallback_mtl_path = None
    if default_name:
        fallback_mtl_path = Sdf.Path("/" + default_name + "/mtl")

    moves = []
    edit = Sdf.BatchNamespaceEdit()
    for mat_spec in list(mtlx_materials_spec.nameChildren):
        mat_name = mat_spec.name
        src = mtlx_materials_path.AppendChild(mat_name)
        dst = binding_targets.get(mat_name)
        if dst is None:
            if fallback_mtl_path is None:
                print(f"MaterialX bridge: no binding target and no defaultPrim "
                      f"for {src}, skipping relocation")
                continue
            if usd_layer.GetPrimAtPath(fallback_mtl_path) is None:
                scope_spec = Sdf.CreatePrimInLayer(usd_layer, fallback_mtl_path)
                scope_spec.specifier = Sdf.SpecifierDef
                scope_spec.typeName = "Scope"
            dst = fallback_mtl_path.AppendChild(mat_name)
        existing = usd_layer.GetPrimAtPath(dst)
        if existing is not None:
            edit.Add(dst, Sdf.Path.emptyPath)
        edit.Add(src, dst)
        moves.append((str(src), str(dst)))

    if not usd_layer.Apply(edit):
        print("MaterialX bridge: namespace edit to relocate MaterialX materials failed")
        return

    for old_prefix, new_prefix in moves:
        _remap_layer_paths_prefix(usd_layer, old_prefix, new_prefix)

    empty_materials = usd_layer.GetPrimAtPath(mtlx_materials_path)
    if empty_materials is not None and not list(empty_materials.nameChildren):
        del usd_layer.GetPrimAtPath(Sdf.Path("/MaterialX")).nameChildren["Materials"]


def _inline_materialx_into_usd(usd_path, sidecar_path):
    """
    Inline MaterialX content into the USD layer by deep-copying specs from
    the .mtlx layer directly via Sdf.CopySpec. The previous implementation
    used Usd.Stage.Flatten() + Export(), but flattening a stage with an
    MTLX-plugin-loaded layer corrupts the exported USDC (values come back as
    empty VtValue on read). CopySpec sidesteps the composition engine
    entirely — it just copies layer specs, which is what "inline" really
    means.
    """
    if not sidecar_path or not os.path.exists(sidecar_path):
        raise RuntimeError("MaterialX inline requested, but no sidecar file was written")

    usd_layer = Sdf.Layer.FindOrOpen(usd_path)
    if usd_layer is None:
        raise RuntimeError(f"Failed to open USD layer for MaterialX inline: {usd_path}")

    mtlx_layer = Sdf.Layer.FindOrOpen(sidecar_path)
    if mtlx_layer is None:
        raise RuntimeError(f"Failed to open MTLX layer for inline: {sidecar_path}")

    mtlx_root_path = Sdf.Path("/MaterialX")
    mtlx_root_spec = mtlx_layer.GetPrimAtPath(mtlx_root_path)
    if mtlx_root_spec is None:
        raise RuntimeError(
            f"MTLX layer {sidecar_path} does not expose a /MaterialX root prim"
        )

    if usd_layer.GetPrimAtPath(mtlx_root_path):
        del usd_layer.rootPrims["MaterialX"]

    Sdf.CreatePrimInLayer(usd_layer, mtlx_root_path)
    if not Sdf.CopySpec(mtlx_layer, mtlx_root_path, usd_layer, mtlx_root_path):
        raise RuntimeError(
            f"Sdf.CopySpec failed to inline {mtlx_root_path} from {sidecar_path}"
        )

    _relocate_materialx_under_asset(usd_layer)

    usd_layer.Save()
    usd_layer = None
    mtlx_layer = None

    try:
        os.remove(sidecar_path)
        print(f"MaterialX bridge: inlined MaterialX into {usd_path} and removed {sidecar_path}")
    except OSError:
        print(f"MaterialX bridge: inlined MaterialX into {usd_path} (temporary sidecar kept: {sidecar_path})")

    return True


def _postprocess_existing_usd(usd_path, nodes, force_materialx_sidecar,
                              inline_materialx_into_usd):
    """
    Shared post-export pipeline: wrap single-content assets, optionally
    export a MaterialX sidecar, optionally inline MaterialX into the USD.

    Used by both the bridge-native export path (export_powerusd_asset) and
    the post-process entry point for files written by the legacy maxUsd
    exportFile path (postprocess_powerusd_usd). Expects the .usd already
    exists on disk; opens it, mutates, saves.
    """
    # USDExporter writes the fresh file to disk, but a previously cached
    # Sdf.Layer at the same path (for example from a prior corrupt-state run
    # that was explicitly cleared) can short-circuit FindOrOpen and yield an
    # empty in-memory layer — even though the on-disk bytes are correct.
    # Force a reload so the post-export stage reflects what was just written.
    existing_layer = Sdf.Layer.Find(usd_path)
    if existing_layer is not None:
        existing_layer.Reload(force=True)

    stage = Usd.Stage.Open(usd_path)
    if stage is None:
        raise RuntimeError(f"Failed to open exported USD stage: {usd_path}")

    _remove_orphan_preview_nodegraphs(stage)
    _wrap_single_content_as_asset(stage)

    has_materialx, asset_attrs = _detect_materialx(stage)
    sidecar_path = None
    if has_materialx or force_materialx_sidecar or inline_materialx_into_usd:
        sidecar_path = _export_materialx_sidecar(usd_path, nodes)
        if sidecar_path and has_materialx:
            _rewrite_materialx_asset_paths(stage, asset_attrs, sidecar_path)
    else:
        print("MaterialX bridge: no MaterialX found in USD, skipping sidecar export")

    # MtlXIOUtil returns False (sidecar_path = None) when nothing MaterialX
    # is present; in that case the inline step is a no-op and the USD is left
    # as plain UsdPreviewSurface, which is the desired fallback.
    if inline_materialx_into_usd and sidecar_path is not None:
        _inline_materialx_into_usd(usd_path, sidecar_path)


def export_powerusd_asset():
    usd_path = _get_runtime_input("_powerusd_export_path", "")
    node_handles = _get_runtime_input("_powerusd_export_node_handles", [])
    start_frame = _get_runtime_input("_powerusd_export_start_frame", None)
    end_frame = _get_runtime_input("_powerusd_export_end_frame", None)
    force_materialx_sidecar = bool(_get_runtime_input("_powerusd_force_materialx_sidecar", False))
    inline_materialx_into_usd = bool(_get_runtime_input("_powerusd_inline_materialx_into_usd", False))

    if not usd_path:
        raise RuntimeError("Missing _powerusd_export_path")

    nodes = _collect_nodes_from_handles(node_handles)
    if not nodes:
        raise RuntimeError("No valid nodes were provided for USD export")

    os.makedirs(os.path.dirname(usd_path), exist_ok=True)

    options = _configure_export_options(start_frame, end_frame)
    ok = bool(
        mxs.USDExporter.ExportFile(
            usd_path,
            exportOptions=options,
            contentSource=mxs.Name("nodeList"),
            nodeList=_to_max_array(nodes),
        )
    )
    if not ok:
        raise RuntimeError("USDExporter.ExportFile returned false")

    _postprocess_existing_usd(
        usd_path, nodes, force_materialx_sidecar, inline_materialx_into_usd
    )
    return True


def postprocess_powerusd_usd():
    """
    Entry point for post-processing a USD that was already written by the
    legacy maxUsd exportFile path (used by powerusd.ms whole-scene export).
    Runs the same wrap/sidecar/inline pipeline as the bridge export path
    against the existing file in place. Does not re-export.
    """
    usd_path = _get_runtime_input("_powerusd_export_path", "")
    node_handles = _get_runtime_input("_powerusd_export_node_handles", [])
    force_materialx_sidecar = bool(_get_runtime_input("_powerusd_force_materialx_sidecar", False))
    inline_materialx_into_usd = bool(_get_runtime_input("_powerusd_inline_materialx_into_usd", False))

    if not usd_path:
        raise RuntimeError("Missing _powerusd_export_path")
    if not os.path.exists(usd_path):
        raise RuntimeError(f"USD file not found for post-process: {usd_path}")

    nodes = _collect_nodes_from_handles(node_handles)
    # An empty node list means we can't produce a MaterialX sidecar (no mats
    # to enumerate); the wrap step still runs.
    _postprocess_existing_usd(
        usd_path, nodes, force_materialx_sidecar, inline_materialx_into_usd
    )
    return True


_mode = str(_get_runtime_input("_powerusd_bridge_mode", "export") or "export").strip()

try:
    if _mode == "postprocess":
        postprocess_powerusd_usd()
    else:
        export_powerusd_asset()
    _set_result(True, "")
except Exception as exc:
    message = f"{exc}\n{traceback.format_exc()}"
    print(f"PowerUSD export bridge ERROR: {message}")
    _set_result(False, message)
