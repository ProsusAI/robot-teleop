"""
Drop-in replacement for Inspire_Controller_FTP that uses direct Modbus TCP
instead of the proprietary inspire_sdkpy DDS bridge.
"""

from pymodbus.client import ModbusTcpClient
from teleop.robot_control.hand_retargeting import HandRetargeting, HandType
import numpy as np
import threading
import time
from multiprocessing import Process, Array

import logging_mp
logger_mp = logging_mp.getLogger(__name__)

Inspire_Num_Motors = 6

REG_ANGLE_SET = 1486
REG_ANGLE_ACT = 1546
REG_FORCE_ACT = 1582
REG_SPEED_SET = 1522

MODBUS_DEVICE_ID = 255

DEFAULT_LEFT_IP  = "192.168.123.210"
DEFAULT_RIGHT_IP = "192.168.123.211"
MODBUS_PORT = 6000


class InspireHandModbusTCP:
    def __init__(self, ip, port=MODBUS_PORT, label="hand"):
        self.ip = ip
        self.port = port
        self.label = label
        self.client = None
        self.connected = False

    def connect(self):
        try:
            self.client = ModbusTcpClient(self.ip, port=self.port, timeout=1)
            if self.client.connect():
                self.connected = True
                logger_mp.info(f"[{self.label}] Connected to {self.ip}:{self.port}")
                return True
            else:
                logger_mp.warning(f"[{self.label}] Failed to connect to {self.ip}:{self.port}")
                return False
        except Exception as e:
            logger_mp.warning(f"[{self.label}] Connection error: {e}")
            return False

    def reconnect(self):
        if self.client:
            try:
                self.client.close()
            except:
                pass
        self.connected = False
        return self.connect()

    def read_angles(self):
        if not self.connected:
            return None
        try:
            r = self.client.read_holding_registers(REG_ANGLE_ACT, count=6, device_id=MODBUS_DEVICE_ID)
            if not r.isError():
                return list(r.registers)
        except Exception:
            self.connected = False
        return None

    def write_angles(self, angles):
        if not self.connected:
            return False
        try:
            r = self.client.write_registers(REG_ANGLE_SET, values=angles, device_id=MODBUS_DEVICE_ID)
            return not r.isError()
        except Exception:
            self.connected = False
            return False

    def close(self):
        if self.client:
            try:
                self.client.close()
            except:
                pass
        self.connected = False


