import bpy
import os
from pathlib import Path
import shutil
import zipfile

from bpy.types import Operator
from . import utils


def filter_operator_options(operator, options):
    category, name = operator.split(".", 1)
    op = getattr(getattr(bpy.ops, category), name)
    valid_options = {
        prop.identifier
        for prop in op.get_rna_type().properties
        if prop.identifier != "rna_type"
    }

    filtered = {key: value for key, value in options.items() if key in valid_options}
    removed = sorted(set(options) - valid_options)
    if removed:
        print(
            "Ignoring unsupported "
            + operator
            + " option(s): "
            + ", ".join(removed)
        )
    return filtered


def get_hierarchy_root(obj):
    """Find the absolute root of an object's hierarchy by walking up through all parents."""
    current = obj
    while current.parent is not None:
        current = current.parent
    return current


def get_all_descendants(root):
    """Recursively collect all descendants of a node (including the root itself)."""
    descendants = [root]
    for child in root.children:
        descendants.extend(get_all_descendants(child))
    return descendants


def get_collection_objects_recursive(collection):
    objects = set(collection.objects)
    for child in collection.children:
        objects.update(get_collection_objects_recursive(child))
    return objects


def object_has_supported_geometry(obj):
    return obj and obj.type in {'MESH', 'CURVE', 'SURFACE', 'META', 'FONT'}


def make_realized_mesh_object(context, source_obj, matrix_world, temp_collection, name_prefix):
    depsgraph = context.evaluated_depsgraph_get()
    evaluated_obj = source_obj.evaluated_get(depsgraph)

    try:
        mesh = bpy.data.meshes.new_from_object(
            evaluated_obj, depsgraph=depsgraph, preserve_all_data_layers=True)
    except TypeError:
        mesh = bpy.data.meshes.new_from_object(evaluated_obj, depsgraph=depsgraph)
    except RuntimeError as exc:
        print(f"Skipping instance realization for {source_obj.name}: {exc}")
        return None

    realized = bpy.data.objects.new(name_prefix + bpy.path.clean_name(source_obj.name), mesh)
    realized.matrix_world = matrix_world
    for slot in getattr(source_obj, "material_slots", []):
        if slot.material:
            realized.data.materials.append(slot.material)
    temp_collection.objects.link(realized)
    return realized


def _add_object_materials(obj, materials):
    material_slots = getattr(obj, "material_slots", None)
    if material_slots:
        for slot in material_slots:
            if slot.material:
                materials.add(slot.material)

    obj_data = getattr(obj, "data", None)
    data_materials = getattr(obj_data, "materials", None)
    if data_materials:
        for material in data_materials:
            if material:
                materials.add(material)


def collect_object_materials(objects):
    """Collect every material referenced by ``objects`` AND by any
    collection-instance prototype they reference.

    Collection-instance empties contribute their entire prototype subgraph
    to Blender's USD export, so the plugin must walk those prototypes too.
    Otherwise textures and material wiring for instanced game models are
    silently skipped."""
    materials = set()
    seen_collections = set()

    def expand_collection(collection):
        cid = id(collection)
        if cid in seen_collections:
            return
        seen_collections.add(cid)
        for child_obj in collection.all_objects:
            _add_object_materials(child_obj, materials)

    for obj in objects:
        _add_object_materials(obj, materials)
        if getattr(obj, "instance_type", 'NONE') == 'COLLECTION':
            collection = getattr(obj, "instance_collection", None)
            if collection is not None:
                expand_collection(collection)
    return materials


def iter_material_image_texture_nodes(material):
    """Yield ``(node, image)`` for every image-texture node in the material,
    recursing into nested ``ShaderNodeGroup`` trees so textures wired through
    a custom node group are still discoverable.

    Many DCC importers (CoD asset pipelines, Substance, etc.) place the
    actual UsdPreviewSurface inputs inside a node group. Without this
    recursion we'd miss every such material and Blender's USD export would
    write empty UsdPreviewSurface networks."""
    if not material.use_nodes or not material.node_tree:
        return
    visited = set()
    stack = [material.node_tree]
    while stack:
        tree = stack.pop()
        if tree is None or id(tree) in visited:
            continue
        visited.add(id(tree))
        for node in tree.nodes:
            if node.bl_idname == "ShaderNodeTexImage":
                if node.image:
                    yield node, node.image
            elif node.bl_idname == "ShaderNodeGroup" and node.node_tree:
                stack.append(node.node_tree)


def get_material_texture_images(objects):
    images = []
    seen_images = set()

    for material in collect_object_materials(objects):
        for _node, image in iter_material_image_texture_nodes(material):
            if image.name in seen_images:
                continue
            images.append(image)
            seen_images.add(image.name)

    return images


_NODE_ROLE_HINTS = (
    ("normal",    ("normal", "_nml", "_nor", "norm")),
    ("diffuse",   ("color", "diffuse", "albedo", "basecolor", "_col", "diff")),
    # ``specular`` matched before ``roughness`` so packed-map names like
    # ``specularRoughness`` / ``specularGloss`` (glTF / Substance / CoD
    # variants) keep the spec role; the structural roughness detector
    # tracks down the actual roughness channel via the group's
    # ``Roughness`` output trace, regardless of node-name conventions.
    ("specular",  ("specular", "_spc", "_spec", "metal")),
    ("roughness", ("rough", "gloss")),
)

_ALPHA_LABEL_HINTS = ("alpha", "opacity", "mask", "transp", "_alp")


def _is_alpha_label(name):
    if not name:
        return False
    low = name.lower()
    return any(h in low for h in _ALPHA_LABEL_HINTS)


def classify_node_role(node, image):
    """Classify the PBR role of an image texture node.

    Prefers an explicit role hint from the node label/name (importers
    usually set these to ``colorMap`` / ``normalMap`` / etc.). Falls back
    to the filename pattern when the node has no informative name."""
    for source in (getattr(node, "label", ""), getattr(node, "name", "")):
        if not source:
            continue
        low = source.lower()
        for role, hints in _NODE_ROLE_HINTS:
            if any(h in low for h in hints):
                return role
    if image and image.filepath:
        return classify_texture_role(image.filepath)
    return None


def detect_material_opacity(material):
    """Return ``(image, threshold)`` if the source material genuinely
    intends an alpha mask, else ``None``.

    The CoD-style importer wires every material's outer node-group ``Alpha``
    output to ``Principled BSDF.Alpha`` as a blanket — including solid
    materials like trash bins. The reliable signal is the group's *internal*
    ``GroupOutput.Alpha`` socket: if that socket is linked back to an image
    texture node (typically named ``colorOpacity``), the importer actually
    packed an alpha channel into the texture. If the inner socket is
    unwired, the outer Alpha output is connected to nothing meaningful and
    the material is solid.

    ``threshold`` mirrors ``material.blend_method``: ``BLEND`` -> 0.0
    (true alpha blend, smoother chainlink/glass edges), anything else
    (HASHED / CLIP) -> 0.5 (cutout mask, what foliage and razor-wire
    expect)."""
    if not material.use_nodes or not material.node_tree:
        return None

    for node in material.node_tree.nodes:
        if node.bl_idname != "ShaderNodeGroup" or not node.node_tree:
            continue
        out_node = next(
            (n for n in node.node_tree.nodes if n.bl_idname == "NodeGroupOutput"),
            None,
        )
        if out_node is None:
            continue
        for sock in out_node.inputs:
            if not _is_alpha_label(sock.name):
                continue
            if not sock.is_linked or not sock.links:
                return None
            src = sock.links[0].from_node
            if src.bl_idname == "ShaderNodeTexImage" and src.image:
                threshold = 0.0 if material.blend_method == "BLEND" else 0.5
                return (src.image, threshold)
            return None
        return None
    return None


