# Camera projection switch crash

Fixes [cyberbotics/webots#6910](https://github.com/cyberbotics/webots/issues/6910).

Changing a `Camera` `projection` field after the device has been enabled used to crash Webots on the next simulation step. The same path now keeps the controller attached to a valid image and does less work for each switch.

## What went wrong

The camera image is shared with the robot controller through a memory-mapped file. The first time the camera is enabled, Webots creates that file and sends its name to the controller (`C_CAMERA_MEMORY_MAPPED_FILE`). The controller keeps the mapping open for the rest of the run.

`projection` is not a live parameter of the renderer. Planar, spherical, and cylindrical cameras use different framebuffers, so `WbAbstractCamera::updateProjection()` has to rebuild the camera after initialization. That rebuild called `setup()` again, which deleted the memory-mapped file and tried to create another one **with the same name**.

On Windows the mapping is a `QSharedMemory` segment. `create()` fails with `AlreadyExists` while the controller still has the old name open. Webots logged `Cannot allocate memory mapped file`, left the image pointer aimed at the freed segment, and crashed on the next copy into that pointer.

On Linux the POSIX implementation `unlink`s the name and creates a new file, so the same steps usually survive. The controller can also keep reading the previous mapping until it is told about a replacement. That is why the bug shows up reliably on Windows and not on a typical Linux desktop.

`cCameraNumber` was already incremented on every rebuild, but the number was never added to the file name, so the counter did not avoid the collision.

## What changed

1. Every image segment is named `snap.webots.<camera>.<generation>`. The generation is `cCameraNumber`, which already increases on each allocation. If that name is still busy, one fresh generation is tried before giving up. The controller is notified through the existing `C_CAMERA_MEMORY_MAPPED_FILE` message and remaps. The previous segment stays alive until the controller unmaps it, which is what releases it on Windows.
2. If allocation still fails, the image pointer is cleared and the copy into the mapping is skipped, so a failed create cannot write through a dangling pointer.
3. The controller side (`image_cleanup`) unmaps the old view, closes the Windows handle, and frees the previous file name before attaching the new one.
4. A projection change no longer calls `setup()`. `setup()` is the first-enable path: it increments the process-wide camera counter, subscribes recognition ray tracing, and connects frustum updates. Calling it on every edit stacked those connections and subscriptions. The Wren camera now switches mode with `WbWrenCamera::setProjection()`, which releases the old framebuffers and builds the new ones while keeping the per-face post-processing helpers (bloom, SMAA, GTAO, HDR, and the rest). The camera overlay is rebound to the new texture, and the controller is reconfigured (`C_CAMERA_RECONFIGURE`) so `wb_camera_get_fov` style checks see the new planar flag.

## Performance

Spherical and cylindrical projections still render up to six faces. That cost is the projection itself, not the bug.

What got cheaper is the **switch**:

- The old path destroyed the whole `WbWrenCamera`, including 6 orientations × 11 post-processing helper objects, then allocated them again. `setProjection()` keeps those helpers and only rebuilds the GPU framebuffers and viewports.
- Returning to `planar` no longer adds another `optionalRenderingChanged` slot or another recognition ray-tracing subscription. Those used to accumulate for as long as the world stayed open.

Measured on this machine (software OpenGL, 160×120 camera, `camera_projection_switch.wbt`), image checksums are identical before and after the fix, so the pictures did not change:

| Projection | Checksum | Before (one warm run) | After |
| --- | --- | --- | --- |
| planar baseline | 424236 | — | — |
| spherical | 420025 | 65 ms | 40–51 ms |
| cylindrical | 427389 | 19 ms | 27–35 ms |
| back to planar | 424236 | 7 ms | 7–38 ms |
| 10 further toggles, average | — | 6.0 ms | 5.0–8.3 ms |

The toggle time is mostly framebuffer rebuild and software rasterization, so it jumps around by a few milliseconds. The stable result is that ten extra toggles still finish, the checksums still change with the mode, and the per-switch heap and signal-connection work no longer grows.

## Try it

From a built Webots tree:

```bash
export LIBGL_ALWAYS_SOFTWARE=true   # only needed without a GPU
./webots --stdout --stderr --batch --mode=fast --no-rendering \
  projects/samples/devices/worlds/camera_projection_switch.wbt
```

A passing run prints `PROJECTION_SWITCH PASS` after spherical, cylindrical, and planar images have different checksums and ten more toggles have completed. Any crash, empty image, or `Cannot allocate memory mapped file` line is a failure.

The original report can also be followed by hand in `projects/samples/devices/worlds/camera.wbt`: run the simulation, select the `Camera` node, and set `projection` to `spherical`. The simulation should keep stepping and the camera overlay should switch to the spherical image.