class Inspire_Controller_FTP:
    def __init__(self, left_hand_array, right_hand_array, dual_hand_data_lock=None, dual_hand_state_array=None,
                 dual_hand_action_array=None, fps=100.0, Unit_Test=False, simulation_mode=False,
                 left_ip=None, right_ip=None):
        logger_mp.info("Initialize Inspire_Controller_FTP (Modbus TCP)...")
        self.fps = fps
        self.Unit_Test = Unit_Test
        self.simulation_mode = simulation_mode

        import os
        self.left_ip = left_ip or os.environ.get("INSPIRE_LEFT_IP", DEFAULT_LEFT_IP)
        self.right_ip = right_ip or os.environ.get("INSPIRE_RIGHT_IP", DEFAULT_RIGHT_IP)

        if not self.Unit_Test:
            self.hand_retargeting = HandRetargeting(HandType.INSPIRE_HAND)
        else:
            self.hand_retargeting = HandRetargeting(HandType.INSPIRE_HAND_Unit_Test)

        self.left_hand = InspireHandModbusTCP(self.left_ip, label="LeftHand")
        self.right_hand = InspireHandModbusTCP(self.right_ip, label="RightHand")

        left_ok = self.left_hand.connect()
        right_ok = self.right_hand.connect()

        if not left_ok and not right_ok:
            logger_mp.warning("[Inspire_Controller_FTP] Neither hand connected!")
        elif not left_ok:
            logger_mp.warning(f"[Inspire_Controller_FTP] Left hand at {self.left_ip} not reachable")
        elif not right_ok:
            logger_mp.warning(f"[Inspire_Controller_FTP] Right hand at {self.right_ip} not reachable")

        self.left_hand_state_array = Array('d', Inspire_Num_Motors, lock=True)
        self.right_hand_state_array = Array('d', Inspire_Num_Motors, lock=True)

        self.subscribe_state_thread = threading.Thread(target=self._subscribe_hand_state)
        self.subscribe_state_thread.daemon = True
        self.subscribe_state_thread.start()

        wait_count = 0
        while not (any(self.left_hand_state_array) or any(self.right_hand_state_array)):
            if wait_count % 100 == 0:
                logger_mp.info(f"[Inspire_Controller_FTP] Waiting for hand state (L:{self.left_hand.connected} R:{self.right_hand.connected})...")
            time.sleep(0.01)
            wait_count += 1
            if wait_count > 300:
                logger_mp.warning("[Inspire_Controller_FTP] Timeout waiting for hand states. Proceeding anyway.")
                break
        logger_mp.info("[Inspire_Controller_FTP] Hand states received or timeout.")

        hand_control_process = Process(target=self.control_process, args=(
            left_hand_array, right_hand_array, self.left_hand_state_array, self.right_hand_state_array,
            dual_hand_data_lock, dual_hand_state_array, dual_hand_action_array))
        hand_control_process.daemon = True
        hand_control_process.start()

        logger_mp.info("Initialize Inspire_Controller_FTP (Modbus TCP) OK!")

    def _subscribe_hand_state(self):
        logger_mp.info("[Inspire_Controller_FTP] State polling thread started.")
        reconnect_interval = 5.0
        last_left_reconnect = 0
        last_right_reconnect = 0

        while True:
            now = time.time()

            if self.left_hand.connected:
                angles = self.left_hand.read_angles()
                if angles is not None:
                    with self.left_hand_state_array.get_lock():
                        for i in range(Inspire_Num_Motors):
                            self.left_hand_state_array[i] = angles[i] / 1000.0
            elif now - last_left_reconnect > reconnect_interval:
                self.left_hand.reconnect()
                last_left_reconnect = now

            if self.right_hand.connected:
                angles = self.right_hand.read_angles()
                if angles is not None:
                    with self.right_hand_state_array.get_lock():
                        for i in range(Inspire_Num_Motors):
                            self.right_hand_state_array[i] = angles[i] / 1000.0
            elif now - last_right_reconnect > reconnect_interval:
                self.right_hand.reconnect()
                last_right_reconnect = now

            time.sleep(0.02)

    def _send_hand_command(self, left_angle_cmd_scaled, right_angle_cmd_scaled):
        if self.left_hand.connected:
            self.left_hand.write_angles(left_angle_cmd_scaled)
        if self.right_hand.connected:
            self.right_hand.write_angles(right_angle_cmd_scaled)

        if not hasattr(self, "_debug_count"):
            self._debug_count = 0
        if self._debug_count < 20:
            logger_mp.info(f"[ModbusTCP] cmd L={left_angle_cmd_scaled} R={right_angle_cmd_scaled}")
            self._debug_count += 1

    def control_process(self, left_hand_array, right_hand_array, left_hand_state_array, right_hand_state_array,
                        dual_hand_data_lock=None, dual_hand_state_array=None, dual_hand_action_array=None):
        logger_mp.info("[Inspire_Controller_FTP] Control process started (Modbus TCP).")

        self.left_hand = InspireHandModbusTCP(self.left_ip, label="LeftHand-ctrl")
        self.right_hand = InspireHandModbusTCP(self.right_ip, label="RightHand-ctrl")
        self.left_hand.connect()
        self.right_hand.connect()

        self.running = True
        left_q_target = np.full(Inspire_Num_Motors, 1.0)
        right_q_target = np.full(Inspire_Num_Motors, 1.0)

        try:
            while self.running:
                start_time = time.time()

                with left_hand_array.get_lock():
                    left_hand_data = np.array(left_hand_array[:]).reshape(25, 3).copy()
                with right_hand_array.get_lock():
                    right_hand_data = np.array(right_hand_array[:]).reshape(25, 3).copy()

                state_data = np.concatenate((np.array(left_hand_state_array[:]), np.array(right_hand_state_array[:])))

                if not np.all(right_hand_data == 0.0) and not np.all(left_hand_data[4] == np.array([-1.13, 0.3, 0.15])):
                    ref_left_value = left_hand_data[self.hand_retargeting.left_indices[1, :]] - left_hand_data[self.hand_retargeting.left_indices[0, :]]
                    ref_right_value = right_hand_data[self.hand_retargeting.right_indices[1, :]] - right_hand_data[self.hand_retargeting.right_indices[0, :]]

                    left_q_target = self.hand_retargeting.left_retargeting.retarget(ref_left_value)[self.hand_retargeting.left_dex_retargeting_to_hardware]
                    right_q_target = self.hand_retargeting.right_retargeting.retarget(ref_right_value)[self.hand_retargeting.right_dex_retargeting_to_hardware]

                    def normalize(val, min_val, max_val):
                        return np.clip((max_val - val) / (max_val - min_val), 0.0, 1.0)

                    for idx in range(Inspire_Num_Motors):
                        if idx <= 3:
                            left_q_target[idx] = normalize(left_q_target[idx], 0.0, 1.7)
                            right_q_target[idx] = normalize(right_q_target[idx], 0.0, 1.7)
                        elif idx == 4:
                            left_q_target[idx] = normalize(left_q_target[idx], 0.0, 0.5)
                            right_q_target[idx] = normalize(right_q_target[idx], 0.0, 0.5)
                        elif idx == 5:
                            left_q_target[idx] = normalize(left_q_target[idx], -0.1, 1.3)
                            right_q_target[idx] = normalize(right_q_target[idx], -0.1, 1.3)

                scaled_left_cmd = [int(np.clip(val * 1000, 0, 1000)) for val in left_q_target]
                scaled_right_cmd = [int(np.clip(val * 1000, 0, 1000)) for val in right_q_target]

                action_data = np.concatenate((left_q_target, right_q_target))
                if dual_hand_state_array and dual_hand_action_array:
                    with dual_hand_data_lock:
                        dual_hand_state_array[:] = state_data
                        dual_hand_action_array[:] = action_data

                self._send_hand_command(scaled_left_cmd, scaled_right_cmd)

                time_elapsed = time.time() - start_time
                sleep_time = max(0, (1 / self.fps) - time_elapsed)
                time.sleep(sleep_time)
        finally:
            self.left_hand.close()
            self.right_hand.close()
            logger_mp.info("Inspire_Controller_FTP (Modbus TCP) has been closed.")
