import os
import re
import traceback

import maxUsd
from pymxs import runtime as mxs


class MaterialXSidecarChaser(maxUsd.ExportChaser):
    """
    Export a sidecar MaterialX document next to each USD asset export.

    3ds Max's USD export does not author MaterialX automatically, so this
    chaser collects the materials used by the exported nodes and calls the
    built-in MtlXIOUtil exporter after the USD file has been written.
    """

    def __init__(self, factoryContext, *args, **kwargs):
        super(MaterialXSidecarChaser, self).__init__(factoryContext, *args, **kwargs)
        self.stage = factoryContext.GetStage()
        self.primsToNodeHandles = factoryContext.GetPrimsToNodeHandles()

    def _get_export_file_path(self):
        """Best-effort resolution of the current USD file path."""
        layer = self.stage.GetRootLayer()
        candidates = [
            getattr(layer, "realPath", ""),
            getattr(layer, "identifier", ""),
        ]

        for candidate in candidates:
            if not candidate:
                continue
            path = str(candidate).strip()
            if not path or path.startswith("anon:"):
                continue
            if path.startswith("@") and path.endswith("@"):
                path = path[1:-1]
            return os.path.abspath(path)

        return None

    def _sanitize_file_stem(self, value):
        """Make a safe sidecar filename stem."""
        value = str(value).strip()
        value = re.sub(r'[<>:"/\\|?*]+', "_", value)
        value = value.rstrip(". ")
        return value or "materialx"

    def _collect_export_materials(self):
        """Collect unique top-level materials from exported nodes."""
        materials = []
        seen = set()

        for _, node_handle in self.primsToNodeHandles.items():
            try:
                node = mxs.maxOps.getNodeByHandle(node_handle)
            except Exception:
                node = None
            if not node:
                continue

            material = None
            try:
                material = node.material
            except Exception:
                material = None

            if not material:
                continue

            try:
                key = int(mxs.getHandleByAnim(material))
            except Exception:
                key = None

            if key is None:
                try:
                    key = (str(material.name), str(mxs.classOf(material)))
                except Exception:
                    key = str(material)

            if key in seen:
                continue

            seen.add(key)
            materials.append(material)

        return materials

    def _export_materialx_sidecar(self, sidecar_path, materials):
        """Run MtlXIOUtil with exporter-owned settings."""
        mxs.MtlXIOUtil.SetDefaults()
        mxs.MtlXIOUtil.CopyTexturesToSaveLocation = True
        mxs.MtlXIOUtil.UseRelativePaths = True
        mxs.MtlXIOUtil.ResolveTexturePaths = True

        material_array = mxs.Array()
        for material in materials:
            material_array.append(material)

        return bool(mxs.MtlXIOUtil.ExportMtlX(sidecar_path, material_array))

    def PostExport(self):
        try:
            export_path = self._get_export_file_path()
            if not export_path:
                print("MaterialX sidecar: could not resolve export path, skipping")
                return True

            materials = self._collect_export_materials()
            if not materials:
                print("MaterialX sidecar: no exported materials found, skipping")
                return True

            export_dir = os.path.dirname(export_path)
            export_stem = self._sanitize_file_stem(os.path.splitext(os.path.basename(export_path))[0])
            sidecar_path = os.path.join(export_dir, export_stem + ".mtlx")

            os.makedirs(export_dir, exist_ok=True)

            material_names = []
            for material in materials:
                try:
                    material_names.append(str(material.name))
                except Exception:
                    material_names.append(str(material))
            print(f"MaterialX sidecar: exporting {len(materials)} material(s) -> {sidecar_path}")
            print(f"MaterialX sidecar: {', '.join(material_names)}")

            ok = self._export_materialx_sidecar(sidecar_path, materials)
            if not ok:
                print(f"MaterialX sidecar ERROR: {mxs.MtlXIOUtil.GetError()}")
            else:
                print("MaterialX sidecar export completed successfully.")

        except Exception as e:
            print(f"MaterialX sidecar ERROR: {e}")
            print(traceback.format_exc())

        return True


maxUsd.ExportChaser.Register(
    MaterialXSidecarChaser,
    "exportMaterialXSidecar",
    "Export MaterialX Sidecar",
    "Exports a sidecar .mtlx next to the USD asset using 3ds Max's MtlXIOUtil."
)


def materialXSidecarContext():
    return {
        "chaser": ["exportMaterialXSidecar"],
        "chaserNames": ["exportMaterialXSidecar"]
    }


registeredContexts = maxUsd.JobContextRegistry.ListJobContexts()
if "materialXSidecarContext" not in registeredContexts:
    maxUsd.JobContextRegistry.RegisterExportJobContext(
        "materialXSidecarContext",
        "Export MaterialX Sidecar",
        "Writes a sidecar .mtlx next to each exported USD asset",
        materialXSidecarContext
    )

print("Registered MaterialX sidecar chaser")