def detect_material_roughness(material):
    """Trace where the material's roughness signal comes from inside its
    node group. Returns ``(image, channel, invert)`` or ``None``.

    * ``channel`` is ``"rgb"`` if the group's ``Roughness`` output socket is
      driven by an image's RGB output, ``"a"`` if driven by alpha.
    * ``invert`` is True when the path goes through a ``ShaderNodeInvert``
      node — common in CoD-style importers that store *gloss* in the spec
      map's alpha and feed it to ``Roughness`` through Invert."""
    if not material.use_nodes or not material.node_tree:
        return None

    for node in material.node_tree.nodes:
        if node.bl_idname != "ShaderNodeGroup" or not node.node_tree:
            continue
        out_node = next(
            (n for n in node.node_tree.nodes if n.bl_idname == "NodeGroupOutput"),
            None,
        )
        if out_node is None:
            continue
        for sock in out_node.inputs:
            nm = (sock.name or "").lower()
            if not any(k in nm for k in ("rough", "gloss")):
                continue
            if not sock.is_linked or not sock.links:
                return None
            link = sock.links[0]
            invert = False
            src = link.from_node
            from_sock_name = link.from_socket.name
            if src.bl_idname == "ShaderNodeInvert":
                invert = True
                upstream = next(
                    (i for i in src.inputs if i.is_linked and i.name in ("Color", "Image")),
                    None,
                )
                if upstream is None:
                    return None
                inner = upstream.links[0]
                src = inner.from_node
                from_sock_name = inner.from_socket.name
            if src.bl_idname == "ShaderNodeTexImage" and src.image:
                channel = "a" if from_sock_name.lower() == "alpha" else "rgb"
                return (src.image, channel, invert)
            return None
        return None
    return None


def collect_direct_material_textures(objects):
    """Build the per-material role map from direct node-tree walks.

    Returns ``(textures, options)`` where:

    * ``textures`` is ``{material_name: {role: image}}`` covering at minimum
      ``diffuse`` / ``normal`` / ``specular``, plus ``opacity`` when the
      importer intended an alpha mask (see :func:`detect_material_opacity`).
      The ``opacity`` role's image is typically the same RGBA file as the
      diffuse, just with its alpha channel exposed downstream.
    * ``options`` is ``{material_name: {"opacity_threshold": float}}`` —
      additional per-material settings the USD patcher needs but that don't
      fit the role/image model."""
    textures = {}
    options = {}
    for material in collect_object_materials(objects):
        roles = {}
        for node, image in iter_material_image_texture_nodes(material):
            role = classify_node_role(node, image)
            if role and role not in roles:
                roles[role] = image

        opacity = detect_material_opacity(material)
        if opacity is not None:
            opacity_image, threshold = opacity
            roles["opacity"] = opacity_image
            options.setdefault(material.name, {})["opacity_threshold"] = threshold

        roughness = detect_material_roughness(material)
        if roughness is not None:
            rough_image, channel, invert = roughness
            spec_image = roles.get("specular")
            shared_with_spec = (
                spec_image is not None
                and channel == "a"
                and rough_image.name == spec_image.name
            )
            opts = options.setdefault(material.name, {})
            if shared_with_spec:
                # CoD-style: spec map's alpha encodes gloss; expose it as
                # an extra output on the existing specular UsdUVTexture
                # rather than authoring a duplicate texture node.
                opts["roughness_from_specular_alpha"] = True
                opts["roughness_invert"] = invert
            elif channel == "a":
                # Detector found roughness on an image's alpha channel, but
                # we can't piggyback on a matching specular role. Authoring
                # a standalone roughness texture would read outputs:r — the
                # colour channel, not the alpha that actually carries the
                # signal — so we'd wire the wrong data. Skip rather than
                # publish a misleading roughness; the lighting team can
                # override downstream.
                pass
            else:
                # Standalone roughness or gloss image (RGB-driven). The
                # classifier already picked it up via the ``roughness`` role
                # hint when the node name is unambiguous; keep it in roles
                # in case the importer named the node something the hints
                # didn't catch. Inversion propagates as an option for
                # gloss-source files.
                roles.setdefault("roughness", rough_image)
                if invert:
                    opts["roughness_invert"] = invert

        if roles:
            textures[material.name] = roles
    return textures, options


def get_material_names(objects):
    return {m.name for m in collect_object_materials(objects)}


def normalize_texture_key(name):
    return "".join(ch.lower() for ch in name if ch.isalnum())


def name_tokens(name):
    tokens = []
    current = []
    for char in name.lower():
        if char.isalnum():
            current.append(char)
        elif current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return [token for token in tokens if token not in {"dec", "dc"}]


def texture_matches_material(material_name, texture_path):
    material_key = normalize_texture_key(material_name)
    file_key = normalize_texture_key(Path(texture_path).stem)
    if material_key in file_key:
        return True

    tokens = [token for token in name_tokens(material_name) if len(token) > 1]
    if len(tokens) < 2:
        return False

    return all(token in file_key for token in tokens[:2])


def classify_texture_role(path):
    name = Path(path).stem.lower()
    if any(token in name for token in ("_nml", "_normal", "_norm", "_nor")):
        return "normal"
    if any(token in name for token in ("_col", "_color", "_diff", "_albedo", "_basecolor", "_base_color")):
        return "diffuse"
    if any(token in name for token in ("_spc", "_spec", "_specular")):
        return "specular"
    return None


def get_texture_search_roots(export_path):
    export_dir = Path(export_path).parent
    scene_root = export_dir.parent
    roots = []

    for name in ("exported_images", "exported_maps", "textures"):
        candidate = scene_root / name
        if candidate.is_dir():
            roots.append(candidate)

    return roots


def find_named_material_textures(material_names, export_path):
    roots = get_texture_search_roots(export_path)
    if not roots:
        return {}

    texture_extensions = {".png", ".jpg", ".jpeg", ".tga", ".tif", ".tiff", ".exr", ".bmp", ".dds"}
    material_keys = {
        material_name: normalize_texture_key(material_name)
        for material_name in material_names
    }
    matches = {material_name: {} for material_name in material_names}

    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in texture_extensions:
                continue

            file_key = normalize_texture_key(path.stem)
            role = classify_texture_role(path)
            if not role:
                continue

            for material_name, material_key in material_keys.items():
                if not texture_matches_material(material_name, path):
                    continue

                existing = matches[material_name].get(role)
                if not existing or len(path.name) < len(existing.name):
                    matches[material_name][role] = path

    return {name: roles for name, roles in matches.items() if roles}


