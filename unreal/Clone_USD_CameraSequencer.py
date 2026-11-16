"""
Clone USD Camera Sequencer
Reads _camera_sequence.json and builds a Camera Cut Track in Unreal Sequencer.

Finds cameras as child actors under the UsdStageActor, binds them to the
root Level Sequence, and creates the Camera Cut Track.

Usage:
    Run in Unreal Editor Python console after importing a USD stage.
"""

import unreal
import json
import os


def find_camera_sequence_json():
    """Find the _camera_sequence.json path. Tries auto-detect, then file picker."""
    explicit = globals().get("_camera_sequence_path")
    if explicit and os.path.isfile(explicit):
        return explicit

    actor_subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    all_actors = actor_subsystem.get_all_level_actors()

    for actor in all_actors:
        if actor.get_class().get_name() == "UsdStageActor":
            root_layer = actor.get_editor_property("root_layer")
            # root_layer is a FilePath struct; str() gives its struct text, not the path
            layer_path = getattr(root_layer, "file_path", None) or (root_layer if isinstance(root_layer, str) else "")
            if layer_path:
                stage_dir = os.path.dirname(layer_path)
                json_path = os.path.join(stage_dir, "_camera_sequence.json")
                if os.path.isfile(json_path):
                    return json_path

    # Fallback: file picker
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        picked = filedialog.askopenfilename(
            title="Select _camera_sequence.json",
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")]
        )
        root.destroy()
        if picked and os.path.isfile(picked):
            return picked
    except Exception:
        pass

    unreal.log_warning("Clone_USD_CameraSequencer: No file selected.")
    return None


def find_level_sequence():
    """Find the Level Sequence from UsdStageActor or currently open Sequencer."""
    actor_subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    all_actors = actor_subsystem.get_all_level_actors()

    for actor in all_actors:
        if actor.get_class().get_name() == "UsdStageActor":
            seq = actor.get_editor_property("level_sequence")
            if seq:
                return seq

    ls_subsystem = unreal.get_editor_subsystem(unreal.LevelSequenceEditorSubsystem)
    if ls_subsystem:
        current = ls_subsystem.get_current_level_sequence()
        if current:
            return current

    return None


def find_camera_actors(camera_names):
    """Find camera actors by name. Searches all actors including UsdStageActor children."""
    world = unreal.EditorLevelLibrary.get_editor_world()

    # Get ALL CineCameraActors in the world (catches procedurally spawned ones too)
    all_cams = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.CineCameraActor)

    # Also try regular CameraActor
    all_cams = list(all_cams)
    all_cams += list(unreal.GameplayStatics.get_all_actors_of_class(world, unreal.CameraActor))

    unreal.log("  All cameras in world ({} total):".format(len(all_cams)))
    for a in all_cams:
        unreal.log("    label='{}' name='{}' class='{}'".format(
            a.get_actor_label(), a.get_name(), a.get_class().get_name()))

    camera_map = {}
    for actor in all_cams:
        label = str(actor.get_actor_label())
        name = str(actor.get_name())

        for cam_name in camera_names:
            if cam_name not in camera_map:
                if cam_name == label or cam_name == name:
                    camera_map[cam_name] = actor
                elif cam_name in label or cam_name in name or label in cam_name or name in cam_name:
                    camera_map[cam_name] = actor

    return camera_map


def build_camera_cut_track(sequence, sequence_data):
    """Build the Camera Cut Track from sequence data."""
    entries = sequence_data.get("sequence", [])

    if not entries:
        unreal.log_warning("Clone_USD_CameraSequencer: No camera entries in sequence data.")
        return False

    # FPS conversion: JSON frames are at source fps, Sequencer may run at different rate
    source_fps = float(sequence_data.get("fps", 30))
    display_rate = sequence.get_display_rate()
    seq_fps = float(display_rate.numerator) / max(float(display_rate.denominator), 1.0)
    fps_scale = seq_fps / source_fps if source_fps > 0 else 1.0

    unreal.log("  Source FPS: {}, Sequencer FPS: {}, Scale: {:.3f}".format(
        source_fps, seq_fps, fps_scale))

    camera_names = list(set(e["camera"] for e in entries))
    camera_actors = find_camera_actors(camera_names)

    if not camera_actors:
        unreal.log_error("Clone_USD_CameraSequencer: No matching cameras found.")
        unreal.log_error("  Looking for: {}".format(camera_names))
        return False

    found = list(camera_actors.keys())
    missing = [n for n in camera_names if n not in camera_actors]
    unreal.log("  Matched: {}".format(found))
    if missing:
        unreal.log_warning("  Missing: {}".format(missing))

    # Remove existing camera cut track
    existing = sequence.find_tracks_by_type(unreal.MovieSceneCameraCutTrack)
    for track in existing:
        sequence.remove_track(track)

    # Create new camera cut track
    camera_cut_track = sequence.add_track(unreal.MovieSceneCameraCutTrack)

    # Add possessable bindings for each camera
    binding_map = {}
    for cam_name, actor in camera_actors.items():
        binding = sequence.add_possessable(actor)
        binding_map[cam_name] = binding
        unreal.log("  Bound '{}' -> binding ID: {}".format(cam_name, binding.get_id()))

    # Create cut sections (convert frames from source fps to sequencer fps)
    for entry in entries:
        cam_name = entry["camera"]
        start_frame = int(round(entry["startFrame"] * fps_scale))
        end_frame = int(round(entry["endFrame"] * fps_scale))

        if cam_name not in binding_map:
            unreal.log_warning("  Skipping '{}': no binding.".format(cam_name))
            continue

        binding = binding_map[cam_name]

        section = camera_cut_track.add_section()
        section.set_range(start_frame, end_frame + 1)

        binding_id = unreal.MovieSceneObjectBindingID()
        binding_id.set_editor_property("Guid", binding.get_id())
        section.set_camera_binding_id(binding_id)

        unreal.log("  Cut: '{}' frames {}-{}".format(cam_name, start_frame, end_frame))

    unreal.log("Clone_USD_CameraSequencer: Done. {} camera cuts created.".format(len(entries)))
    return True


def run():
    json_path = find_camera_sequence_json()
    if not json_path:
        return False

    with open(json_path, "r") as f:
        sequence_data = json.load(f)

    unreal.log("Clone_USD_CameraSequencer: Loaded {}".format(json_path))
    unreal.log("  FPS: {}, Cameras: {}".format(
        sequence_data.get("fps", "?"),
        len(sequence_data.get("sequence", []))
    ))

    sequence = find_level_sequence()
    if not sequence:
        unreal.log_error("Clone_USD_CameraSequencer: No Level Sequence found.")
        return False

    unreal.log("  Level Sequence: '{}'".format(sequence.get_name()))
    return build_camera_cut_track(sequence, sequence_data)



# Only auto-run when executed directly (not when imported as module)
if __name__ == "__main__":
    run()
