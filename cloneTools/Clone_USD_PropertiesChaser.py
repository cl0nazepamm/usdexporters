"""
Clone USD Properties Chaser

Export chaser that reads USD properties from 3ds Max Attribute Holders
and applies them to the corresponding USD prims.

Reads:
  - USD_Kind: assembly, group, component, subcomponent, model
  - USD_Purpose: render, proxy, guide (skipped if default)
  - USD_Instanceable: true/false
  - USD_Hidden: true/false - Sets visibility to invisible
  - USD_Active: true/false - Sets prim active state
  - USD_AssetVersion: string - Adds to assetInfo
  - USD_DrawMode: bounds, origin, cards
  - USD_Payload: true/false - Written to customData for Assembler to read
"""

import maxUsd
from pxr import Usd, UsdGeom, Kind, Sdf
from pymxs import runtime as mxs
import traceback
import re

CHASER_VERSION = "3.9"


class USDPropertiesChaser(maxUsd.ExportChaser):

    def __init__(self, factoryContext, *args, **kwargs):
        super(USDPropertiesChaser, self).__init__(factoryContext, *args, **kwargs)
        self.primsToNodeHandles = factoryContext.GetPrimsToNodeHandles()
        self.stage = factoryContext.GetStage()

    def PostExport(self):
        print(f"--- USD Properties Chaser v{CHASER_VERSION} ---")

        # Step 1: Apply properties from USD Properties modifiers
        try:
            processed = 0
            for prim_path, node_handle in self.primsToNodeHandles.items():
                node = mxs.maxOps.getNodeByHandle(node_handle)
                if node is None:
                    continue
                prim = self.stage.GetPrimAtPath(prim_path)
                if not prim.IsValid():
                    continue
                usd_props_mod = self._get_usd_properties_modifier(node)
                if usd_props_mod is None:
                    continue

                self._apply_geom_type(prim, usd_props_mod)
                self._apply_kind(prim, usd_props_mod)
                self._apply_purpose(prim, usd_props_mod)
                self._apply_instanceable(prim, usd_props_mod)
                self._apply_hidden(prim, usd_props_mod)
                self._apply_active(prim, usd_props_mod)
                self._apply_asset_version(prim, usd_props_mod)
                self._apply_draw_mode(prim, usd_props_mod)
                self._apply_payload_flag(prim, usd_props_mod)
                processed += 1

            print(f"  Processed {processed} prim(s) with USD Properties")
        except Exception as e:
            print(f"  ERROR applying properties: {e}")
            print(traceback.format_exc())

        # Step 2: Apply purpose from name suffixes (_RENDER, _PROXY, _GUIDE)
        try:
            self._apply_suffix_purpose()
        except Exception as e:
            print(f"  ERROR applying suffix purpose: {e}")
            print(traceback.format_exc())

        # Step 3: Strip /root wrapper and remap paths
        try:
            self._strip_root_wrapper()
        except Exception as e:
            print(f"  ERROR stripping root: {e}")
            print(traceback.format_exc())

        # Step 4: Restructure _VARIANT children into VariantSets
        try:
            self._process_variants()
        except Exception as e:
            print(f"  ERROR processing variants: {e}")
            print(traceback.format_exc())

        print(f"--- USD Properties Chaser v{CHASER_VERSION} Complete ---")
        return True

    # -------------------------------------------------------------------------
    # Property application methods
    # -------------------------------------------------------------------------

    def _get_usd_properties_modifier(self, node):
        """Find the USD Properties modifier on a node."""
        try:
            for mod in node.modifiers:
                if mod.name == "USD Properties":
                    return mod
        except:
            pass
        return None

    def _apply_geom_type(self, prim, mod):
        """Store GeomType in customData for Stage Assembler to read."""
        try:
            geom_type_val = mod.USD_GeomType
            geom_type_map = {2: "Xform", 3: "Scope"}
            if geom_type_val in geom_type_map:
                prim.SetCustomDataByKey("geomType", geom_type_map[geom_type_val])
                print(f"    {prim.GetPath()}: GeomType = {geom_type_map[geom_type_val]}")
        except Exception as e:
            print(f"    Error setting GeomType: {e}")

    def _apply_kind(self, prim, mod):
        """Apply Kind from modifier to prim."""
        try:
            kind_val = mod.USD_Kind
            kind_map = {
                2: Kind.Tokens.assembly,
                3: Kind.Tokens.group,
                4: Kind.Tokens.component,
                5: Kind.Tokens.subcomponent,
                6: Kind.Tokens.model
            }
            if kind_val in kind_map:
                Usd.ModelAPI(prim).SetKind(kind_map[kind_val])
                print(f"    {prim.GetPath()}: Kind = {kind_map[kind_val]}")
        except Exception as e:
            print(f"    Error setting Kind: {e}")

    def _apply_purpose(self, prim, mod):
        """Apply Purpose from modifier to prim (only if not default)."""
        try:
            purpose_val = mod.USD_Purpose
            purpose_map = {
                2: UsdGeom.Tokens.render,
                3: UsdGeom.Tokens.proxy,
                4: UsdGeom.Tokens.guide
            }
            if purpose_val in purpose_map:
                imageable = UsdGeom.Imageable(prim)
                imageable.CreatePurposeAttr(purpose_map[purpose_val])
                print(f"    {prim.GetPath()}: Purpose = {purpose_map[purpose_val]}")
        except Exception as e:
            print(f"    Error setting Purpose: {e}")

    def _apply_instanceable(self, prim, mod):
        """Apply Instanceable from modifier to prim."""
        try:
            if mod.USD_Instanceable:
                prim.SetInstanceable(True)
                print(f"    {prim.GetPath()}: Instanceable = True")
        except Exception as e:
            print(f"    Error setting Instanceable: {e}")

    def _apply_hidden(self, prim, mod):
        """Apply Hidden (visibility) from modifier to prim."""
        try:
            if mod.USD_Hidden:
                imageable = UsdGeom.Imageable(prim)
                imageable.CreateVisibilityAttr(UsdGeom.Tokens.invisible)
                print(f"    {prim.GetPath()}: Visibility = invisible")
        except Exception as e:
            print(f"    Error setting Hidden: {e}")

    def _apply_active(self, prim, mod):
        """Apply Active state from modifier to prim."""
        try:
            if not mod.USD_Active:
                prim.SetActive(False)
                print(f"    {prim.GetPath()}: Active = False")
        except Exception as e:
            print(f"    Error setting Active: {e}")

    def _apply_asset_version(self, prim, mod):
        """Apply Asset Version from modifier to prim's assetInfo."""
        try:
            version = mod.USD_AssetVersion
            if version and str(version).strip():
                model = Usd.ModelAPI(prim)
                model.SetAssetVersion(str(version).strip())
                print(f"    {prim.GetPath()}: AssetVersion = {version}")
        except Exception as e:
            print(f"    Error setting AssetVersion: {e}")

    def _apply_draw_mode(self, prim, mod):
        """Apply Draw Mode from modifier to prim."""
        try:
            draw_mode_val = mod.USD_DrawMode
            if draw_mode_val > 1:
                geom_model = UsdGeom.ModelAPI.Apply(prim)
                draw_mode_map = {
                    2: UsdGeom.Tokens.bounds,
                    3: UsdGeom.Tokens.origin,
                    4: UsdGeom.Tokens.cards
                }
                if draw_mode_val in draw_mode_map:
                    geom_model.CreateModelDrawModeAttr(draw_mode_map[draw_mode_val])
                    print(f"    {prim.GetPath()}: DrawMode = {draw_mode_map[draw_mode_val]}")
        except Exception as e:
            print(f"    Error setting DrawMode: {e}")

    def _apply_payload_flag(self, prim, mod):
        """Store payload flag in customData for Stage Assembler to read."""
        try:
            if mod.USD_Payload:
                prim.SetCustomDataByKey("usePayload", True)
                print(f"    {prim.GetPath()}: Payload flag set")
        except Exception as e:
            print(f"    Error setting Payload flag: {e}")

    # -------------------------------------------------------------------------
    # Suffix-based purpose detection — applies to ALL prims, not just those
    # with USD Properties modifier
    # -------------------------------------------------------------------------

    def _apply_suffix_purpose(self):
        """
        Traverse all prims and apply USD Purpose based on name suffixes:
          _RENDER -> render
          _PROXY  -> proxy
          _GUIDE  -> guide
        Skips prims that already have an explicit purpose (set by Step 1).
        Also promotes unsuffixed siblings to purpose=render when a proxy/guide
        sibling exists (otherwise default prims stay visible in all modes).
        """
        suffix_map = {
            "_RENDER": UsdGeom.Tokens.render,
            "_PROXY": UsdGeom.Tokens.proxy,
            "_GUIDE": UsdGeom.Tokens.guide,
        }
        suffix_re = re.compile(r'^(.+?)_(RENDER|PROXY|GUIDE)$', re.IGNORECASE)

        # Pass 1: Apply purpose from suffixes, track which parents have purpose children
        applied = 0
        parents_with_purpose = {}  # parent_path -> set of base names
        for prim in self.stage.Traverse():
            imageable = UsdGeom.Imageable(prim)
            if not imageable:
                continue
            purpose_attr = imageable.GetPurposeAttr()
            if purpose_attr and purpose_attr.HasAuthoredValue():
                continue

            match = suffix_re.match(prim.GetName())
            if not match:
                continue

            base = match.group(1)
            suffix_key = "_" + match.group(2).upper()
            purpose_token = suffix_map[suffix_key]
            imageable.CreatePurposeAttr(purpose_token)
            print(f"    {prim.GetPath()}: Purpose = {purpose_token} (from suffix)")
            applied += 1

            parent = prim.GetParent()
            if parent and not parent.IsPseudoRoot():
                pkey = str(parent.GetPath())
                if pkey not in parents_with_purpose:
                    parents_with_purpose[pkey] = set()
                parents_with_purpose[pkey].add(base)

        # Pass 2: Promote unsuffixed siblings to render purpose
        promoted = 0
        for parent_path_str, base_names in parents_with_purpose.items():
            parent_prim = self.stage.GetPrimAtPath(parent_path_str)
            if not parent_prim or not parent_prim.IsValid():
                continue
            for child in parent_prim.GetChildren():
                if child.GetName() not in base_names:
                    continue
                imageable = UsdGeom.Imageable(child)
                if not imageable:
                    continue
                purpose_attr = imageable.GetPurposeAttr()
                if purpose_attr and purpose_attr.HasAuthoredValue():
                    continue
                imageable.CreatePurposeAttr(UsdGeom.Tokens.render)
                print(f"    {child.GetPath()}: Purpose = render (sibling has proxy/guide)")
                promoted += 1

        print(f"  Applied suffix purpose to {applied} prim(s), promoted {promoted} to render")

        # Pass 3: Restructure purpose groups under intermediate Xforms
        # e.g. Torus + Torus_PROXY -> Torus [Xform] / Torus [render] + Torus_PROXY [proxy]
        layer = self.stage.GetRootLayer()
        grouped = 0
        for parent_path_str, base_names in parents_with_purpose.items():
            parent_path = Sdf.Path(parent_path_str)
            for base in base_names:
                # Collect all prims in this purpose group
                members = []  # (prim_name, prim_path)
                base_upper = base.upper()
                parent_prim = self.stage.GetPrimAtPath(parent_path)
                if not parent_prim or not parent_prim.IsValid():
                    continue
                for child in parent_prim.GetChildren():
                    name = child.GetName()
                    name_upper = name.upper()
                    if name_upper == base_upper:
                        members.append((name, child.GetPath()))
                    elif suffix_re.match(name) and suffix_re.match(name).group(1).upper() == base_upper:
                        members.append((name, child.GetPath()))

                if len(members) < 2:
                    continue

                group_path = parent_path.AppendChild(base)

                # Copy all members to temp locations
                temps = []
                for name, src_path in members:
                    tmp_name = f"__purpose_tmp_{name}"
                    tmp_path = parent_path.AppendChild(tmp_name)
                    Sdf.CopySpec(layer, src_path, layer, tmp_path)
                    temps.append((name, tmp_path))

                # Remove originals (including the base prim at group_path)
                for _, src_path in members:
                    self.stage.RemovePrim(src_path)

                # Create intermediate Xform
                UsdGeom.Xform.Define(self.stage, group_path)

                # Move temps as children of the new Xform
                for name, tmp_path in temps:
                    dst_path = group_path.AppendChild(name)
                    Sdf.CopySpec(layer, tmp_path, layer, dst_path)
                    self.stage.RemovePrim(tmp_path)

                grouped += len(members)
                print(f"    Grouped {len(members)} prims under {group_path}")

        if grouped:
            print(f"  Restructured {grouped} prim(s) into purpose groups")

    # -------------------------------------------------------------------------
    # Root stripping — uses BatchNamespaceEdit to MOVE prims (not copy+delete)
    # This preserves all binary data including MaxUSD instance encoding
    # -------------------------------------------------------------------------

    def _strip_root_wrapper(self):
        """
        Strip MaxUSD's /root wrapper using Sdf.BatchNamespaceEdit.
        This MOVES prims instead of copy+delete, preserving all binary data
        including MaxUSD's instance encoding and composition arcs.
        BatchNamespaceEdit also auto-updates all internal path references.
        """
        layer = self.stage.GetRootLayer()
        root_spec = layer.GetPrimAtPath("/root")
        if not root_spec:
            print("  No /root spec in root layer, skipping strip")
            return

        # Find the deepest /root/root/... wrapper via layer specs
        current_path = Sdf.Path("/root")
        while True:
            spec = layer.GetPrimAtPath(current_path)
            child_names = [c.name for c in spec.nameChildren]
            if len(child_names) == 1 and child_names[0] == "root":
                current_path = current_path.AppendChild("root")
            else:
                break

        # Collect children from the layer spec (includes class/abstract prims)
        wrapper_spec = layer.GetPrimAtPath(current_path)
        all_children = list(wrapper_spec.nameChildren)
        if not all_children:
            print("  No children under root wrapper, skipping")
            return

        root_prim = self.stage.GetPrimAtPath("/root")
        keep_skel_root = bool(root_prim and root_prim.IsValid() and root_prim.GetTypeName() == "SkelRoot")
        if keep_skel_root:
            self._flatten_scene_wrapper_under_skel_root(layer, current_path)
            return

        # Separate content from materials
        mtl_scope_names = {"mtl", "Looks", "Materials"}
        main_children = []
        content_children = []
        mtl_children = []
        for child_spec in all_children:
            name = child_spec.name
            if name in mtl_scope_names:
                mtl_children.append(name)
            else:
                main_children.append(name)
                if child_spec.specifier != Sdf.SpecifierClass and not name.startswith("_class_"):
                    content_children.append(name)

        if not main_children:
            print("  No main content children found")
            return

        default_name = content_children[0] if content_children else main_children[0]
        nest_mtl = len(content_children) == 1 and len(mtl_children) > 0
        if not content_children:
            print("  WARNING: No concrete content prim found; defaultPrim falls back to first non-material child")

        print(f"  Strip: {current_path} -> /")
        print(f"  Content: {main_children}, Mtl: {mtl_children}")
        print(f"  nest_mtl={nest_mtl}, defaultPrim={default_name}")

        # Build namespace edit to move all children out of /root
        edit = Sdf.BatchNamespaceEdit()

        for name in main_children:
            src = current_path.AppendChild(name)
            dst = Sdf.Path("/" + name)
            edit.Add(src, dst)
            print(f"    Move {src} -> {dst}")

        if nest_mtl:
            for name in mtl_children:
                src = current_path.AppendChild(name)
                dst = Sdf.Path("/" + default_name + "/" + name)
                edit.Add(src, dst)
                print(f"    Move {src} -> {dst} (nested)")
        else:
            for name in mtl_children:
                src = current_path.AppendChild(name)
                dst = Sdf.Path("/" + name)
                edit.Add(src, dst)
                print(f"    Move {src} -> {dst}")

        # Apply the namespace edit — moves prims but does NOT remap relationship targets
        if layer.Apply(edit):
            print("    BatchNamespaceEdit applied OK")
        else:
            print("    BatchNamespaceEdit FAILED — falling back to CopySpec")
            self._strip_root_fallback(layer, current_path, main_children, mtl_children,
                                      default_name, nest_mtl)

        # Set defaultPrim BEFORE removing /root so it always happens
        layer.defaultPrim = default_name
        print(f"  defaultPrim = {default_name}")

        # Remove the now-empty /root wrapper
        try:
            root_spec = layer.GetPrimAtPath("/root")
            if root_spec:
                del layer.rootPrims["root"]
                print("    Removed empty /root")
        except Exception as e:
            print(f"    Could not remove /root: {e}")

        # Remap relationship targets and attribute connections (BatchNamespaceEdit doesn't do this)
        strip_prefix = str(current_path)
        mtl_names = [n for n in mtl_children]
        nest_target = default_name if nest_mtl else None
        remapped = self._remap_paths_in_place(strip_prefix, nest_target, mtl_names)
        if remapped:
            print(f"    Remapped {remapped} path(s)")
        remapped_specs = self._remap_primspec_path_lists(layer, strip_prefix, nest_target, mtl_names)
        if remapped_specs:
            print(f"    Remapped class/inherit arcs on {remapped_specs} prim spec(s)")
        remapped_joint_attrs, remapped_joint_tokens = self._remap_skeleton_joint_tokens(
            strip_prefix, nest_target, mtl_names, default_name
        )
        if remapped_joint_attrs:
            print(f"    Remapped skel:joints on {remapped_joint_attrs} prim(s), {remapped_joint_tokens} token(s)")

    def _move_children_to_parent(self, layer, src_parent_path, dst_parent_path):
        """
        Move all direct children from src parent to dst parent using BatchNamespaceEdit,
        with CopySpec fallback.
        """
        src_spec = layer.GetPrimAtPath(src_parent_path)
        if not src_spec:
            return []

        child_names = [c.name for c in src_spec.nameChildren]
        if not child_names:
            return []

        edit = Sdf.BatchNamespaceEdit()
        for child_name in child_names:
            src = src_parent_path.AppendChild(child_name)
            dst = dst_parent_path.AppendChild(child_name)
            if src != dst:
                edit.Add(src, dst)
                print(f"    Move {src} -> {dst}")

        if layer.Apply(edit):
            print("    BatchNamespaceEdit applied OK")
            return child_names

        print("    BatchNamespaceEdit FAILED — falling back to CopySpec")
        moved = []
        for child_name in child_names:
            src = src_parent_path.AppendChild(child_name)
            dst = dst_parent_path.AppendChild(child_name)
            ok = Sdf.CopySpec(layer, src, layer, dst)
            if ok:
                self.stage.RemovePrim(src)
                moved.append(child_name)
        return moved

    def _flatten_scene_wrapper_under_skel_root(self, layer, current_path):
        """
        Skeletal exports must keep /root as SkelRoot.
        If /root/Scene_* wraps the actual character, flatten that wrapper into /root.
        """
        root_path = Sdf.Path("/root")
        mtl_scope_names = {"mtl", "Looks", "Materials"}

        if str(current_path) != "/root":
            print(f"  SkelRoot mode: collapse {current_path} -> /root")
            self._move_children_to_parent(layer, current_path, root_path)
            try:
                self.stage.RemovePrim(current_path)
            except Exception as e:
                print(f"    Could not remove nested wrapper {current_path}: {e}")

        root_spec = layer.GetPrimAtPath(root_path)
        if not root_spec:
            print("  Missing /root spec after SkelRoot collapse, skipping")
            return

        root_children = list(root_spec.nameChildren)
        if not root_children:
            print("  No children under /root, keeping SkelRoot unchanged")
            layer.defaultPrim = "root"
            return

        has_skeleton_scope = False
        content_candidates = []
        for child_spec in root_children:
            child_name = child_spec.name
            child_path = root_path.AppendChild(child_name)
            child_prim = self.stage.GetPrimAtPath(child_path)
            child_type = child_prim.GetTypeName() if child_prim and child_prim.IsValid() else ""

            if child_name == "Bones" or child_type == "Skeleton":
                has_skeleton_scope = True

            if child_name in mtl_scope_names or child_name == "Bones" or child_name == "root":
                continue
            if child_type == "Skeleton":
                continue
            if child_spec.specifier == Sdf.SpecifierClass or child_name.startswith("_class_"):
                continue
            content_candidates.append(child_name)

        scene_wrapper_name = None
        if has_skeleton_scope and len(content_candidates) == 1:
            candidate = content_candidates[0]
            candidate_spec = layer.GetPrimAtPath(root_path.AppendChild(candidate))
            candidate_children = list(candidate_spec.nameChildren) if candidate_spec else []
            is_scene_wrapper = bool(re.match(r"^scene($|_)", candidate, re.IGNORECASE))
            if is_scene_wrapper and candidate_children:
                scene_wrapper_name = candidate

        if scene_wrapper_name:
            scene_path = root_path.AppendChild(scene_wrapper_name)
            print(f"  SkelRoot mode: flatten {scene_path} -> /root")
            moved_children = self._move_children_to_parent(layer, scene_path, root_path)

            try:
                self.stage.RemovePrim(scene_path)
                print(f"    Removed {scene_path}")
            except Exception as e:
                print(f"    Could not remove scene wrapper {scene_path}: {e}")

            if moved_children:
                strip_prefix = str(scene_path)
                remapped = self._remap_paths_in_place(
                    strip_prefix, None, [], replacement_prefix="/root"
                )
                if remapped:
                    print(f"    Remapped {remapped} path(s)")
                remapped_specs = self._remap_primspec_path_lists(
                    layer, strip_prefix, None, [], replacement_prefix="/root"
                )
                if remapped_specs:
                    print(f"    Remapped class/inherit arcs on {remapped_specs} prim spec(s)")
                remapped_joint_attrs, remapped_joint_tokens = self._remap_skeleton_joint_tokens(
                    strip_prefix,
                    None,
                    [],
                    None,
                    replacement_prefix="/root",
                    relative_strip_prefix=scene_wrapper_name
                )
                if remapped_joint_attrs:
                    print(f"    Remapped skel:joints on {remapped_joint_attrs} prim(s), {remapped_joint_tokens} token(s)")

        # Deterministic hardening for skeletal exports.
        self._harden_skeleton_bindings(scene_wrapper_name)

        layer.defaultPrim = "root"
        print("  defaultPrim = root (SkelRoot)")

    def _normalize_joint_token(self, token_str, scene_wrapper_name=None, character_root_name=None):
        """
        Normalize joint token to a stable relative path form used by MaxUSD:
        Character/... (without /root or scene wrapper prefixes).
        """
        token = str(token_str)
        if not token:
            return token

        work = token.lstrip("/")

        if work.startswith("root/"):
            work = work[len("root/"):]

        if scene_wrapper_name:
            wrapper = scene_wrapper_name.strip("/")
            wrapper_prefix = wrapper + "/"
            if work.startswith(wrapper_prefix):
                work = work[len(wrapper_prefix):]
            else:
                marker = "/" + wrapper_prefix
                idx = work.find(marker)
                if idx != -1:
                    work = work[idx + len(marker):]

        if character_root_name:
            marker = character_root_name + "/"
            if work != character_root_name and not work.startswith(marker):
                idx = work.find(marker)
                if idx != -1:
                    work = work[idx:]

        return work if work else token.lstrip("/")

    def _harden_skeleton_bindings(self, scene_wrapper_name=None):
        """
        Hardening pass for skeletal exports:
          1) Skeleton rel skel:animationSource -> /root/Bones/Animations (or first valid)
          2) Skinned prim rel skel:skeleton -> /root/Bones (or chosen skeleton)
          3) Normalize token[] joints to relative Character/... style
        """
        root_prim = self.stage.GetPrimAtPath("/root")
        if not root_prim or not root_prim.IsValid():
            print("  Hardening skipped: /root not found")
            return

        skeleton_candidates = []
        for child in root_prim.GetChildren():
            if child.GetTypeName() == "Skeleton":
                skeleton_candidates.append(child)

        if not skeleton_candidates:
            for prim in self.stage.TraverseAll():
                if prim.GetTypeName() == "Skeleton" and str(prim.GetPath()).startswith("/root/"):
                    skeleton_candidates.append(prim)

        if not skeleton_candidates:
            print("  Hardening skipped: no Skeleton under /root")
            return

        skeleton_prim = None
        for sk in skeleton_candidates:
            if sk.GetName() == "Bones":
                skeleton_prim = sk
                break
        if skeleton_prim is None:
            skeleton_prim = skeleton_candidates[0]

        skeleton_path = skeleton_prim.GetPath()

        anim_prim = None
        for child in skeleton_prim.GetChildren():
            if child.GetTypeName() == "SkelAnimation" and child.GetName() == "Animations":
                anim_prim = child
                break
        if anim_prim is None:
            for child in skeleton_prim.GetChildren():
                if child.GetTypeName() == "SkelAnimation":
                    anim_prim = child
                    break

        if anim_prim and anim_prim.IsValid():
            anim_rel = skeleton_prim.GetRelationship("skel:animationSource")
            if not anim_rel:
                anim_rel = skeleton_prim.CreateRelationship("skel:animationSource", False)
            anim_rel.SetTargets([anim_prim.GetPath()])
            print(f"    Hardened skel:animationSource = {anim_prim.GetPath()}")

        character_root_name = None
        for child in root_prim.GetChildren():
            name = child.GetName()
            type_name = child.GetTypeName()
            if name in {"Bones", "mtl", "Looks", "Materials", "root"}:
                continue
            if type_name == "Skeleton":
                continue
            character_root_name = name
            break

        hardened_skel_rels = 0
        normalized_joint_attrs = 0
        normalized_joint_tokens = 0

        joint_attr_names = {"skel:joints", "joints"}
        for prim in self.stage.TraverseAll():
            prim_path_str = str(prim.GetPath())
            if not prim_path_str.startswith("/root/"):
                continue

            has_skinning = (
                prim.HasAttribute("primvars:skel:jointIndices")
                or prim.HasAttribute("primvars:skel:jointWeights")
                or prim.HasAttribute("skel:joints")
            )

            if has_skinning:
                skel_rel = prim.GetRelationship("skel:skeleton")
                if not skel_rel:
                    skel_rel = prim.CreateRelationship("skel:skeleton", False)
                skel_rel.SetTargets([skeleton_path])
                hardened_skel_rels += 1

            for attr in prim.GetAttributes():
                if attr.GetName() not in joint_attr_names:
                    continue
                if str(attr.GetTypeName()) != "token[]":
                    continue

                tokens = attr.Get()
                if not tokens:
                    continue

                new_tokens = []
                changed = False
                for token in tokens:
                    new_token = self._normalize_joint_token(
                        token,
                        scene_wrapper_name=scene_wrapper_name,
                        character_root_name=character_root_name
                    )
                    new_tokens.append(new_token)
                    if new_token != str(token):
                        changed = True
                        normalized_joint_tokens += 1

                if changed:
                    attr.Set(new_tokens)
                    normalized_joint_attrs += 1

        if hardened_skel_rels:
            print(f"    Hardened skel:skeleton on {hardened_skel_rels} prim(s) -> {skeleton_path}")
        if normalized_joint_attrs:
            print(f"    Normalized joint tokens on {normalized_joint_attrs} prim(s), {normalized_joint_tokens} token(s)")

    def _strip_root_fallback(self, layer, wrapper_path, main_children, mtl_children,
                             default_name, nest_mtl):
        """Fallback: CopySpec + RemovePrim + stage-level path remap if BatchNamespaceEdit fails."""
        print("    Using CopySpec fallback (instances may lose data)")

        for name in main_children:
            src = wrapper_path.AppendChild(name)
            dst = Sdf.Path("/" + name)
            Sdf.CopySpec(layer, src, layer, dst)

        mtl_nested_ok = False
        if nest_mtl:
            for name in mtl_children:
                src = wrapper_path.AppendChild(name)
                dst = Sdf.Path("/" + default_name + "/" + name)
                ok = Sdf.CopySpec(layer, src, layer, dst)
                if ok:
                    mtl_nested_ok = True
                else:
                    Sdf.CopySpec(layer, src, layer, Sdf.Path("/" + name))
        else:
            for name in mtl_children:
                src = wrapper_path.AppendChild(name)
                Sdf.CopySpec(layer, src, layer, Sdf.Path("/" + name))

        self.stage.RemovePrim(Sdf.Path("/root"))

        # Remap paths via stage API
        strip_prefix = str(wrapper_path)
        nest_target = default_name if mtl_nested_ok else None
        self._remap_paths_in_place(strip_prefix, nest_target, mtl_children)
        self._remap_primspec_path_lists(layer, strip_prefix, nest_target, mtl_children)
        self._remap_skeleton_joint_tokens(strip_prefix, nest_target, mtl_children, default_name)

    def _remap_path_str(self, path_str, strip_prefix, nest_target, mtl_names, replacement_prefix=None):
        """Compute new path string. Returns remapped string or None if unchanged."""
        if nest_target and mtl_names:
            for mtl_name in mtl_names:
                mtl_prefix = strip_prefix + "/" + mtl_name
                if path_str.startswith(mtl_prefix + "/") or path_str == mtl_prefix:
                    return "/" + nest_target + "/" + mtl_name + path_str[len(mtl_prefix):]
        if path_str.startswith(strip_prefix + "/"):
            suffix = path_str[len(strip_prefix):]
            if replacement_prefix is None:
                return suffix
            if replacement_prefix == "/":
                return suffix
            return replacement_prefix.rstrip("/") + suffix
        if path_str == strip_prefix:
            if replacement_prefix is not None:
                return replacement_prefix if replacement_prefix else "/"
            return "/"
        return None

    def _remap_paths_in_place(self, strip_prefix, nest_target, mtl_names, replacement_prefix=None):
        """Remap paths using Usd Stage API. Fallback for when BatchNamespaceEdit fails."""
        remapped = 0
        for prim in self.stage.TraverseAll():
            for rel in prim.GetRelationships():
                targets = rel.GetTargets()
                if not targets:
                    continue
                new_targets = []
                changed = False
                for t in targets:
                    new_str = self._remap_path_str(
                        str(t), strip_prefix, nest_target, mtl_names, replacement_prefix
                    )
                    if new_str is not None:
                        new_targets.append(Sdf.Path(new_str))
                        changed = True
                    else:
                        new_targets.append(t)
                if changed:
                    rel.SetTargets(new_targets)
                    remapped += 1

            for attr in prim.GetAttributes():
                connections = attr.GetConnections()
                if not connections:
                    continue
                new_conns = []
                changed = False
                for c in connections:
                    new_str = self._remap_path_str(
                        str(c), strip_prefix, nest_target, mtl_names, replacement_prefix
                    )
                    if new_str is not None:
                        new_conns.append(Sdf.Path(new_str))
                        changed = True
                    else:
                        new_conns.append(c)
                if changed:
                    attr.SetConnections(new_conns)
                    remapped += 1
        return remapped

    def _iter_prim_specs(self, prim_spec):
        """Depth-first traversal of layer prim specs, including class prims."""
        yield prim_spec
        for child_spec in prim_spec.nameChildren:
            for nested in self._iter_prim_specs(child_spec):
                yield nested

    def _remap_path_list_op(self, path_list_op, strip_prefix, nest_target, mtl_names, replacement_prefix=None):
        """Remap all items in an Sdf path list-op. Returns True if any item changed."""
        changed_any = False
        for field_name in ("explicitItems", "addedItems", "prependedItems", "appendedItems", "deletedItems"):
            try:
                items = list(getattr(path_list_op, field_name))
            except Exception:
                continue
            if not items:
                continue

            remapped_items = []
            changed_field = False
            for item in items:
                new_str = self._remap_path_str(
                    str(item), strip_prefix, nest_target, mtl_names, replacement_prefix
                )
                if new_str is not None:
                    remapped_items.append(Sdf.Path(new_str))
                    changed_field = True
                else:
                    remapped_items.append(item)

            if changed_field:
                setattr(path_list_op, field_name, remapped_items)
                changed_any = True

        return changed_any

    def _clone_reference_like_item(self, item, new_path):
        """
        Clone an Sdf.Reference or Sdf.Payload with a remapped prim path.
        Keeps assetPath/layerOffset/customData intact.
        """
        item_type_name = type(item).__name__
        if item_type_name == "Reference":
            return Sdf.Reference(
                assetPath=item.assetPath,
                primPath=Sdf.Path(new_path),
                layerOffset=item.layerOffset,
                customData=item.customData
            )

        if item_type_name == "Payload":
            return Sdf.Payload(
                assetPath=item.assetPath,
                primPath=Sdf.Path(new_path),
                layerOffset=item.layerOffset
            )

        return None

    def _remap_reference_like_list_op(self, list_op, strip_prefix, nest_target, mtl_names, replacement_prefix=None):
        """
        Remap primPath on Sdf.ReferenceListOp / Sdf.PayloadListOp items.
        This is required because BatchNamespaceEdit does not rewrite internal
        composition arcs authored as references/payloads.
        """
        changed_any = False
        for field_name in ("explicitItems", "addedItems", "prependedItems", "appendedItems", "deletedItems"):
            try:
                items = list(getattr(list_op, field_name))
            except Exception:
                continue
            if not items:
                continue

            remapped_items = []
            changed_field = False
            for item in items:
                prim_path = getattr(item, "primPath", None)
                prim_path_str = str(prim_path) if prim_path else ""
                if not prim_path_str:
                    remapped_items.append(item)
                    continue

                new_str = self._remap_path_str(
                    prim_path_str, strip_prefix, nest_target, mtl_names, replacement_prefix
                )
                if new_str is None:
                    remapped_items.append(item)
                    continue

                cloned = self._clone_reference_like_item(item, new_str)
                if cloned is None:
                    remapped_items.append(item)
                    continue

                remapped_items.append(cloned)
                changed_field = True

            if changed_field:
                setattr(list_op, field_name, remapped_items)
                changed_any = True

        return changed_any

    def _remap_primspec_path_lists(self, layer, strip_prefix, nest_target, mtl_names, replacement_prefix=None):
        """
        Remap prim-spec path list-ops that BatchNamespaceEdit can leave stale,
        especially inherit/specialize arcs and internal reference/payload arcs
        used by MaxUSD material networks and class-based instances.
        """
        remapped_specs = 0
        for root_spec in layer.rootPrims:
            for prim_spec in self._iter_prim_specs(root_spec):
                changed_spec = False
                for list_name in ("inheritPathList", "specializesList"):
                    try:
                        list_op = getattr(prim_spec, list_name)
                    except Exception:
                        list_op = None
                    if not list_op:
                        continue
                    if self._remap_path_list_op(
                        list_op, strip_prefix, nest_target, mtl_names, replacement_prefix
                    ):
                        changed_spec = True

                for list_name in ("referenceList", "payloadList"):
                    try:
                        list_op = getattr(prim_spec, list_name)
                    except Exception:
                        list_op = None
                    if not list_op:
                        continue
                    if self._remap_reference_like_list_op(
                        list_op, strip_prefix, nest_target, mtl_names, replacement_prefix
                    ):
                        changed_spec = True

                if changed_spec:
                    remapped_specs += 1

        return remapped_specs

    def _format_joint_token_path(self, path_str, had_leading_slash):
        """Return token with original absolute/relative style."""
        if had_leading_slash:
            return path_str
        return path_str.lstrip("/")

    def _remap_skeleton_joint_token(
        self,
        token_str,
        strip_prefix,
        nest_target,
        mtl_names,
        content_root,
        replacement_prefix=None,
        relative_strip_prefix=None
    ):
        """
        Remap a single skeleton joint token. Tries the same root-strip/material remap
        flow first, then prefixes the content root (e.g. Scene_Example/) only when a
        matching prim exists at that prefixed path.
        """
        token = str(token_str)
        if not token:
            return token

        had_leading_slash = token.startswith("/")

        # 1) Reuse existing path remapper (supports moved mtl scopes and stripped /root).
        remapped = self._remap_path_str(token, strip_prefix, nest_target, mtl_names, replacement_prefix)
        if remapped is None and not had_leading_slash:
            remapped = self._remap_path_str("/" + token, strip_prefix, nest_target, mtl_names, replacement_prefix)
        if remapped is None and not had_leading_slash and relative_strip_prefix:
            rel_prefix = relative_strip_prefix.strip("/")
            if token.startswith(rel_prefix + "/"):
                remapped = token[len(rel_prefix) + 1:]
        if remapped is not None:
            return self._format_joint_token_path(remapped, had_leading_slash)

        # 2) If token points to a missing prim, try prefixing content root.
        if not content_root:
            return token

        token_abs = token if had_leading_slash else "/" + token
        if self.stage.GetPrimAtPath(token_abs).IsValid():
            return token

        prefixed_abs = "/" + content_root + token_abs
        if self.stage.GetPrimAtPath(prefixed_abs).IsValid():
            return self._format_joint_token_path(prefixed_abs, had_leading_slash)

        return token

    def _remap_skeleton_joint_tokens(
        self,
        strip_prefix,
        nest_target,
        mtl_names,
        content_root,
        replacement_prefix=None,
        relative_strip_prefix=None
    ):
        """Remap token[] joints authored on skeleton-related prims."""
        remapped_attrs = 0
        remapped_tokens = 0
        joint_attr_names = {"skel:joints", "joints"}

        for prim in self.stage.TraverseAll():
            for attr in prim.GetAttributes():
                attr_name = attr.GetName()
                if attr_name not in joint_attr_names:
                    continue
                if str(attr.GetTypeName()) != "token[]":
                    continue

                tokens = attr.Get()
                if not tokens:
                    continue

                new_tokens = []
                changed = False
                for token in tokens:
                    new_token = self._remap_skeleton_joint_token(
                        token,
                        strip_prefix,
                        nest_target,
                        mtl_names,
                        content_root,
                        replacement_prefix,
                        relative_strip_prefix
                    )
                    new_tokens.append(new_token)
                    if new_token != str(token):
                        changed = True
                        remapped_tokens += 1

                if changed:
                    attr.Set(new_tokens)
                    remapped_attrs += 1

        return remapped_attrs, remapped_tokens

    # -------------------------------------------------------------------------
    # Variant processing
    # -------------------------------------------------------------------------

    def _process_variants(self):
        """
        Detect _VARIANT* children and restructure into USD VariantSets.

        Creates an intermediate Xform with the base name and places the
        VariantSet on it, so non-variant siblings are unaffected.

        Before: /Assembly/Teapot_VARIANTA, /Assembly/Teapot_VARIANTB, /Assembly/Table
        After:  /Assembly/Teapot {modelVariant={A,B}}, /Assembly/Table
        """
        layer = self.stage.GetRootLayer()

        # Collect variant children grouped by (parent_path, base_name)
        variant_groups = {}
        for prim in self.stage.Traverse():
            match = re.match(r'^(.+?)_VARIANT(\w*)$', prim.GetName(), re.IGNORECASE)
            if not match:
                continue
            parent = prim.GetParent()
            if not parent or parent.IsPseudoRoot():
                continue
            base = match.group(1)
            var_name = match.group(2) if match.group(2) else "1"
            key = (str(parent.GetPath()), base)
            if key not in variant_groups:
                variant_groups[key] = []
            variant_groups[key].append((var_name, prim.GetPath()))

        if not variant_groups:
            print("  No _VARIANT children found")
            return

        for (parent_path_str, base_name), variants in variant_groups.items():
            if len(variants) < 2:
                print(f"  Skipping '{base_name}' at {parent_path_str}: only {len(variants)} variant(s)")
                continue

            parent_path = Sdf.Path(parent_path_str)
            parent_spec = layer.GetPrimAtPath(parent_path)
            if not parent_spec:
                print(f"  No spec for {parent_path} in root layer, skipping variants")
                continue

            parent_prim = self.stage.GetPrimAtPath(parent_path)
            if not parent_prim or not parent_prim.IsValid():
                print(f"  Invalid prim at {parent_path}, skipping variants")
                continue

            # Create intermediate Xform for the variant group
            group_path = parent_path.AppendChild(base_name)
            group_prim = UsdGeom.Xform.Define(self.stage, group_path).GetPrim()

            print(f"  VariantSet '{base_name}' on {group_path} ({len(variants)} variants)")

            # Create VariantSet on the intermediate prim
            variant_set = group_prim.GetVariantSets().AddVariantSet("modelVariant")

            first_var = None
            for var_name, child_path in variants:
                if first_var is None:
                    first_var = var_name

                variant_set.AddVariant(var_name)
                variant_sel_path = group_path.AppendVariantSelection("modelVariant", var_name)
                dst_path = variant_sel_path.AppendChild(base_name)
                ok = Sdf.CopySpec(layer, child_path, layer, dst_path)
                print(f"    {{{var_name}}} <- {child_path}: {'OK' if ok else 'FAIL'}")

            # Remove original _VARIANT children
            for _, child_path in variants:
                self.stage.RemovePrim(child_path)
                print(f"    Removed {child_path}")

            # Set default to first variant
            variant_set.SetVariantSelection(first_var)
            print(f"    Default variant: {first_var}")


# Register the chaser
maxUsd.ExportChaser.Register(
    USDPropertiesChaser,
    "usdProperties",
    "USD Properties",
    "Applies Kind, Purpose, Instanceable, Hidden, Active, AssetVersion, DrawMode, Payload from Attribute Holders"
)


def usdPropertiesContext():
    extraArgs = {}
    extraArgs['chaser'] = ['usdProperties']
    extraArgs['chaserNames'] = ['usdProperties']
    return extraArgs


registeredContexts = maxUsd.JobContextRegistry.ListJobContexts()
if 'usdPropertiesContext' not in registeredContexts:
    maxUsd.JobContextRegistry.RegisterExportJobContext(
        "usdPropertiesContext",
        "USD Properties",
        "Applies USD properties from Attribute Holders",
        usdPropertiesContext
    )


print(f"Registered USD Properties Chaser v{CHASER_VERSION}")