def texture_source_paths(image):
    filepath = image.filepath
    if not filepath:
        return []

    absolute_path = bpy.path.abspath(filepath, library=image.library)
    if "<UDIM>" not in absolute_path:
        return [absolute_path]

    paths = []
    for tile in image.tiles:
        tile_path = absolute_path.replace("<UDIM>", str(tile.number))
        if os.path.isfile(tile_path):
            paths.append(tile_path)
    return paths


def unique_texture_destination(textures_dir, filename, used_names):
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    candidate = filename
    index = 1

    while candidate.lower() in used_names:
        candidate = f"{stem}_{index}{suffix}"
        index += 1

    used_names.add(candidate.lower())
    return textures_dir / candidate


def _copy_source_to_textures_dir(source_path, textures_dir, used_names, copied_paths):
    """Copy ``source_path`` into ``textures_dir`` with collision-safe naming.
    Returns the destination ``Path`` or ``None`` if the source is missing."""
    if not os.path.isfile(source_path):
        return None

    preferred_destination = textures_dir / Path(source_path).name
    if preferred_destination.exists():
        try:
            if os.path.samefile(source_path, preferred_destination):
                if str(preferred_destination) not in {str(p) for p in copied_paths}:
                    copied_paths.append(preferred_destination)
                used_names.add(preferred_destination.name.lower())
                return preferred_destination
        except OSError:
            pass

    destination = preferred_destination
    if destination.name.lower() in used_names:
        destination = unique_texture_destination(
            textures_dir, Path(source_path).name, used_names)
    else:
        used_names.add(destination.name.lower())

    if not (destination.exists() and os.path.samefile(source_path, destination)):
        shutil.copy2(source_path, destination)
    copied_paths.append(destination)
    return destination


def copy_material_textures(objects, export_path):
    """Copy textures next to the USD and return a ``{material: {role: dest}}``
    map for the USD patcher.

    Strategy:
      1. Walk each material's node tree (including ``ShaderNodeGroup``) for
         direct image-texture nodes. This gives us a precise per-material,
         per-role mapping with zero guesswork.
      2. Copy every image referenced by any material into ``./textures/``.
      3. For materials still missing role coverage after the direct pass,
         fall back to filename-token matching against sibling texture
         folders (``exported_images``, ``exported_maps``, ``textures``).
         The fuzzy step is intentionally a fallback so we never overwrite
         a good direct hit with a guessed match.
    """
    textures_dir = Path(export_path).parent / "textures"
    textures_dir.mkdir(parents=True, exist_ok=True)

    copied_paths = []
    texture_map = {}
    used_names = set()
    missing_paths = []
    image_to_destination = {}

    # Step 1: copy every image referenced (directly or via groups) by any material.
    for image in get_material_texture_images(objects):
        if image.name in image_to_destination:
            continue

        source_paths = texture_source_paths(image)
        if not source_paths and image.packed_file:
            filename = Path(image.filepath or image.name).name
            if not Path(filename).suffix:
                filename += ".bin"
            destination = unique_texture_destination(textures_dir, filename, used_names)
            destination.write_bytes(image.packed_file.data)
            copied_paths.append(destination)
            image_to_destination[image.name] = destination
            continue

        for source_path in source_paths:
            destination = _copy_source_to_textures_dir(
                source_path, textures_dir, used_names, copied_paths)
            if destination is None:
                missing_paths.append(source_path)
                continue
            image_to_destination.setdefault(image.name, destination)

    # Step 2: build the texture map from direct material walks.
    direct_textures, material_options = collect_direct_material_textures(objects)
    direct_covered = set()
    for material_name, roles in direct_textures.items():
        material_roles = {}
        for role, image in roles.items():
            destination = image_to_destination.get(image.name)
            if destination:
                material_roles[role] = destination
        if material_roles:
            texture_map[material_name] = material_roles
            direct_covered.add(material_name)

    # Step 3: fuzzy fallback only for materials the direct pass couldn't wire.
    all_material_names = get_material_names(objects)
    fuzzy_targets = all_material_names - direct_covered
    fuzzy_count = 0
    if fuzzy_targets:
        named_textures = find_named_material_textures(fuzzy_targets, export_path)
        for material_name, roles in named_textures.items():
            material_roles = texture_map.setdefault(material_name, {})
            for role, source_path in roles.items():
                if role in material_roles:
                    continue
                destination = _copy_source_to_textures_dir(
                    str(source_path), textures_dir, used_names, copied_paths)
                if destination is None:
                    missing_paths.append(str(source_path))
                    continue
                material_roles[role] = destination
                fuzzy_count += 1

    if copied_paths:
        print(f"Copied {len(copied_paths)} material texture file(s) to {textures_dir}")
    if missing_paths:
        unique_missing = sorted(set(missing_paths))
        print(f"Missing material texture file(s) ({len(unique_missing)}): "
              + ", ".join(unique_missing[:10])
              + (" ..." if len(unique_missing) > 10 else ""))
    n_opacity = sum(1 for r in texture_map.values() if "opacity" in r)
    print(f"Texture map: {len(texture_map)} material(s) wired "
          f"({len(direct_covered)} direct, {fuzzy_count} fuzzy fallback, "
          f"{n_opacity} with alpha)")

    return copied_paths, texture_map, material_options


def find_preview_surface_shader(material):
    from pxr import UsdShade

    surface_outputs = material.GetSurfaceOutputs()
    for output in surface_outputs:
        source = output.GetConnectedSource()
        if not source:
            continue

        source_api, source_name, source_type = source
        shader = UsdShade.Shader(source_api.GetPrim())
        shader_id = shader.GetIdAttr().Get()
        if shader_id == "UsdPreviewSurface":
            return shader

    return None


