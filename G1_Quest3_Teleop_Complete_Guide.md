# G1 + Quest 3 Teleoperation: Complete Setup Guide

> **Status: FULLY TESTED AND WORKING** — Full-body teleoperation confirmed on G1 (29-DoF) via Quest 3, running entirely on the G1's Jetson Orin NX. Need to figure out Inspire hands integration.
> Last updated: April 1, 2026

---

## Overview

This document covers the complete setup of full-body teleoperation of a **Unitree G1 (29-DoF)** humanoid robot using a **Meta Quest 3** VR headset. Everything runs directly on the G1's onboard **Jetson Orin NX** (PC2) — no external host PC needed.

The software stack is Unitree's official `**xr_teleoperate`** repository (v1.5), built on the Open-TeleVision framework (CoRL 2024). It uses browser-based WebXR, so no custom app is needed on the Quest 3 — just open a URL in the browser.

---

## Hardware


| Component              | Details                                              |
| ---------------------- | ---------------------------------------------------- |
| Robot                  | Unitree G1, 29-DoF arm config                        |
| VR Headset             | Meta Quest 3                                         |
| Robot onboard PC (PC2) | Jetson Orin NX 16GB, Ubuntu 20.04 ARM                |
| Camera                 | Intel RealSense D430i (on G1, `/dev/video2`)         |
| Unitree remote         | Required for robot mode switching and emergency stop |
| WiFi router            | Must be on `192.168.123.x` subnet (same as G1)       |


> **No external host PC needed.** The Jetson runs the IK solver, WebXR server, and camera streaming all on-board.

---

## Part 1: Jetson Teleop Setup

All commands run via SSH into the G1:

### 1.1 Install miniconda

The Jetson ships with Python 3.8 — too old. Miniconda provides Python 3.10:

```bash
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-aarch64.sh -O /tmp/miniconda.sh
bash /tmp/miniconda.sh -b -p ~/miniconda3
~/miniconda3/bin/conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main
~/miniconda3/bin/conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r
~/miniconda3/bin/conda init bash
source ~/.bashrc
```

### 1.2 Create the teleop environment

```bash
conda create -n tv python=3.10 pinocchio=3.1.0 numpy=1.26.4 -c conda-forge -y
conda activate tv
```

### 1.3 Clone xr_teleoperate

```bash
mkdir -p ~/teleop && cd ~/teleop
git clone https://github.com/unitreerobotics/xr_teleoperate.git
cd xr_teleoperate
git submodule update --init --depth 1
```

### 1.4 Install submodules

```bash
cd teleop/teleimager && pip install -e . --no-deps
cd ../televuer && pip install -e .
```

### 1.5 Install the Unitree SDK

Install as editable from source — this version includes the full `comm` and `g1` modules:

```bash
cd ~/teleop
git clone https://github.com/unitreerobotics/unitree_sdk2_python.git
cd unitree_sdk2_python
pip install -e .
```

> **Note**: No manual SDK patching needed. The cloned repo includes `MotionSwitcherClient`, `LocoClient`, and all G1-specific modules.

### 1.6 Install remaining dependencies

```bash
pip install 'vuer[all]==0.0.60'
pip install 'params-proto==2.13.2'
pip install meshcat==0.3.2
pip install 'rerun-sdk==0.21.0'
pip install sshkeyboard==2.3.1
pip install matplotlib==3.7.5
pip install git+https://github.com/unitreerobotics/logging-mp.git
pip install numpy==1.26.4  # ALWAYS re-pin after installing anything
```

### 1.7 Generate SSL certificates

Quest 3 requires HTTPS for WebXR:

```bash
cd ~/teleop/xr_teleoperate/teleop/televuer
openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout key.pem -out cert.pem
# Hit Enter through all prompts — defaults are fine
mkdir -p ~/.config/xr_teleoperate/
cp cert.pem key.pem ~/.config/xr_teleoperate/
```

---

## Part 2: Camera Server Setup

The camera server runs in a separate conda environment to avoid dependency conflicts.

### 2.1 Create teleimager environment

```bash
conda create -n teleimager python=3.10 -y
conda activate teleimager
```

### 2.2 Install teleimager

