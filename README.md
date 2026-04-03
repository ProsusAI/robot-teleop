# G1 + Quest 3 Teleoperation

> **Status: Fully tested and working** — Full-body teleoperation confirmed on G1 (29-DoF) via Quest 3, running entirely on the G1's Jetson Orin NX. Inspire RH56DFTP right hand integrated via direct Modbus TCP. Left hand offline (hardware issue).

Full-body teleoperation of a **Unitree G1 (29-DoF)** humanoid robot using a **Meta Quest 3** VR headset. Everything runs directly on the G1's onboard **Jetson Orin NX** (PC2) — no external host PC needed.

Built on Unitree's [xr_teleoperate](https://github.com/unitreerobotics/xr_teleoperate) v1.5 (Open-TeleVision framework, CoRL 2024). Uses browser-based WebXR — just open a URL on the Quest 3.

## Repo Structure

This monorepo bundles all required components — no separate cloning needed:

```
robot-teleop/
├── xr_teleoperate/          # Teleop stack (IK, WebXR server, robot control)
│   ├── assets/              # URDF models, meshes for G1/H1/hands
│   └── teleop/              # Main scripts, televuer, utils
│       └── robot_control/
│           ├── robot_hand_inspire.py          # Original DDS-based Inspire driver
│           └── robot_hand_inspire_modbus.py   # Direct Modbus TCP driver (our addition)
├── teleimager/              # Camera streaming server
│   └── src/teleimager/      # image_server.py, image_client.py
├── unitree_sdk2_python/     # Unitree SDK (DDS comms, G1 modules)
│   └── unitree_sdk2py/      # Core SDK: g1/, comm/, idl/, etc.
└── README.md
```

---

## Hardware


| Component              | Details                                              |
| ---------------------- | ---------------------------------------------------- |
| Robot                  | Unitree G1, 29-DoF arm config                        |
| VR Headset             | Meta Quest 3                                         |
| Robot onboard PC (PC2) | Jetson Orin NX 16GB, Ubuntu 20.04 ARM                |
| Camera                 | Intel RealSense D430i (on G1, `/dev/video2`)         |
| Dexterous hands        | Inspire RH56DFTP × 2 (Ethernet Modbus TCP)           |
| Unitree remote         | Required for robot mode switching and emergency stop  |
| WiFi router            | Must be on `192.168.123.x` subnet (same as G1)       |


---

## Quick Start

Once everything is set up, daily usage is three steps:

```bash
# SSH Session 1: Camera server
conda activate teleimager
cd ~/robot-teleop/teleimager
python -m teleimager.image_server

# SSH Session 2: Teleop server (with Inspire hands)
conda activate tv
cd ~/robot-teleop/xr_teleoperate/teleop
python teleop_hand_and_arm.py --arm=G1_29 --motion --input-mode=hand --ee=inspire_ftp --display-mode=immersive

# Quest 3 browser:
# https://192.168.123.164:8012/?ws=wss://192.168.123.164:8012

# Terminal: r = start, s = record, q = quit
# Remote: L2+B = emergency stop
```

---

## Setup

### Part 1: Jetson Teleop Environment

All commands run via SSH into the G1.

#### 1.1 Install Miniconda

The Jetson ships with Python 3.8 — too old. Miniconda provides Python 3.10:

```bash
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-aarch64.sh -O /tmp/miniconda.sh
bash /tmp/miniconda.sh -b -p ~/miniconda3
~/miniconda3/bin/conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main
~/miniconda3/bin/conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r
~/miniconda3/bin/conda init bash
source ~/.bashrc
```

#### 1.2 Create the teleop environment

```bash
conda create -n tv python=3.10 pinocchio=3.1.0 numpy=1.26.4 -c conda-forge -y
conda activate tv
```

#### 1.3 Clone this repo

```bash
cd ~
git clone https://github.com/<YOUR_ORG>/robot-teleop.git
cd robot-teleop
```