def connect_texture_to_preview(stage, material, preview_shader, role, texture_path,
                               *, also_alpha=False, opacity_threshold=None,
                               also_roughness_via_alpha=False, roughness_invert=False):
    """Author a UsdUVTexture for ``role`` and wire it into ``preview_shader``.

    Side channels (one UsdUVTexture, multiple outputs) avoid duplicating
    texture nodes when an image carries more than one signal:

    * ``also_alpha`` (``role='diffuse'`` only): exposes ``outputs:a`` and
      wires ``UsdPreviewSurface.opacity`` to it. The CoD pipeline packs
      foliage / fence cutout masks into the diffuse RGBA.
    * ``also_roughness_via_alpha`` (``role='specular'`` only): exposes
      ``outputs:a`` and wires ``UsdPreviewSurface.roughness`` to it. When
      ``roughness_invert`` is also True the alpha channel is remapped via
      ``scale=(1,1,1,-1) bias=(0,0,0,1)`` to flip gloss → roughness.

    For ``role='roughness'`` (standalone roughness/gloss image), we author
    the texture and wire ``outputs:r`` to ``inputs:roughness``. When the
    image actually encodes gloss, ``roughness_invert=True`` flips RGB via
    ``scale=(-1,-1,-1,1) bias=(1,1,1,0)``."""
    from pxr import Gf, Sdf, UsdShade

    material_path = material.GetPath()
    texture_name = "PowerUSD_" + role + "_texture"
    texture_shader = UsdShade.Shader.Define(
        stage, material_path.AppendChild(texture_name))
    texture_shader.CreateIdAttr("UsdUVTexture")
    texture_shader.CreateInput(
        "file", Sdf.ValueTypeNames.Asset).Set("./textures/" + Path(texture_path).name)
    texture_shader.CreateInput(
        "sourceColorSpace", Sdf.ValueTypeNames.Token).Set("sRGB" if role == "diffuse" else "raw")

    if role == "normal":
        # Tangent-space normals are stored in [0,1]; remap to [-1,1] so strict
        # USD Preview Surface consumers shade correctly.
        texture_shader.CreateInput(
            "scale", Sdf.ValueTypeNames.Float4).Set(Gf.Vec4f(2.0, 2.0, 2.0, 1.0))
        texture_shader.CreateInput(
            "bias", Sdf.ValueTypeNames.Float4).Set(Gf.Vec4f(-1.0, -1.0, -1.0, 0.0))
    elif role == "specular" and also_roughness_via_alpha and roughness_invert:
        # RGB pass-through, alpha → 1 - alpha (gloss flipped to roughness).
        texture_shader.CreateInput(
            "scale", Sdf.ValueTypeNames.Float4).Set(Gf.Vec4f(1.0, 1.0, 1.0, -1.0))
        texture_shader.CreateInput(
            "bias", Sdf.ValueTypeNames.Float4).Set(Gf.Vec4f(0.0, 0.0, 0.0, 1.0))
    elif role == "roughness" and roughness_invert:
        # Source is a gloss map; flip RGB so the value reads as roughness.
        texture_shader.CreateInput(
            "scale", Sdf.ValueTypeNames.Float4).Set(Gf.Vec4f(-1.0, -1.0, -1.0, 1.0))
        texture_shader.CreateInput(
            "bias", Sdf.ValueTypeNames.Float4).Set(Gf.Vec4f(1.0, 1.0, 1.0, 0.0))

    texture_shader.CreateOutput("rgb", Sdf.ValueTypeNames.Float3)

    st_reader = UsdShade.Shader.Define(
        stage, material_path.AppendChild("PowerUSD_st_reader"))
    st_reader.CreateIdAttr("UsdPrimvarReader_float2")
    # `inputs:varname` is typed as `string` per UsdPrimvarReader_float2's
    # Sdr definition; using `token` fails usdchecker compliance.
    st_reader.CreateInput("varname", Sdf.ValueTypeNames.String).Set("st")
    st_reader.CreateOutput("result", Sdf.ValueTypeNames.Float2)
    texture_shader.CreateInput(
        "st", Sdf.ValueTypeNames.Float2).ConnectToSource(st_reader.ConnectableAPI(), "result")

    if role == "diffuse":
        preview_shader.CreateInput(
            "diffuseColor", Sdf.ValueTypeNames.Color3f).ConnectToSource(
                texture_shader.ConnectableAPI(), "rgb")
        if also_alpha:
            texture_shader.CreateOutput("a", Sdf.ValueTypeNames.Float)
            preview_shader.CreateInput(
                "opacity", Sdf.ValueTypeNames.Float).ConnectToSource(
                    texture_shader.ConnectableAPI(), "a")
            if opacity_threshold is not None:
                preview_shader.CreateInput(
                    "opacityThreshold", Sdf.ValueTypeNames.Float).Set(float(opacity_threshold))
    elif role == "specular":
        texture_shader.CreateOutput("r", Sdf.ValueTypeNames.Float)
        preview_shader.CreateInput(
            "specular", Sdf.ValueTypeNames.Float).ConnectToSource(
                texture_shader.ConnectableAPI(), "r")
        if also_roughness_via_alpha:
            texture_shader.CreateOutput("a", Sdf.ValueTypeNames.Float)
            preview_shader.CreateInput(
                "roughness", Sdf.ValueTypeNames.Float).ConnectToSource(
                    texture_shader.ConnectableAPI(), "a")
    elif role == "roughness":
        texture_shader.CreateOutput("r", Sdf.ValueTypeNames.Float)
        preview_shader.CreateInput(
            "roughness", Sdf.ValueTypeNames.Float).ConnectToSource(
                texture_shader.ConnectableAPI(), "r")
    elif role == "normal":
        preview_shader.CreateInput(
            "normal", Sdf.ValueTypeNames.Normal3f).ConnectToSource(
                texture_shader.ConnectableAPI(), "rgb")


def patch_usd_material_textures(usd_path, texture_map, material_options=None):
    if not texture_map or not os.path.isfile(usd_path) or usd_path.lower().endswith(".usdz"):
        return

    try:
        from pxr import Usd, UsdShade
    except Exception as exc:
        print(f"Could not patch USD texture links: {exc}")
        return

    stage = Usd.Stage.Open(usd_path)
    if not stage:
        print(f"Could not open USD for texture patching: {usd_path}")
        return

    patched = 0
    texture_map_by_key = {
        normalize_texture_key(material_name): roles
        for material_name, roles in texture_map.items()
    }
    options_by_key = {
        normalize_texture_key(material_name): opts
        for material_name, opts in (material_options or {}).items()
    }

    for prim in stage.Traverse():
        if not prim.IsA(UsdShade.Material):
            continue

        material_name = prim.GetName()
        roles = texture_map_by_key.get(normalize_texture_key(material_name))
        if not roles:
            continue

        material = UsdShade.Material(prim)
        preview_shader = find_preview_surface_shader(material)
        if not preview_shader:
            continue

        opts = options_by_key.get(normalize_texture_key(material_name)) or {}
        opacity_path = roles.get("opacity")
        diffuse_path = roles.get("diffuse")
        # The opacity channel is reused from the diffuse texture only when
        # both roles point at the same image file. The CoD pipeline always
        # packs alpha into the diffuse RGBA so this is the common path.
        wire_alpha_into_diffuse = (
            opacity_path is not None
            and diffuse_path is not None
            and Path(opacity_path).name == Path(diffuse_path).name
        )
        wire_rough_into_specular = bool(opts.get("roughness_from_specular_alpha"))
        roughness_invert = bool(opts.get("roughness_invert"))

        for role in ("diffuse", "specular", "roughness", "normal"):
            if role not in roles:
                continue
            kwargs = {}
            if role == "diffuse":
                kwargs["also_alpha"] = wire_alpha_into_diffuse
                kwargs["opacity_threshold"] = opts.get("opacity_threshold")
            elif role == "specular":
                kwargs["also_roughness_via_alpha"] = wire_rough_into_specular
                kwargs["roughness_invert"] = roughness_invert
            elif role == "roughness":
                kwargs["roughness_invert"] = roughness_invert
            connect_texture_to_preview(
                stage, material, preview_shader, role, roles[role], **kwargs)
            patched += 1

    if patched:
        stage.GetRootLayer().Save()
        print(f"Patched {patched} USD material texture link(s) in {usd_path}")


_USD_INVALID_CHARS = __import__("re").compile(r"[^A-Za-z0-9_]")


