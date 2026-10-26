"""Switch a Camera projection while the simulation is running.

Reproduces https://github.com/cyberbotics/webots/issues/6910 :
the camera image memory-mapped file used to be recreated under the same name
after initialization. On Windows that fails while the controller still maps
the previous segment, and the next step crashes. This controller keeps
stepping across planar, spherical, and cylindrical so a crash or a stale
image fails the run.
"""

import time

from controller import Supervisor


def image_checksum(image):
    if not image:
        return None
    # Stride keeps the sum cheap and still sensitive to a projection change.
    return sum(image[index] for index in range(0, len(image), 17))


def main():
    robot = Supervisor()
    timestep = int(robot.getBasicTimeStep())
    camera = robot.getDevice("camera")
    camera.enable(timestep)

    camera_node = None
    children = robot.getSelf().getField("children")
    for index in range(children.getCount()):
        node = children.getMFNode(index)
        if node.getTypeName() == "Camera":
            camera_node = node
            break
    if camera_node is None:
        print("PROJECTION_SWITCH FAIL camera node not found", flush=True)
        robot.simulationQuit(1)
        return

    projection = camera_node.getField("projection")

    for _ in range(8):
        if robot.step(timestep) == -1:
            print("PROJECTION_SWITCH FAIL warmup", flush=True)
            return

    previous = image_checksum(camera.getImage())
    print(f"PROJECTION_SWITCH baseline planar checksum={previous}", flush=True)
    if previous is None:
        print("PROJECTION_SWITCH FAIL no image", flush=True)
        robot.simulationQuit(1)
        return

    # One pass of every mode, then a burst of toggles for switch cost.
    sequence = ["spherical", "cylindrical", "planar"]
    for mode in sequence:
        started = time.perf_counter()
        projection.setSFString(mode)
        if robot.step(timestep) == -1:
            print(f"PROJECTION_SWITCH FAIL step {mode}", flush=True)
            return
        for _ in range(4):
            if robot.step(timestep) == -1:
                print(f"PROJECTION_SWITCH FAIL followup {mode}", flush=True)
                return
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        checksum = image_checksum(camera.getImage())
        changed = checksum != previous
        print(
            f"PROJECTION_SWITCH mode={mode} checksum={checksum} changed={changed} ms={elapsed_ms:.2f}",
            flush=True,
        )
        if checksum is None:
            print(f"PROJECTION_SWITCH FAIL empty image {mode}", flush=True)
            robot.simulationQuit(1)
            return
        previous = checksum

    toggles = 0
    toggle_ms = 0.0
    mode = "spherical"
    for _ in range(10):
        started = time.perf_counter()
        projection.setSFString(mode)
        if robot.step(timestep) == -1:
            print("PROJECTION_SWITCH FAIL toggle", flush=True)
            return
        toggle_ms += (time.perf_counter() - started) * 1000.0
        toggles += 1
        mode = "planar" if mode == "spherical" else "spherical"
    print(f"PROJECTION_SWITCH toggles={toggles} avg_ms={toggle_ms / toggles:.2f}", flush=True)
    print("PROJECTION_SWITCH PASS", flush=True)
    for _ in range(3):
        if robot.step(timestep) == -1:
            break
    robot.simulationQuit(0)


if __name__ == "__main__":
    main()