```bash
sudo apt install -y libusb-1.0-0-dev libturbojpeg-dev
cd ~/teleop
git clone https://github.com/unitreerobotics/teleimager.git
cd teleimager

# IMPORTANT: Use the conda env's pip, not system pip
/home/unitree/miniconda3/envs/teleimager/bin/pip install -e ".[server]"
/home/unitree/miniconda3/envs/teleimager/bin/pip install git+https://github.com/unitreerobotics/logging-mp.git
```

> **Critical**: The system `pip` at `/home/unitree/.local/bin/pip` installs to Python 3.8. Always use the full path `/home/unitree/miniconda3/envs/teleimager/bin/pip` to install into the conda env.

### 2.3 Patch teleimager logging API

The teleimager code uses an older `logging_mp` API. Apply these fixes:

```bash
cd ~/teleop/teleimager

# Reset to clean state
git checkout src/teleimager/image_server.py
git checkout src/teleimager/image_client.py

# Fix image_client.py: get_logger → getLogger, remove level kwarg
sed -i 's/logging_mp.get_logger(__name__, level=logging_mp.INFO)/logging_mp.getLogger(__name__)/g' src/teleimager/image_client.py

# Fix image_server.py: insert basicConfig BEFORE the image_client import (line 27)
sed -i '26a import logging_mp\nlogging_mp.basicConfig(level=logging_mp.INFO)\nlogger_mp = logging_mp.getLogger(__name__)' src/teleimager/image_server.py

# Remove the old logging_mp lines (now around lines 45-47)
sed -i '45,47d' src/teleimager/image_server.py
```

> **Why**: `basicConfig()` must be called before any `getLogger()`. The original code imports `image_client` (which calls `getLogger`) before calling `basicConfig`. The fix reorders them.

### 2.4 Set up camera permissions and certificates

```bash
cd ~/teleop/teleimager
bash setup_uvc.sh
# Log out and back in for group change to take effect

# Generate SSL certificates
openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout key.pem -out cert.pem
mkdir -p ~/.config/xr_teleoperate/
cp cert.pem key.pem ~/.config/xr_teleoperate/
```

### 2.5 Configure camera

Discover cameras:

```bash
python -m teleimager.image_server --cf
```

The G1 has an Intel RealSense D430i. Only `/dev/video2` produces RGB frames (480x640). Configure:

```bash
cat > ~/teleop/teleimager/cam_config_server.yaml << 'EOF'
head_camera:
  enable_zmq: true
  zmq_port: 55555
  enable_webrtc: true
  webrtc_port: 60001
  webrtc_codec: h264
  type: opencv
  image_shape: [480, 640]
  binocular: false
  fps: 30
  video_id: 2
  serial_number: null
  physical_path: null

left_wrist_camera:
  enable_zmq: false
  zmq_port: 55556
  enable_webrtc: false
  webrtc_port: 60002
  webrtc_codec: h264
  type: opencv
  image_shape: [480, 640]
  binocular: false
  fps: 30
  video_id: null
  serial_number: null
  physical_path: null

right_wrist_camera:
  enable_zmq: false
  zmq_port: 55557
  enable_webrtc: false
  webrtc_port: 60003
  webrtc_codec: h264
  type: opencv
  image_shape: [480, 640]
  binocular: false
  fps: 30
  video_id: null
  serial_number: null
  physical_path: null
EOF
```

> **Important**: Wrist cameras MUST be present (even disabled) — `image_client.py` expects them.

---

## Part 3: Running Teleoperation

### Step 1: Put G1 in motion control mode

Using the Unitree remote controller:

1. **L2+B** → Damping mode
2. **L2+UP** → Locked Standing
3. **R1+X** → Main motion control program (Regular mode)

### Step 2: Start the camera server (SSH session 1)

```bash
conda activate teleimager
cd ~/teleop/teleimager
python -m teleimager.image_server
```

You should see:

```
[OpenCVCamera: head_camera] initialized with 480x640 @ 30 FPS.
[Image Server] Image server has started, waiting for client connections...
[Image Server] head_camera is ready.
```

### Step 3: Launch teleop (SSH session 2)

```bash
conda activate tv
cd ~/teleop/xr_teleoperate/teleop
python teleop_hand_and_arm.py --arm=G1_29 --motion
```