def usd_sanitize_identifier(name):
    """Approximate Blender's USD prim-name sanitization: replace invalid
    chars with ``_``, prefix a leading digit with ``_``."""
    if not name:
        return "_"
    s = _USD_INVALID_CHARS.sub("_", name)
    if s[0].isdigit():
        s = "_" + s
    return s


def strip_lights_from_usd(usd_path):
    """Remove every light prim and any UsdLux* schema-applied prim from
    the USD. Cinematics teams light their own scenes and don't want
    DCC-authored lights, dome lights, or world env lights bleeding in.

    Works in two passes that NEVER iterate the stage while mutating it:
      1. Snapshot every light-typed path under the stage, then remove.
      2. Snapshot direct children of ``/root`` that are now empty Xforms
         (e.g. our ``/root/Lights`` group after every child was stripped)
         and remove those. Deeper-tree empty groups are left alone — they
         may be intentional placeholders elsewhere in the scene.
    """
    if not os.path.isfile(usd_path) or usd_path.lower().endswith(".usdz"):
        return None
    try:
        from pxr import Usd
    except Exception as exc:
        print(f"Could not strip lights: {exc}")
        return None

    stage = Usd.Stage.Open(usd_path)
    if not stage:
        return None

    # Pass 1: find every light prim and its applied-schema variants.
    light_paths = []
    for prim in stage.TraverseAll():
        type_name = prim.GetTypeName()
        if not type_name:
            continue
        # Catches SphereLight, DistantLight, RectLight, DiskLight, DomeLight,
        # CylinderLight, GeometryLight, PluginLight, MeshLight, PortalLight,
        # plus any vendor-prefixed Light schema name.
        if type_name.endswith("Light"):
            light_paths.append(prim.GetPath())
            continue
        applied = prim.GetAppliedSchemas()
        if any("Light" in s for s in applied):
            light_paths.append(prim.GetPath())

    for path in light_paths:
        stage.RemovePrim(path)

    # Pass 2: drop top-level grouping Xforms that just emptied out (e.g.
    # ``/root/Lights`` once every child light is gone). Bounded to one
    # level under /root so we never touch deeper organisational groups.
    empty_top_groups = []
    root = stage.GetPrimAtPath("/root")
    if root:
        candidate_paths = [c.GetPath() for c in root.GetChildren()]
        for path in candidate_paths:
            prim = stage.GetPrimAtPath(path)
            if not prim or not prim.IsValid():
                continue
            if prim.GetTypeName() != "Xform":
                continue
            if list(prim.GetChildren()):
                continue
            empty_top_groups.append(path)
    for path in empty_top_groups:
        stage.RemovePrim(path)

    if light_paths or empty_top_groups:
        stage.GetRootLayer().Save()
    if light_paths or empty_top_groups:
        print(f"Stripped {len(light_paths)} light prim(s) and "
              f"{len(empty_top_groups)} empty top-level group(s) from {usd_path}")
    return {"removed_lights": len(light_paths),
            "removed_empty_groups": len(empty_top_groups)}


def build_object_collection_map(objects, root_collection_name="Scene Collection"):
    """For each export object, return its primary parent collection name.

    Used to reorganise the post-export USD into ``/root/<collection>/<obj>``
    so cinematics tools see a clean grouping by source collection instead
    of 6,000 prims dumped flat under ``/root``."""
    out = {}
    for obj in objects:
        users = getattr(obj, "users_collection", None)
        if not users:
            continue
        coll = users[0]
        if not coll or coll.name == root_collection_name:
            continue
        group = usd_sanitize_identifier(coll.name)
        # Key by both the raw and the sanitised object name so we can match
        # whichever form Blender's USD exporter happens to write.
        out[obj.name] = group
        out[usd_sanitize_identifier(obj.name)] = group
    return out


def organize_usd_by_collection(usd_path, object_collection_map, root_prim_path="/root"):
    """Move flat top-level prims under Xforms named after their source
    Blender collection.

    Skips the materials scope and any prim that doesn't have a known source
    object (e.g. dome lights authored from world settings) — those are left
    where Blender placed them so we never lose data.
    """
    if not object_collection_map or not os.path.isfile(usd_path):
        return None
    if usd_path.lower().endswith(".usdz"):
        return None

    try:
        from pxr import Usd, UsdGeom, Sdf
    except Exception as exc:
        print(f"Could not reorganise USD hierarchy: {exc}")
        return None

    stage = Usd.Stage.Open(usd_path)
    if not stage:
        return None

    layer = stage.GetRootLayer()
    root = stage.GetPrimAtPath(root_prim_path)
    if not root:
        return None

    moves = []
    untouched = 0
    for prim in list(root.GetChildren()):
        name = prim.GetName()
        if name == "_materials":
            untouched += 1
            continue
        group = object_collection_map.get(name)
        if not group:
            untouched += 1
            continue
        new_parent_path = f"{root_prim_path}/{group}"
        new_path = f"{new_parent_path}/{name}"
        moves.append((str(prim.GetPath()), new_path, new_parent_path))

    if not moves:
        return {"moved": 0, "untouched": untouched}

    # Pre-create grouping Xforms so the CopySpec target paths resolve.
    for _old, _new, parent in {(m[0], m[1], m[2]) for m in moves}:
        UsdGeom.Xform.Define(stage, parent)
    # Avoid creating a duplicate top-level prim of the same name as the
    # group while iterating: copy first, then delete originals.
    for old_path, new_path, _parent in moves:
        Sdf.CopySpec(layer, old_path, layer, new_path)
    for old_path, _new_path, _parent in moves:
        stage.RemovePrim(old_path)

    stage.GetRootLayer().Save()
    print(f"Reorganised USD: moved {len(moves)} prim(s) into collection groups, "
          f"left {untouched} at /root")
    return {"moved": len(moves), "untouched": untouched}


def append_textures_to_usdz(usdz_path, texture_paths):
    if not texture_paths or not zipfile.is_zipfile(usdz_path):
        return

    with zipfile.ZipFile(usdz_path, "a", compression=zipfile.ZIP_STORED) as archive:
        existing_names = set(archive.namelist())
        added = 0
        for texture_path in texture_paths:
            arcname = "textures/" + Path(texture_path).name
            if arcname in existing_names:
                continue
            archive.write(texture_path, arcname)
            existing_names.add(arcname)
            added += 1

    if added:
        print(f"Added {added} collected texture file(s) to {usdz_path}")


