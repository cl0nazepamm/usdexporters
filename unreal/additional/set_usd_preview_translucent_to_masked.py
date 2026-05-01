import unreal

SEARCH_ROOT = "/Game"  # Change if needed
TARGET_PARENT_NAME = "UsdPreviewSurfaceTranslucent"


def has_parent_in_chain(mat_interface, target_name: str) -> bool:
    current = mat_interface
    while current:
        if current.get_name() == target_name:
            return True
        if isinstance(current, unreal.MaterialInstance):
            current = current.get_editor_property("parent")
        else:
            break
    return False


changed = 0
checked = 0
already_masked = 0
failed = 0

asset_paths = unreal.EditorAssetLibrary.list_assets(
    SEARCH_ROOT, recursive=True, include_folder=False
)

for asset_path in asset_paths:
    asset = unreal.EditorAssetLibrary.load_asset(asset_path)
    if not isinstance(asset, unreal.MaterialInstanceConstant):
        continue

    checked += 1

    try:
        parent = asset.get_editor_property("parent")
        if not parent or not has_parent_in_chain(parent, TARGET_PARENT_NAME):
            continue

        overrides = asset.get_editor_property("base_property_overrides")

        if (
            overrides.get_editor_property("override_blend_mode")
            and overrides.get_editor_property("blend_mode") == unreal.BlendMode.BLEND_MASKED
        ):
            already_masked += 1
            continue

        overrides.set_editor_property("override_blend_mode", True)
        overrides.set_editor_property("blend_mode", unreal.BlendMode.BLEND_MASKED)
        asset.set_editor_property("base_property_overrides", overrides)

        # Force refresh of material instance if the API is available in this UE build.
        if hasattr(unreal.MaterialEditingLibrary, "update_material_instance"):
            unreal.MaterialEditingLibrary.update_material_instance(asset)

        if unreal.EditorAssetLibrary.save_loaded_asset(asset, False):
            changed += 1
            unreal.log(f"Updated: {asset.get_path_name()}")
        else:
            failed += 1
            unreal.log_warning(f"Failed to save: {asset.get_path_name()}")

    except Exception as exc:
        failed += 1
        unreal.log_error(f"Error processing {asset_path}: {exc}")

unreal.log(
    f"Done. Checked {checked} MICs, changed {changed}, already masked {already_masked}, failed {failed}."
)