Key messages:

- "[G1_29_ArmController] Subscribe dds ok." — DDS connected
- "Initialize G1_29_ArmController OK!" — arm controller ready
- "🟢 Press [r] to start syncing" — ready for Quest 3

### Step 4: Connect the Quest 3

1. Ensure Quest 3 is on the **same WiFi network** (`192.168.123.x` subnet)
2. Open **Meta Quest browser**
3. Navigate to: `https://192.168.123.164:8012/?ws=wss://192.168.123.164:8012`
4. Accept SSL certificate warning (Advanced → Proceed)
5. Click **"Enter VR"** and allow tracking permissions
6. Align your arms with the robot's initial pose
7. Press `**r`** in the SSH terminal to start teleoperation
8. Press `**q`** to quit

---

## Input Modes & Controls

### Hand tracking mode (default)

```bash
python teleop_hand_and_arm.py --arm=G1_29 --motion --input-mode=hand
```

- Your bare hands are tracked by Quest 3 cameras
- Move hands naturally — G1's arms follow
- No locomotion via hand tracking (need Unitree R3 controller for walking)

### Controller mode

```bash
python teleop_hand_and_arm.py --arm=G1_29 --motion --input-mode=controller
```

- Hold Quest 3 controllers
- Controller positions control the robot's arms
- **Left joystick**: walk forward/back + strafe
- **Right joystick**: turn
- **Right A button**: quit
- **Both thumbsticks pressed**: emergency soft stop

### Display modes

- `--display-mode=immersive` — full VR, robot's camera feed (default)
- `--display-mode=pass-through` — see your real room with camera overlay
- `--display-mode=ego` — first-person from robot's perspective

### End-effectors (when hands are connected)

- `--ee=inspire_ftp` — Inspire hands, finger tip position control
- `--ee=inspire_dfx` — Inspire hands, direct flex control
- `--ee=dex3` — Dex3-1 dexterous hand
- `--ee=dex1` — Dex1-1 gripper
- `--ee=brainco` — BrainCo hand

### Example launch commands

```bash
# Arm only, hand tracking, immersive VR
python teleop_hand_and_arm.py --arm=G1_29 --motion

# Full body with controllers and pass-through
python teleop_hand_and_arm.py --arm=G1_29 --motion --input-mode=controller --display-mode=pass-through

# With Inspire hands
python teleop_hand_and_arm.py --arm=G1_29 --motion --input-mode=hand --ee=inspire_ftp

# Record episodes for imitation learning
python teleop_hand_and_arm.py --arm=G1_29 --motion --record

# Headless mode (no VR display, for testing)
python teleop_hand_and_arm.py --arm=G1_29 --motion --headless
```

### Terminal controls

- `r` — start syncing robot to your movements
- `s` — start/stop recording (only with `--record`)
- `q` — quit cleanly (arms return home first)

---

## Safety

The G1 weighs **35 kg** with **120 N·m knee torque** and moves at **2+ m/s**.

1. **Always have the Unitree remote in hand** — emergency stop is **L2+B**
2. **Never cut power** to a standing robot — it will fall
3. **Clear the area** — remove obstacles, equipment, and bystanders
4. **Use the gantry/suspension frame** for initial tests
5. **Never touch moving joints**, especially knees and waist
6. **Monitor battery** — stop when last cell indicator flashes (60-90 min runtime)
7. **Short sessions** (10-15 min) — visual latency (~120ms) can cause nausea
8. **Never enter debug mode** (L2+R2) — requires full reboot
9. **Only Regular mode (R1+X)** — Running mode (R2+A) is not supported

---

## Version Pins


| Package      | Version | Notes                                |
| ------------ | ------- | ------------------------------------ |
| Python       | 3.10    | Required by pinocchio and teleimager |
| NumPy        | 1.26.4  | **Must stay <2.0**                   |
| Pinocchio    | 3.1.0   | IK solver                            |
| CycloneDDS   | 0.10.2  | Installed with SDK                   |
| vuer         | 0.0.60  | WebXR streaming                      |
| params-proto | 2.13.2  | Required for vuer import             |
| rerun-sdk    | 0.21.0  | Must be <0.22 for numpy <2           |
| meshcat      | 0.3.2   | 3D visualization                     |
| sshkeyboard  | 2.3.1   | Terminal keyboard input              |
| matplotlib   | 3.7.5   | Required by weighted_moving_filter   |


