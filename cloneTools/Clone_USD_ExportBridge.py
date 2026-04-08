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
    materials = []
    seen = set()

    for node in nodes:
        try:
            material = node.material
        except Exception:
            material = None
        if not material:
            continue

        try:
            key = int(mxs.getHandleByAnim(material))
        except Exception:
            key = (str(getattr(material, "name", material)), str(mxs.classOf(material)))

        if key in seen:
            continue

        seen.add(key)
        materials.append(material)

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

    mxs.MtlXIOUtil.SetDefaults()
    if mxs.isProperty(mxs.MtlXIOUtil, "CopyTexturesToSaveLocation"):
        mxs.MtlXIOUtil.CopyTexturesToSaveLocation = True
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


def _inline_materialx_into_usd(usd_path, sidecar_path):
    if not sidecar_path or not os.path.exists(sidecar_path):
        raise RuntimeError("MaterialX inline requested, but no sidecar file was written")

    stage = Usd.Stage.Open(usd_path)
    if stage is None:
        raise RuntimeError(f"Failed to reopen USD stage for MaterialX inline: {usd_path}")

    local_root_path = Sdf.Path("/MaterialX")
    local_root = stage.GetPrimAtPath(local_root_path)
    if local_root and local_root.IsValid():
        stage.RemovePrim(local_root_path)

    local_root = stage.DefinePrim(local_root_path, "Scope")
    refs = local_root.GetReferences()
    refs.AddReference(os.path.basename(sidecar_path), "/MaterialX")
    stage.GetRootLayer().Save()

    flattened = stage.Flatten()
    flattened.Export(usd_path)
    stage = None

    try:
        os.remove(sidecar_path)
        print(f"MaterialX bridge: inlined MaterialX into {usd_path} and removed {sidecar_path}")
    except OSError:
        print(f"MaterialX bridge: inlined MaterialX into {usd_path} (temporary sidecar kept: {sidecar_path})")

    return True


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

    stage = Usd.Stage.Open(usd_path)
    if stage is None:
        raise RuntimeError(f"Failed to open exported USD stage: {usd_path}")

    _remove_orphan_preview_nodegraphs(stage)

    has_materialx, asset_attrs = _detect_materialx(stage)
    sidecar_path = None
    if has_materialx or force_materialx_sidecar or inline_materialx_into_usd:
        sidecar_path = _export_materialx_sidecar(usd_path, nodes)
        if sidecar_path and has_materialx:
            _rewrite_materialx_asset_paths(stage, asset_attrs, sidecar_path)
    else:
        print("MaterialX bridge: no MaterialX found in USD, skipping sidecar export")

    if inline_materialx_into_usd:
        _inline_materialx_into_usd(usd_path, sidecar_path)

    return True


try:
    export_powerusd_asset()
    _set_result(True, "")
except Exception as exc:
    message = f"{exc}\n{traceback.format_exc()}"
    print(f"PowerUSD export bridge ERROR: {message}")
    _set_result(False, message)