Everything is included — no submodules to init, no extra repos to clone.

#### 1.4 Install packages from the repo

```bash
cd ~/robot-teleop

# Use the conda env's pip, not system pip
# Unitree SDK (includes MotionSwitcherClient, LocoClient, G1 modules)
/home/unitree/miniconda3/envs/tv/bin/pip install -e unitree_sdk2_python/

# Teleimager client (no-deps — server deps installed separately in Part 2)
/home/unitree/miniconda3/envs/tv/bin/pip install -e xr_teleoperate/teleop/teleimager/ --no-deps

# Televuer (WebXR interface)
/home/unitree/miniconda3/envs/tv/bin/pip install -e xr_teleoperate/teleop/televuer/
```

#### 1.5 Install remaining dependencies

```bash
pip install 'vuer[all]==0.0.60'
pip install 'params-proto==2.13.2'
pip install meshcat==0.3.2
pip install 'rerun-sdk==0.21.0'
pip install sshkeyboard==2.3.1
pip install matplotlib==3.7.5
pip install git+https://github.com/unitreerobotics/logging-mp.git
pip install pymodbus       # Required for Inspire hands (Modbus TCP driver)
pip install numpy==1.26.4  # ALWAYS re-pin after installing anything
```

#### 1.6 Install dex-retargeting (required for Inspire hands)

The `dex-retargeting` submodule handles finger pose retargeting from VR hand tracking to the Inspire hand's 6 DOFs. `nlopt` must be installed via conda because pip fails to build it on ARM:

```bash
conda activate tv
conda install -c conda-forge nlopt -y
cd ~/robot-teleop/xr_teleoperate/teleop/robot_control/dex-retargeting
/home/unitree/miniconda3/envs/tv/bin/pip install -e . --no-deps
/home/unitree/miniconda3/envs/tv/bin/pip install anytree pytransform3d trimesh lxml torch==2.3.0
/home/unitree/miniconda3/envs/tv/bin/pip install numpy==1.26.4
```

Verify:

```bash
python -c "from dex_retargeting import RetargetingConfig; print('OK')"
```

#### 1.7 Install pymodbus (required for Inspire hands)

```bash
/home/unitree/miniconda3/envs/tv/bin/pip install pymodbus
```

#### 1.8 Generate SSL certificates

Quest 3 requires HTTPS for WebXR:

```bash
cd ~/robot-teleop/xr_teleoperate/teleop/televuer
openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout key.pem -out cert.pem
mkdir -p ~/.config/xr_teleoperate/
cp cert.pem key.pem ~/.config/xr_teleoperate/
```

### Part 2: Camera Server

The camera server runs in a **separate conda environment** to avoid dependency conflicts.

#### 2.1 Create teleimager environment

```bash
conda create -n teleimager python=3.10 -y
conda activate teleimager
```

#### 2.2 Install teleimager

```bash
sudo apt install -y libusb-1.0-0-dev libturbojpeg-dev
cd ~/robot-teleop/teleimager

# IMPORTANT: Use the conda env's pip, not system pip
/home/unitree/miniconda3/envs/teleimager/bin/pip install -e ".[server]"
/home/unitree/miniconda3/envs/teleimager/bin/pip install git+https://github.com/unitreerobotics/logging-mp.git
```

> **Critical**: The system `pip` at `/home/unitree/.local/bin/pip` installs to Python 3.8. Always use the full path `/home/unitree/miniconda3/envs/teleimager/bin/pip`.

#### 2.3 Camera permissions and certificates

```bash
cd ~/robot-teleop/teleimager
bash setup_uvc.sh
# Log out and back in for group change to take effect

openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout key.pem -out cert.pem
mkdir -p ~/.config/xr_teleoperate/
cp cert.pem key.pem ~/.config/xr_teleoperate/
```

#### 2.4 Configure camera

A working config is already included at `teleimager/cam_config_server.yaml`. To discover other cameras, run `python -m teleimager.image_server --cf`. The G1's Intel RealSense D430i uses `/dev/video2` (480x640 RGB).