def capture_thumbnail(objects, filepath, size=256, limit_textures=False, texture_limit='CLAMP_1024'):
    """
    Capture a thumbnail of specified objects using offscreen rendering.
    Objects are isolated, framed, and rendered with transparent background.
    """
    context = bpy.context
    scene = context.scene

    # Convert to list to ensure we have a stable reference
    objects_list = list(objects)

    # Store original visibility states and set up isolation
    hidden_objects = []  # Objects we hid (were visible, not in our list)
    unhidden_objects = []  # Objects we unhid (were hidden, in our list)

    for obj in bpy.data.objects:
        # Skip objects not in the view layer (can't hide/unhide them)
        if obj.name not in context.view_layer.objects:
            continue

        if obj in objects_list:
            # Ensure objects in our list are visible
            if obj.hide_get():
                obj.hide_set(False)
                unhidden_objects.append(obj)
        else:
            # Hide objects not in our list
            if not obj.hide_get():
                obj.hide_set(True)
                hidden_objects.append(obj)

    # Store original selection and set new selection
    original_selection = context.selected_objects[:]
    original_active = context.view_layer.objects.active

    bpy.ops.object.select_all(action='DESELECT')
    for obj in objects_list:
        if obj.name in context.view_layer.objects:
            obj.select_set(True)

    # Find 3D viewport area and region
    view3d_area = None
    view3d_region = None
    view3d_space = None
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            view3d_area = area
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    view3d_space = space
                    break
            for region in area.regions:
                if region.type == 'WINDOW':
                    view3d_region = region
                    break
            break

    # Store original viewport settings
    original_shading_type = None
    original_show_overlays = None
    original_color_type = None
    original_light = None
    original_show_object_outline = None
    original_show_specular = None
    if view3d_space:
        original_shading_type = view3d_space.shading.type
        original_show_overlays = view3d_space.overlay.show_overlays
        original_color_type = view3d_space.shading.color_type
        original_light = view3d_space.shading.light
        original_show_object_outline = view3d_space.shading.show_object_outline
        original_show_specular = view3d_space.shading.show_specular_highlight
        # Set to solid view with textures, disable overlays and extras
        view3d_space.shading.type = 'SOLID'
        view3d_space.shading.color_type = 'TEXTURE'
        view3d_space.shading.light = 'STUDIO'
        view3d_space.shading.show_object_outline = False
        view3d_space.shading.show_specular_highlight = False
        view3d_space.overlay.show_overlays = False

    # Limit texture size to save memory if enabled
    original_texture_limit = None
    if limit_textures:
        original_texture_limit = context.preferences.system.gl_texture_limit
        context.preferences.system.gl_texture_limit = texture_limit

    if view3d_area and view3d_region:
        # Frame selected objects in view
        with context.temp_override(area=view3d_area, region=view3d_region):
            bpy.ops.view3d.view_selected()

    # Store original render settings
    original_res_x = scene.render.resolution_x
    original_res_y = scene.render.resolution_y
    original_res_percentage = scene.render.resolution_percentage
    original_film_transparent = scene.render.film_transparent
    original_filepath = scene.render.filepath
    original_file_format = scene.render.image_settings.file_format
    original_color_mode = scene.render.image_settings.color_mode

    # Set render settings for thumbnail
    scene.render.resolution_x = size
    scene.render.resolution_y = size
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.filepath = filepath
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'

    # Render using OpenGL (viewport render)
    if view3d_area:
        with context.temp_override(area=view3d_area):
            bpy.ops.render.opengl(write_still=True)

    # Restore render settings
    scene.render.resolution_x = original_res_x
    scene.render.resolution_y = original_res_y
    scene.render.resolution_percentage = original_res_percentage
    scene.render.film_transparent = original_film_transparent
    scene.render.filepath = original_filepath
    scene.render.image_settings.file_format = original_file_format
    scene.render.image_settings.color_mode = original_color_mode

    # Restore viewport settings
    if view3d_space:
        view3d_space.shading.type = original_shading_type
        view3d_space.shading.color_type = original_color_type
        view3d_space.shading.light = original_light
        view3d_space.shading.show_object_outline = original_show_object_outline
        view3d_space.shading.show_specular_highlight = original_show_specular
        view3d_space.overlay.show_overlays = original_show_overlays

    # Restore texture limit if we changed it
    if original_texture_limit is not None:
        context.preferences.system.gl_texture_limit = original_texture_limit

    # Restore visibility
    for obj in hidden_objects:
        obj.hide_set(False)
    for obj in unhidden_objects:
        obj.hide_set(True)

    # Restore selection
    bpy.ops.object.select_all(action='DESELECT')
    for obj in original_selection:
        if obj.name in context.view_layer.objects:
            obj.select_set(True)
    context.view_layer.objects.active = original_active


