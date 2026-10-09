# laya_video

LAYA video adapter on the shared Scene core (plan 28).

- **Public API:** `analyse`, `apply_fix`, `assemble`, `brief_from`, `capture_flags`, `capture_index`, `checkpoint`, `compile_project`, `contact_sheet`, `decode_audio`, `decode_gray`, `delta_e`, `derive_crop`, `dom_facts`, `episode_input`, `fix_add_motion`, `fix_aspect`, `fix_brand`, `fix_card_motion`, `fix_close_gap`, `fix_extend_bed`, `fix_extend_caption`, `fix_insert_shot`, `fix_move_into_safe`, `fix_normalize`, `fix_restack`, `fix_restyle`, `fix_retime`, `fix_separate`, `fix_snap_cuts`, `fix_swap_capture`, `frames_at`, `glance_capture`, `improve_cut`, `largest_flat_rect`, `library_for`, `load_edl`, `make_adapter`, `observe`, `observe_file`, `ocr_lines`, `pixel_text_colours`, `probe`, `project_hash`, `read_brief`, `render`, `restore`, `save_edl`, `scene_from`, `sha_file`, `source_audit`, `source_text`, `speech`, `tools`, `total_seconds`, `unread_path_blocks`, `vocabulary`, `vote`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl), [video.cl](../../manuals/cl/video.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `video.outcome-contracts`.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.laya_glance](../backend.laya_glance/README.md), [backend.laya_glance_gate](../backend.laya_glance_gate/README.md), [backend.laya_glance_image](../backend.laya_glance_image/README.md), [backend.proof_ports](../backend.proof_ports/README.md), [backend.scene_core.__init__](../backend.scene_core.__init__/README.md).
- **Owner:** Neyvia / video.
- **Files:** [src/grant_agent/laya_video.py](../../src/grant_agent/laya_video.py).