Default config (`~/robot-teleop/teleimager/cam_config_server.yaml`):

```yaml
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
```

> Wrist cameras must be present in the config (even disabled) — `image_client.py` expects them.

---

## Inspire RH56DFTP Dexterous Hands

### Overview

The Inspire RH56DFTP hands connect to the G1 via **Ethernet using Modbus TCP**. Each hand has 6 DOFs (little finger, ring, middle, index, thumb bend, thumb rotation) controlled by writing angle values (0–1000) to registers over TCP port 6000.

The original `xr_teleoperate` code uses `inspire_sdkpy` (a proprietary DDS-based SDK) to control the FTP hands. Since this SDK is not publicly available, we wrote a **drop-in replacement** (`robot_hand_inspire_modbus.py`) that talks directly to the hands via Modbus TCP, bypassing DDS entirely.

### Hand Network Configuration

The Inspire hands ship with a default IP of `192.168.11.210` on a different subnet. On our G1, the hands have been reconfigured to the robot's subnet:

| Hand  | IP Address         | Port | Status          |
| ----- | ------------------ | ---- | --------------- |
| Left  | 192.168.123.210    | 6000 | **Offline** — Ethernet cable disconnected inside left forearm |
| Right | 192.168.123.211    | 6000 | **Working**     |

To verify hand connectivity from the Jetson:

```bash
nc -zv 192.168.123.211 6000   # Should say "succeeded"
nc -zv 192.168.123.210 6000   # Will timeout if left hand is disconnected
```

### Modbus TCP Register Map

All registers use byte-addressing with `device_id=255` (0xFF):

| Register       | Byte Address | Count       | Range     | Description                          |
| -------------- | ------------ | ----------- | --------- | ------------------------------------ |
| ANGLE_SET      | 1486         | 6 × int16   | 0–1000    | Set target angle (0=open, 1000=closed) |
| ANGLE_ACT      | 1546         | 6 × int16   | 0–1000    | Read actual angle                    |
| SPEED_SET      | 1522         | 6 × int16   | 0–1000    | Movement speed per DOF               |
| FORCE_SET      | 1498         | 6 × int16   | 0–3000    | Force limit per DOF (grams)          |
| FORCE_ACT      | 1582         | 6 × int16   | -4000–4000| Read actual force (grams)            |
| TEMP           | 1618         | 6 × uint8   | 0–100     | Temperature (°C)                     |
| ERROR          | 1606         | 6 × uint8   | bitmap    | Error codes                          |
| HAND_ID        | 1000         | 1 byte       | 1–254     | Hand ID                              |

DOF order: [0] little, [1] ring, [2] middle, [3] index, [4] thumb bend, [5] thumb rotation.

### The Modbus TCP Driver

The file `robot_hand_inspire_modbus.py` is a drop-in replacement for `Inspire_Controller_FTP`. It:

