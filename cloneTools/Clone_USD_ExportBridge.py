import os
import traceback

from pxr import Sdf, Usd
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

    options.ContextNames = _to_max_array(["usdPropertiesContext"])
    options.ChaserNames = _to_max_array(["cleanMaterialStructure"])
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


def export_powerusd_asset():
    usd_path = _get_runtime_input("_powerusd_export_path", "")
    node_handles = _get_runtime_input("_powerusd_export_node_handles", [])
    start_frame = _get_runtime_input("_powerusd_export_start_frame", None)
    end_frame = _get_runtime_input("_powerusd_export_end_frame", None)

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

    has_materialx, asset_attrs = _detect_materialx(stage)
    if has_materialx:
        sidecar_path = _export_materialx_sidecar(usd_path, nodes)
        if sidecar_path:
            _rewrite_materialx_asset_paths(stage, asset_attrs, sidecar_path)
    else:
        print("MaterialX bridge: no MaterialX found in USD, skipping sidecar export")

    return True


try:
    export_powerusd_asset()
    _set_result(True, "")
except Exception as exc:
    message = f"{exc}\n{traceback.format_exc()}"
    print(f"PowerUSD export bridge ERROR: {message}")
    _set_result(False, message)
