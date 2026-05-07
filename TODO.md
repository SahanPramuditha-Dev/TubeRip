# Fix TubeRipApp AttributeError: '_tkinter.tkapp' object has no attribute '_audio_outer'

## Steps:
- [ ] Step 1: Edit main.py - Move `self._set_mode("video")` from line ~602 (after mode buttons) to end of _build_page_download() after `self._dl_btn_frame.pack(...)`
- [ ] Step 2: Verify fix by running `python main.py` (app should launch without error)
- [ ] Step 3: Test mode switching (Video/Audio) in UI
- [ ] Step 4: Mark complete and attempt_completion