---

## File Paths


| What                 | Path                                                    |
| -------------------- | ------------------------------------------------------- |
| Teleop root          | `~/teleop/`                                             |
| xr_teleoperate repo  | `~/teleop/xr_teleoperate/`                              |
| Teleop entry point   | `~/teleop/xr_teleoperate/teleop/teleop_hand_and_arm.py` |
| Teleop conda env     | `tv`                                                    |
| SDK (editable)       | `~/teleop/unitree_sdk2_python/`                         |
| Teleimager repo      | `~/teleop/teleimager/`                                  |
| Teleimager conda env | `teleimager`                                            |
| Camera config        | `~/teleop/teleimager/cam_config_server.yaml`            |
| SSL certificates     | `~/.config/xr_teleoperate/cert.pem`, `key.pem`          |


---

## Known Issues & Workarounds

### teleimager logging patches lost on git pull

Re-apply patches from section 2.3 after any `git pull` on the teleimager repo.

### Camera serial number matching fails

Use `video_id` only. Set `serial_number: null` in camera config.

### System pip vs conda pip

Always use `/home/unitree/miniconda3/envs/<env>/bin/pip`. System pip installs to Python 3.8.

### Camera not found after reboot

Unplug and replug the RealSense USB cable. Verify with `ls /dev/video`*.

### numpy gets upgraded by pip

Run `pip install numpy==1.26.4` after every package installation.

### Wrist cameras required in config

Must be present (even disabled) or `image_client.py` throws KeyError.

---

## Quick Reference: Daily Startup

```bash
# SSH Session 1: Camera server
ssh unitree@192.168.123.164
conda activate teleimager
cd ~/teleop/teleimager
python -m teleimager.image_server

# SSH Session 2: Teleop server
ssh unitree@192.168.123.164
conda activate tv
cd ~/teleop/xr_teleoperate/teleop
python teleop_hand_and_arm.py --arm=G1_29 --motion

# Quest 3 browser:
# https://192.168.123.164:8012/?ws=wss://192.168.123.164:8012

# Terminal: r = start, s = record, q = quit
# Remote: L2+B = emergency stop
```

---

## Claude Code Instructions

When helping continue this project:

1. **NumPy must stay at 1.26.4** — always re-pin after installing anything.
2. **Jetson SDK has full G1 support** — `comm`, `g1` modules included when installed from source. No manual patching.
3. **teleimager logging patches** are manual — re-apply after `git pull`.
4. **Two conda envs**: `tv` (teleop) and `teleimager` (camera). Separate SSH sessions.
5. **System pip vs conda pip** — always use full conda pip path on Jetson.
6. **Camera config must include wrist cameras** (even disabled).
7. **Inspire hands disconnected** — use `--ee=inspire_ftp` when reconnected.
8. **Safety is non-negotiable** — L2+B for emergency stop.
9. **Locomotion via joystick** uses `LocoClient.Move()` — may need API ID tuning.
10. **Quest 3 connects via WiFi** to `https://192.168.123.164:8012/...` — no Mac needed.

---

## Resources

- **xr_teleoperate repo**: [https://github.com/unitreerobotics/xr_teleoperate](https://github.com/unitreerobotics/xr_teleoperate)
- **xr_teleoperate wiki**: [https://github.com/unitreerobotics/xr_teleoperate/wiki](https://github.com/unitreerobotics/xr_teleoperate/wiki)
- **teleimager repo**: [https://github.com/unitreerobotics/teleimager](https://github.com/unitreerobotics/teleimager)
- **Unitree Discord**: [https://discord.gg/ZwcVwxv5rq](https://discord.gg/ZwcVwxv5rq)
- **SPARK safety toolkit**: [https://github.com/intelligent-control-lab/spark](https://github.com/intelligent-control-lab/spark)
- **Open-TeleVision paper**: [https://arxiv.org/abs/2407.01512](https://arxiv.org/abs/2407.01512)