# Operator called when pressing the batch export button.
class EXPORT_MESH_OT_batch(Operator):
    """Export many objects to seperate files all at once"""
    bl_idname = "export_mesh.batch"
    bl_label = "USD Export"
    file_count = 0
    copy_count = 0

    def execute(self, context):
        settings = context.scene.batch_export

        # Set Base Directory
        base_dir = settings.directory
        if not bpy.data.is_saved:  # Then the blend file hasn't been saved
            # Then the path should be relative
            if base_dir != bpy.path.abspath(base_dir):
                self.report(
                    {'ERROR'}, "Save .blend file somewhere before exporting to relative directory\n(or use an absolute directory)")
                return {'FINISHED'}
        base_dir = bpy.path.abspath(base_dir)  # convert to absolute path
        if not os.path.isdir(base_dir):
            self.report({'ERROR'}, "Export directory doesn't exist")
            return {'FINISHED'}

        self.file_count = 0

        # Save current state of viewlayer, selection and active object to restore after export
        view_layer = context.view_layer
        selection = context.selected_objects
        obj_active = view_layer.objects.active   

        # Check if we're not in Object mode and set if needed
        obj_active = view_layer.objects.active        
        mode = ''
        if obj_active:
            mode = obj_active.mode
            bpy.ops.object.mode_set(mode='OBJECT')  # Only works in Object mode
        

        ##### EXPORT OBJECTS BASED ON MODES #####
        if settings.mode == 'OBJECTS':
            for obj in self.get_filtered_objects(context, settings):

                # Export Selection
                obj.select_set(True)
                self.export_selection(obj.name, context, base_dir)

                # Deselect Obj
                obj.select_set(False)

        elif settings.mode == 'PARENT_OBJECTS':
            exportObjects = self.get_filtered_objects(context, settings)

            for obj in exportObjects:
                if obj.parent in exportObjects:
                    continue  # if it has a parent, skip it for now, it'll be exported when we get to its parent

                # Export Selection
                obj.select_set(True)
                self.select_children_recursive(obj, context,)

                if context.selected_objects:
                    self.export_selection(obj.name, context, base_dir)

                # Deselect
                for obj in context.selected_objects:
                    obj.select_set(False)

        elif settings.mode == 'HIERARCHY_ROOTS':
            # Similar to 3ds Max "Respect Hierarchies" mode:
            # Find the absolute root of each hierarchy and export the entire tree
            exportObjects = self.get_filtered_objects(context, settings)
            processed_roots = []

            for obj in exportObjects:
                # Find the absolute root of this object's hierarchy
                root = get_hierarchy_root(obj)

                # Skip if we've already processed this root
                if root in processed_roots:
                    continue
                processed_roots.append(root)

                # Get all descendants of the root (the full hierarchy tree)
                full_tree = get_all_descendants(root)

                # Select all objects in the tree
                for tree_obj in full_tree:
                    tree_obj.select_set(True)

                if context.selected_objects:
                    # Export with the root's name
                    self.export_selection(root.name, context, base_dir)

                # Deselect all
                for tree_obj in context.selected_objects:
                    tree_obj.select_set(False)

        elif settings.mode == 'COLLECTIONS':
            exportobjects = self.get_filtered_objects(context, settings)

            for col in bpy.data.collections.values():
                # Check if collection objects are in filtered objects
                for obj in col.objects:
                    if not obj in exportobjects:
                        continue
                    obj.select_set(True)
                if context.selected_objects:
                    self.export_selection(col.name, context, base_dir)

                # Deselect
                for obj in context.selected_objects:
                    obj.select_set(False)

        # Functionality for both COLLECTION_SUBDIRECTORIES and COLLECTION_SUBDIR_PARENTS
        elif 'COLLECTION_SUBDIR' in settings.mode:
            exportobjects = self.get_filtered_objects(context, settings)

            for obj in exportobjects:
                if 'PARENT' in settings.mode and obj.parent in exportobjects:
                    continue  # if it has a parent, skip it for now, it'll be exported when we get to its parent

                # Modify base_dir to add collection, creating directory if necessary
                sCollection = obj.users_collection[0].name
                if sCollection != "Scene Collection":
                    if settings.full_hierarchy:
                        hierarchy = utils.get_collection_hierarchy(sCollection)
                        collection_dir = os.path.join(base_dir, hierarchy)
                    else:
                        collection_dir = os.path.join(base_dir, sCollection)

                    # create sub-directory if it doesn't exist
                    if not os.path.exists(collection_dir):
                        try:
                            os.makedirs(collection_dir)
                            print(f"Directory created: {collection_dir}")
                        except OSError as e:
                            self.report({'ERROR'}, f"Error creating directory {collection_dir}: {e}")
                else: # If object is just in Scene Collection it get's exported to base_dir
                    collection_dir = base_dir

                # Select
                obj.select_set(True)
                if 'PARENT' in settings.mode:
                    self.select_children_recursive(obj, context)

                # Export
                self.export_selection(obj.name, context, collection_dir)

                # Deselect
                for obj in context.selected_objects:
                    obj.select_set(False)

        elif settings.mode == 'SCENE':
            prefix = settings.prefix
            suffix = settings.suffix
            
            filename = ''
            if not prefix and not suffix:
                filename = bpy.path.basename(bpy.context.blend_data.filepath).split('.')[0]
            
            for obj in self.get_filtered_objects(context, settings):
                obj.select_set(True)
            self.export_selection(filename, context, base_dir)

        # Return selection to how it was
        bpy.ops.object.select_all(action='DESELECT')
        for obj in selection:
            obj.select_set(True)
        view_layer.objects.active = obj_active

        # Return to whatever mode the user was in
        if obj_active:
            bpy.ops.object.mode_set(mode=mode)

        # Report results
        copies = False
        name = __package__
        if name in context.preferences.addons:
            prefs = context.preferences.addons[name].preferences
            if prefs and hasattr(prefs, 'copy_on_export'):
                copies = prefs.copy_on_export

        if self.file_count == 0:
            self.report({'ERROR'}, "NOTHING TO EXPORT")
        elif copies and settings.copy_on_export:
            self.report({'INFO'}, f"Exported {self.file_count} file(s),\nMade {self.copy_count} copies")
        elif self.file_count:
            self.report({'INFO'}, f"Exported {self.file_count} file(s)")

        return {'FINISHED'}

    # Finds all renderable objects and returns a list of them
    def get_renderable_objects(self):
        """
        Recursively collect hidden objects from scene collections.
        
        Returns:
            list: A list of objects hidden in viewport or render
        """
        renderable_objects = []
        
        def check_collection(collection):
            # Skip if collection is None
            if not collection:
                return
            
            # Skip if the entire collection is hidden in render
            if collection.hide_render:
                return
            
            # Check objects in this collection
            for obj in collection.objects:
                # Check both viewport and render visibility
                if not obj.hide_render:
                    renderable_objects.append(obj)
            
            # Recursively check child collections
            while collection.children:
                for child_collection in collection.children:
                    # Skip child collections that are hidden in render
                    if not child_collection.hide_render:
                        check_collection(child_collection)
                break  # Use break to match the while loop structure
        
        # Start the recursive check from the scene's root collection
        check_collection(bpy.context.scene.collection)
        
        return renderable_objects

    # Deselect and Get Objects to Export by Limit Settings
    def get_filtered_objects(self, context, settings):
        objects = context.view_layer.objects.values()
        if settings.limit == 'VISIBLE':
            filtered_objects = []
            for obj in objects:
                obj.select_set(False)
                is_flattened_instancer = (
                    settings.flatten_instances
                    and getattr(obj, "instance_type", 'NONE') != 'NONE'
                )
                if obj.visible_get() and (obj.type in settings.object_types or is_flattened_instancer):
                    filtered_objects.append(obj)
            return filtered_objects
        if settings.limit == 'SELECTED':
            selection = context.selected_objects[:]
            filtered_objects = []
            for obj in objects:
                obj.select_set(False)
                if obj in selection:
                    is_flattened_instancer = (
                        settings.flatten_instances
                        and getattr(obj, "instance_type", 'NONE') != 'NONE'
                    )
                    if obj.type in settings.object_types or is_flattened_instancer:
                        filtered_objects.append(obj)
            return filtered_objects
        if settings.limit == 'RENDERABLE':
            filtered_objects = []
            for obj in objects:
                obj.select_set(False)
                is_flattened_instancer = (
                    settings.flatten_instances
                    and getattr(obj, "instance_type", 'NONE') != 'NONE'
                )
                if obj.visible_get() and (obj.type in settings.object_types or is_flattened_instancer):
                    if obj in self.get_renderable_objects():
                        filtered_objects.append(obj)
            return filtered_objects
        return objects

    def select_children_recursive(self, obj, context):
        object_types = context.scene.batch_export.object_types
        for c in obj.children:
            if c.type in object_types:
                c.select_set(True)
            self.select_children_recursive(c, context)

    def create_flattened_export_objects(self, context, selected_objects):
        instancers = [
            obj for obj in selected_objects
            if getattr(obj, "instance_type", 'NONE') != 'NONE'
        ]
        if not instancers:
            return [], []

        temp_collection = bpy.data.collections.new("PowerUSD_Flattened_Instances")
        context.scene.collection.children.link(temp_collection)

        depsgraph = context.evaluated_depsgraph_get()
        realized_objects = []
        instanced_source_objects = set()

        for instancer in instancers:
            if instancer.instance_type == 'COLLECTION' and instancer.instance_collection:
                instanced_source_objects.update(
                    get_collection_objects_recursive(instancer.instance_collection))

        instancer_set = set(instancers)

        for instance in depsgraph.object_instances:
            parent = getattr(instance.parent, "original", instance.parent)
            if not instance.is_instance or parent not in instancer_set:
                continue
            source_obj = getattr(instance.object, "original", instance.object)
            if not object_has_supported_geometry(source_obj):
                continue
            realized = make_realized_mesh_object(
                context, source_obj, instance.matrix_world.copy(),
                temp_collection, "PowerUSD_inst_")
            if realized:
                realized_objects.append(realized)

        for obj in selected_objects:
            if obj in instancer_set or obj in instanced_source_objects:
                continue
            if not object_has_supported_geometry(obj):
                continue
            realized = make_realized_mesh_object(
                context, obj, obj.matrix_world.copy(),
                temp_collection, "PowerUSD_obj_")
            if realized:
                realized_objects.append(realized)

        if realized_objects:
            print(
                f"Flattened {len(realized_objects)} real object(s) from "
                f"{len(instancers)} selected instancer(s)"
            )

        return realized_objects, [temp_collection]

    def cleanup_flattened_export_objects(self, objects, collections):
        for obj in objects:
            mesh = obj.data if hasattr(obj, "data") else None
            bpy.data.objects.remove(obj, do_unlink=True)
            if mesh and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        for collection in collections:
            if collection.name in bpy.data.collections:
                bpy.data.collections.remove(collection)

    def export_selection(self, itemname, context, base_dir):
        settings = context.scene.batch_export
        # save the transform to be reset later:
        old_locations = []
        old_rotations = []
        old_scales = []
        
        # Extra objects for LOD export store for later removal
        preLodObjects = []
        lodObjects = []

        objectsloop = list(context.selected_objects)
        original_active = context.view_layer.objects.active
        export_objects = objectsloop
        flattened_objects = []
        flattened_collections = []
        for obj in objectsloop:
            # Save Old Locations
            old_locations.append(obj.location.copy())
            old_rotations.append(obj.rotation_euler.copy())
            old_scales.append(obj.scale.copy())

            # If exporting by parent/hierarchy, don't set child (object that has a parent) transform
            if ("PARENT" in settings.mode or settings.mode == 'HIERARCHY_ROOTS') and obj.parent in context.selected_objects:
                continue
            else:
                if settings.set_location:
                    obj.location = settings.location
                if settings.set_rotation:
                    obj.rotation_euler = settings.rotation
                if settings.set_scale:
                    obj.scale = settings.scale

            # Change Itemname If Collection As Prefix
            if settings.prefix_collection and 'OBJECT' in settings.mode:
                collection_name = obj.users_collection[0].name
                if not collection_name == 'Scene Collection':
                    itemname = "_".join([collection_name, itemname])


        prefix = settings.prefix
        suffix = settings.suffix
        name = prefix + bpy.path.clean_name(itemname) + suffix
        fp = os.path.join(base_dir, name)
        extension = None
        # Export

        original_frame_start = context.scene.frame_start
        original_frame_end = context.scene.frame_end

        try:
            if settings.file_format == "USD":
                extension = settings.usd_format
                options = utils.load_operator_preset(
                    'wm.usd_export', settings.usd_preset)
                options["filepath"] = fp+extension
                options["selected_objects_only"] = True
                options["relative_paths"] = True
                options["export_materials"] = True
                options["generate_preview_surface"] = True
                # USD instancing is independent of flattening: flattening
                # produces real objects so instancing has no effect anyway.
                options["use_instancing"] = (
                    settings.use_instancing and not settings.flatten_instances
                )
                # Cinematics teams light their own scenes — never export the
                # Blender world as a UsdLuxDomeLight.
                options["convert_world_material"] = False
                options["export_animation"] = settings.export_animation
                # Blender 5.1 exposes only `export_textures_mode` (enum),
                # not a separate `export_textures` boolean. KEEP retains the
                # original disk paths, NEW copies textures next to the USD.
                if settings.texture_mode == 'COPY':
                    options["export_textures_mode"] = 'NEW'
                    options["overwrite_textures"] = True
                else:
                    options["export_textures_mode"] = 'KEEP'
                    options["overwrite_textures"] = False
                options = filter_operator_options('wm.usd_export', options)

                if settings.export_animation:
                    context.scene.frame_start = settings.frame_start
                    context.scene.frame_end = settings.frame_end

                if settings.flatten_instances:
                    flattened_objects, flattened_collections = self.create_flattened_export_objects(
                        context, objectsloop)
                    if flattened_objects:
                        export_objects = flattened_objects
                        bpy.ops.object.select_all(action='DESELECT')
                        for export_obj in export_objects:
                            export_obj.select_set(True)
                        context.view_layer.objects.active = export_objects[0]

                bpy.ops.wm.usd_export(**options)
                if settings.texture_mode == 'COPY':
                    copied_textures, texture_map, material_options = copy_material_textures(
                        export_objects, fp + extension)
                    if extension == ".usdz":
                        append_textures_to_usdz(fp + extension, copied_textures)
                    else:
                        patch_usd_material_textures(
                            fp + extension, texture_map, material_options)

                # Reorganise the flat /root tree Blender authors into Xforms
                # named after the source Blender collections. Cinematics tools
                # rely on this grouping for selection/isolation.
                if extension != ".usdz":
                    coll_map = build_object_collection_map(export_objects)
                    organize_usd_by_collection(fp + extension, coll_map)
                    # Cinematics deliverables strip every light source: no
                    # SphereLights, no DistantLights, no DomeLights. The
                    # downstream lighting team owns lighting.
                    strip_lights_from_usd(fp + extension)
        finally:
            # Selection cleanup must always run — if we don't restore here,
            # a failing export leaves a temp selection or stale active object.
            bpy.ops.object.select_all(action='DESELECT')
            for obj in objectsloop:
                if obj.name in context.view_layer.objects:
                    obj.select_set(True)
            if original_active and original_active.name in context.view_layer.objects:
                context.view_layer.objects.active = original_active
            self.cleanup_flattened_export_objects(
                flattened_objects, flattened_collections)

            # Restore frame range and per-object transforms even if export
            # raised, so a partial export can't leave the user's scene mutated.
            context.scene.frame_start = original_frame_start
            context.scene.frame_end = original_frame_end
            for i, obj in enumerate(objectsloop):
                if i >= len(old_locations):
                    break
                obj.location = old_locations[i]
                obj.rotation_euler = old_rotations[i]
                obj.scale = old_scales[i]

        print("exported: ", fp + extension)
        self.file_count += 1

        # Generate thumbnail if enabled
        if settings.generate_thumbnails:
            thumb_path = fp + "_thumb.png"
            capture_thumbnail(context.selected_objects, thumb_path, settings.thumbnail_size,
                              settings.limit_textures, settings.texture_limit)

        # COPY EXPORTED FILES
        copies = False
        name = __package__
        if name in context.preferences.addons:
            prefs = context.preferences.addons[name].preferences
            if prefs and hasattr(prefs, 'copy_on_export'):
                copies = prefs.copy_on_export

        if copies and settings.copy_on_export:
            exportfile = Path(fp).with_suffix(extension)
            if exportfile.exists():
                oldroot = Path(bpy.path.abspath(settings.directory))
                newroot = Path(bpy.path.abspath(settings.copy_directory))
                if not oldroot.resolve() == newroot.resolve():
                    subpath = exportfile.relative_to(oldroot)
                    copyfile = newroot / subpath

                    shutil.copy(exportfile, copyfile)
                    print('made this copy:   ', copyfile.resolve())
                    self.copy_count += 1



registry = [
    EXPORT_MESH_OT_batch,
]
