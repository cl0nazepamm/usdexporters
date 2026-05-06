# PowerUSD Production Risk Notes

Date: 2026-05-06

This file tracks implementation patterns that can break real production scenes or
make exports unreliable across Blender, USD, Cinema 4D, 3ds Max, and game
pipelines.

## Blender Exporter

### Real scene objects are mutated during export

Source area: `blender/Clone_PowerUSD/operators.py`, `export_selection`.

When transform reset options are enabled, the exporter currently stores object
transforms, applies reset values to the actual selected Blender objects, then
exports. If USD export, texture collection, USD patching, or another later step
raises before the restore loop runs, the user's scene can be left modified.

This is especially risky with flattened collection instances because the
instancer transform may be reset before evaluated instances are realized.

Production fix:
- Build a temporary export graph first.
- Apply transform reset only to temporary duplicates or realized objects.
- Keep original scene objects untouched.
- Put every temporary object/collection cleanup and any unavoidable restore in a
  hard `finally` path.

### Fuzzy texture matching can silently link the wrong maps

Source area: `blender/Clone_PowerUSD/operators.py`,
`texture_matches_material`, `find_named_material_textures`,
`copy_material_textures`.

The fallback texture matcher scans sibling folders such as `exported_images`,
`exported_maps`, and `textures`, then matches textures by normalized material
name tokens. In large game or kitbash exports, many unrelated assets share broad
tokens, so a material can receive a valid-looking but wrong texture.

Production fix:
- Prefer direct Blender image-node file paths.
- Use an explicit material-to-texture manifest when available.
- Make fuzzy fallback opt-in and report every inferred match.
- Treat ambiguous matches as warnings or failures, not silent success.

### USDZ packing is not enough if internal asset paths are not rewritten

Source area: `blender/Clone_PowerUSD/operators.py`,
`append_textures_to_usdz`, `patch_usd_material_textures`.

Textures may be appended into a `.usdz` archive, but `.usdz` files are skipped by
the patching step. That means the archive can contain texture files that are not
actually referenced by the USD content inside the package.

Production fix:
- Author correct relative texture paths before creating the USDZ.
- Or unpack/rewrite/repack the USDZ with verified internal asset paths.
- Validate the final package by opening the stage and checking resolved texture
  asset paths.

### Normal map Preview Surface wiring is too naive

Source area: `blender/Clone_PowerUSD/operators.py`,
`connect_texture_to_preview`.

The current patcher can connect a texture RGB output directly to
`UsdPreviewSurface.inputs:normal`. Some consumers tolerate this poorly or render
it incorrectly because a robust USD Preview Surface normal map network needs the
expected normal-map conversion pattern.

Production fix:
- Author a proper USD Preview Surface normal-map network.
- Validate in strict consumers, not only Blender.
- Keep normal, roughness, metallic, opacity, and base color roles typed
  correctly.

### Flatten instances is a destructive bake

Source area: `blender/Clone_PowerUSD/operators.py`,
`create_flattened_export_objects`, `make_realized_mesh_object`.

Flattening realizes evaluated instances into mesh objects. This is useful for
Cinema 4D compatibility, but it can discard object-level authoring such as
animation, constraints, custom properties, non-mesh semantics, and some instance
relationships.

Production fix:
- Label this as a compatibility bake, not a neutral flatten.
- Keep a separate game-export path that uses prototypes or point instancers when
  the downstream tool supports them.
- Report what was baked and what was dropped.

### Texture copy fallback can collide on basenames

Source area: `blender/Clone_PowerUSD/operators.py`, `copy_material_textures`.

Direct image-node copies use unique destination names, but named fallback
textures can copy to `textures/<basename>` without the same collision handling.
Different source folders with the same texture basename can overwrite or collapse
to one file.

Production fix:
- Route every copied texture through the same unique destination allocator.
- Keep a source-to-destination manifest.
- Patch USD references from the manifest, not from basename assumptions.

### Child selection filter can select the wrong objects

Source area: `blender/Clone_PowerUSD/operators.py`,
`select_children_recursive`.

The child recursion checks the parent object type while selecting each child.
That can include or exclude children based on the parent filter result rather
than each child's actual type.

Production fix:
- Check `c.type` for each child.
- Add a focused test with mixed mesh, empty, camera, and light children.

### Preset loading uses eval

Source area: `blender/Clone_PowerUSD/utils.py`, `get_operator_presets`.

Preset parsing currently evaluates preset values with `eval`. This is unsafe for
user-editable preset files and fragile for malformed values.

Production fix:
- Replace `eval` with `ast.literal_eval` plus typed fallbacks.
- Ignore unsupported preset values with a warning instead of executing them.

## Stage Assembly And Game-Scale Exports

### Manual stage fixes are not reusable exporter behavior yet

Recent work produced repaired or experimental stage files outside the source
tree, including C4D-style placed references and a game-style PointInstancer
stage. Those files prove useful directions, but they are not yet integrated into
PowerUSD's repeatable export path.

Production fix:
- Convert the working pattern into source-controlled exporter options.
- Add validation for illegal prim names, unresolved asset paths, excessive light
  duplication, material explosion, and instance placement.
- Add a report file per export with counts for prims, prototypes, instances,
  lights, materials, copied textures, missing textures, and warnings.

### Game exports need a different policy than DCC interchange exports

A real game export should not blindly emit thousands of duplicated materials,
lights, and mesh references if the source scene contains repeated asset
instances.

Production fix:
- Detect repeated assets and build prototypes.
- Use PointInstancer or a compact placed-reference strategy depending on target.
- Deduplicate dome lights and material definitions.
- Preserve texture links through a manifest-driven copy/reference step.
- Provide target presets such as `Cinema 4D Compatibility`,
  `Game Engine Compact`, and `Raw USD Authoring`.