- Uses `pymodbus` to talk directly to hands over Modbus TCP (no DDS, no `inspire_sdkpy`)
- Has the same class name and constructor signature as the original
- Auto-reconnects if a hand comes online later (checks every 5 seconds)
- Supports environment variables `INSPIRE_LEFT_IP` and `INSPIRE_RIGHT_IP` for IP override
- Re-establishes Modbus connections in the forked child process (sockets don't survive `fork()`)

The import swap in `teleop_hand_and_arm.py` (line 188):

```python
# Original (requires proprietary inspire_sdkpy):
# from teleop.robot_control.robot_hand_inspire import Inspire_Controller_FTP

# Our replacement (direct Modbus TCP):
from teleop.robot_control.robot_hand_inspire_modbus import Inspire_Controller_FTP
```

### Standalone Hand Test Script

To test a hand directly without the full teleop stack:

```python
#!/usr/bin/env python3
from pymodbus.client import ModbusTcpClient
import time

HAND_IP = "192.168.123.211"
client = ModbusTcpClient(HAND_IP, port=6000, timeout=3)
assert client.connect()

def read_angles():
    r = client.read_holding_registers(1546, count=6, device_id=255)
    return r.registers if not r.isError() else None

def set_angles(angles):
    client.write_registers(1486, values=angles, device_id=255)

print(f"Current angles: {read_angles()}")

set_angles([0, 0, 0, 0, 0, 0])       # Open all
time.sleep(2)
set_angles([1000, 1000, 1000, 1000, 1000, 1000])  # Close all
time.sleep(2)
set_angles([0, 0, 0, 0, 0, 0])       # Open again
time.sleep(2)

client.close()
```

### Changing a Hand's IP Address

If a hand is still on the factory default IP (`192.168.11.210`), you need to either add a route or change the hand's IP. To change the IP via Modbus TCP:

```python
# Write new IP octets to registers 1700-1703
# Example: change to 192.168.123.212
client.write_register(1700, 192, device_id=255)   # IP_PART1
client.write_register(1701, 168, device_id=255)   # IP_PART2
client.write_register(1702, 123, device_id=255)   # IP_PART3
client.write_register(1703, 212, device_id=255)   # IP_PART4
client.write_register(1005, 1, device_id=255)     # SAVE to flash
# Power-cycle the hand for the new IP to take effect
```

### Troubleshooting Left Hand

The left hand at `192.168.123.210` is not responding. Full scan confirmed:
- Not on `192.168.123.x` (scanned 1–254)
- Not on `192.168.11.x` (scanned 1–254 after adding `192.168.11.1/24` to `eth0`)
- Not on serial ports (`/dev/ttyTHS0`, `/dev/ttyTHS3`, `/dev/ttyTHS4`) at any baud rate

This is a **hardware issue** — the Ethernet cable inside the left forearm is likely disconnected. Refer to Unitree's [G1 Inspire Hand Assembly Guide](https://www.unitree.com/images/G1-Flagship%20Version%20C%20End%20Dexterous%20Hand%20Disassembly%20and%20Assembly%20Guide%20Manual.pdf) for the signal board wiring.

---

## Running Teleoperation

### 1. Put G1 in motion control mode

Using the Unitree remote controller:

1. **L2+B** — Damping mode
2. **L2+UP** — Locked Standing
3. **R1+X** — Main motion control program (Regular mode)

### 2. Start the camera server (SSH session 1)

```bash
conda activate teleimager
cd ~/robot-teleop/teleimager
python -m teleimager.image_server
```

Expected output:

```
[OpenCVCamera: head_camera] initialized with 480x640 @ 30 FPS.
[Image Server] Image server has started, waiting for client connections...
[Image Server] head_camera is ready.
```

### 3. Launch teleop (SSH session 2)

**Arms only (no hands):**

```bash
conda activate tv
cd ~/robot-teleop/xr_teleoperate/teleop
python teleop_hand_and_arm.py --arm=G1_29 --motion
```

**Arms + Inspire hands:**

```bash
python teleop_hand_and_arm.py --arm=G1_29 --motion --input-mode=hand --ee=inspire_ftp --display-mode=immersive
```

Wait for: `🟢 Press [r] to start syncing`

You should see in the logs:
```
[Inspire_Controller_FTP] Initialize Inspire_Controller_FTP (Modbus TCP)...
[RightHand] Connected to 192.168.123.211:6000
[LeftHand] Failed to connect to 192.168.123.210:6000  (expected until cable is fixed)
```

### 4. Connect the Quest 3

1. Ensure Quest 3 is on the same WiFi network (`192.168.123.x` subnet)
2. Open Meta Quest browser
3. Navigate to: `https://192.168.123.164:8012/?ws=wss://192.168.123.164:8012`
4. Accept SSL certificate warning (Advanced → Proceed)
5. Click **Enter VR** and allow tracking permissions
6. Align your arms with the robot's initial pose
7. Press **r** in the SSH terminal to start teleoperation
8. Press **q** to quit

---

## Controls & Modes

### Input modes

**Hand tracking** (default):

```bash
python teleop_hand_and_arm.py --arm=G1_29 --motion --input-mode=hand
```

Bare hands tracked by Quest 3 cameras. No locomotion (use Unitree R3 controller for walking).

**Controller mode**:

```bash
python teleop_hand_and_arm.py --arm=G1_29 --motion --input-mode=controller
```

- Left joystick: walk forward/back + strafe
- Right joystick: turn
- Right A button: quit
- Both thumbsticks pressed: emergency soft stop

### Display modes


| Flag                          | Mode                                       |
| ----------------------------- | ------------------------------------------ |
| `--display-mode=immersive`    | Full VR with robot's camera feed (default) |
| `--display-mode=pass-through` | See your real room with camera overlay     |
| `--display-mode=ego`          | First-person from robot's perspective      |


### End-effectors


| Flag               | Hand                                                          |
| ------------------ | ------------------------------------------------------------- |
| `--ee=inspire_ftp` | Inspire RH56DFTP hands via Modbus TCP (our custom driver)     |
| `--ee=inspire_dfx` | Inspire RH56DFX hands via DDS (requires dfx_inspire_service)  |
| `--ee=dex3`        | Dex3-1 dexterous hand                                        |
| `--ee=dex1`        | Dex1-1 gripper                                               |
| `--ee=brainco`     | BrainCo hand                                                 |


### Example launch commands

```bash
# Arm only, hand tracking, immersive VR
python teleop_hand_and_arm.py --arm=G1_29 --motion

# Arms + Inspire hands, hand tracking, immersive VR (camera feed)
python teleop_hand_and_arm.py --arm=G1_29 --motion --input-mode=hand --ee=inspire_ftp --display-mode=immersive

# Arms + Inspire hands, pass-through
python teleop_hand_and_arm.py --arm=G1_29 --motion --input-mode=hand --ee=inspire_ftp --display-mode=pass-through

# Full body with controllers and pass-through
python teleop_hand_and_arm.py --arm=G1_29 --motion --input-mode=controller --display-mode=pass-through

# Record episodes for imitation learning
python teleop_hand_and_arm.py --arm=G1_29 --motion --ee=inspire_ftp --record

# Headless mode (no VR display, for testing)
python teleop_hand_and_arm.py --arm=G1_29 --motion --headless
```

### Terminal controls


| Key | Action                                 |
| --- | -------------------------------------- |
| `r` | Start syncing robot to your movements  |
| `s` | Start/stop recording (with `--record`) |
| `q` | Quit cleanly (arms return home first)  |


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


| Package          | Version | Notes                                     |
| ---------------- | ------- | ----------------------------------------- |
| Python           | 3.10    | Required by pinocchio and teleimager      |
| NumPy            | 1.26.4  | **Must stay <2.0**                        |
| Pinocchio        | 3.1.0   | IK solver                                 |
| CycloneDDS       | 0.10.2  | Installed with SDK                        |
| vuer             | 0.0.60  | WebXR streaming                           |
| params-proto     | 2.13.2  | Required for vuer import                  |
| rerun-sdk        | 0.21.0  | Must be <0.22 for numpy <2               |
| meshcat          | 0.3.2   | 3D visualization                          |
| sshkeyboard      | 2.3.1   | Terminal keyboard input                   |
| matplotlib       | 3.7.5   | Required by weighted_moving_filter        |
| pymodbus         | 3.12.1  | Modbus TCP for Inspire hands              |
| dex-retargeting  | 0.4.7   | Finger pose retargeting for Inspire hands |
| nlopt            | 2.10.1  | Install via conda, not pip (ARM build)    |
| torch            | 2.3.0   | Required by dex-retargeting               |


---

## File Paths


| What                      | Path                                                                    |
| ------------------------- | ----------------------------------------------------------------------- |
| Repo root                 | `~/robot-teleop/`                                                       |
| xr_teleoperate            | `~/robot-teleop/xr_teleoperate/`                                        |
| Teleop entry point        | `~/robot-teleop/xr_teleoperate/teleop/teleop_hand_and_arm.py`           |
| Inspire Modbus driver     | `~/robot-teleop/xr_teleoperate/teleop/robot_control/robot_hand_inspire_modbus.py` |
| Original Inspire driver   | `~/robot-teleop/xr_teleoperate/teleop/robot_control/robot_hand_inspire.py` |
| dex-retargeting           | `~/robot-teleop/xr_teleoperate/teleop/robot_control/dex-retargeting/`   |
| Teleop conda env          | `tv`                                                                    |
| Unitree SDK               | `~/robot-teleop/unitree_sdk2_python/`                                   |
| Teleimager                | `~/robot-teleop/teleimager/`                                            |
| Teleimager conda env      | `teleimager`                                                            |
| Camera config             | `~/robot-teleop/teleimager/cam_config_server.yaml`                      |
| SSL certificates          | `~/.config/xr_teleoperate/cert.pem`, `key.pem`                          |
| Hand test scripts         | `~/robot-audio-agent/hands/`                                            |


---

## Known Issues


| Issue                               | Fix                                                                     |
| ----------------------------------- | ----------------------------------------------------------------------- |
| Camera serial number matching fails | Use `video_id` only; set `serial_number: null`                          |
| System pip vs conda pip             | Always use `/home/unitree/miniconda3/envs/<env>/bin/pip`                |
| Camera not found after reboot       | Unplug and replug the RealSense USB cable; verify with `ls /dev/video*` |
| numpy gets upgraded by pip          | Run `pip install numpy==1.26.4` after every package installation        |
| Wrist cameras required in config    | Must be present (even disabled) or `image_client.py` throws KeyError    |
| nlopt fails to build via pip on ARM | Install via conda: `conda install -c conda-forge nlopt -y`              |
| Left Inspire hand offline           | Ethernet cable disconnected inside left forearm — needs physical inspection |
| pymodbus installs to system Python  | Always use `/home/unitree/miniconda3/envs/tv/bin/pip install pymodbus`  |
| pymodbus API version differences    | v3.12+ uses `device_id=` kwarg, not `slave=` or `unit=`                 |
| inspire_sdkpy not available         | Use `robot_hand_inspire_modbus.py` instead (direct Modbus TCP)          |
| Inspire hand IP override            | Set `INSPIRE_LEFT_IP` / `INSPIRE_RIGHT_IP` env vars (defaults: `192.168.123.210` / `.211`) |


---

## Resources

- [xr_teleoperate repo](https://github.com/unitreerobotics/xr_teleoperate)
- [xr_teleoperate wiki](https://github.com/unitreerobotics/xr_teleoperate/wiki)
- [teleimager repo](https://github.com/unitreerobotics/teleimager)
- [Inspire RH56DFTP User Manual](https://en.inspire-robots.com/wp-content/uploads/2025/01/INSPIRE-ROBOTS-The-Dexterous-Hand-RH56DFTP-User-Manual-V1.0.0.pdf)
- [TechShare inspire_demos library](https://github.com/TechShare-inc/inspire_demos)
- [G1 Inspire Hand Assembly Guide](https://www.unitree.com/images/G1-Flagship%20Version%20C%20End%20Dexterous%20Hand%20Disassembly%20and%20Assembly%20Guide%20Manual.pdf)
- [xr_teleoperate issue #48 — FTP hand support](https://github.com/unitreerobotics/xr_teleoperate/issues/48)
- [Unitree Discord](https://discord.gg/ZwcVwxv5rq)
- [SPARK safety toolkit](https://github.com/intelligent-control-lab/spark)
- [Open-TeleVision paper](https://arxiv.org/abs/2407.01512)

