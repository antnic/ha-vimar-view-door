# Vimar VIEW Door - Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/default)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2023.1%2B-blue.svg)](https://www.home-assistant.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Custom component for **Home Assistant** to control **Vimar VIEW Door** video intercoms (e.g. model `IDS9457AW`, Qualvision / QVCloud platform) directly over the local network (LAN).

Enables full **LAN actuation** of both the **Pedestrian Gate / Door** and the **Driveway Gate**, real-time doorbell call events, and motion detection without any ongoing cloud dependency.

---

## ✨ Features

* 🚪 **Pedestrian Door Strike:** Dedicated `lock` and `button` entities (`LOCK1`, lock ID 1).
* 🚗 **Driveway Gate:** Dedicated `lock` and `button` entities (`GATE1`, lock ID 2).
* 🍏 **Apple HomeKit & Homebridge Ready:** Locks feature an automatic **5-second pulse auto-relock timer**. When unlocked via Apple Home or Siri (*"Hey Siri, open the driveway gate"*), the state automatically returns to *"Locked"* without needing a second tap!
* 🔒 **100% Offline Local Operation:** Once configured with your device's 64-character Auth Code, all communication stays strictly within your LAN with zero cloud dependency.
* 🔄 **Dynamic IP Auto-Discovery & Auto-Healing:** If your home router changes the intercom's IP via DHCP, the integration automatically scans the local subnet in ~1 second, updates the IP, and keeps working seamlessly.
* 🔔 **Real-Time Binary Sensors & Diagnostics:**
  * Doorbell Call in progress (`calling`)
  * Human Presence detection (`humandete`)
  * Pedestrian (`smd_peds`) and Vehicle (`smd_vehc`) detection
  * Device firmware version and MAC address sensors

---

## 🛠️ How It Works (Protocol Overview)

Vimar VIEW Door intercoms enforce hardware protection in their firmware:
1. Sending simple HTTP CGI requests (`/tdkcgi`) returns `error=0` syntactically, but **will not energize the physical gate relay**.
2. To trigger the physical lock relays, the intercom requires an active and verified **UMSP / FastPlay binary streaming session** over **TCP port 34567**.
3. This integration connects directly to TCP port 34567, performs the `0xaa` FastPlay handshake encrypted in **AES-256-CBC**, and transmits the proprietary transparent binary command `cmd=4` (`SendUnlockData`) synchronized with the CGI pulse.

---

## 📦 Installation

### Method 1: Via HACS (Recommended)
1. Ensure [HACS](https://hacs.xyz/) is installed in your Home Assistant.
2. In HACS, click the three dots in the top right ➔ **Custom repositories**.
3. Add the repository URL:
   ```text
   https://github.com/antnic/ha-vimar-view-door
   ```
4. Select category **Integration** and click **Add**.
5. Search for **Vimar VIEW Door** and click **Download**.
6. **Restart Home Assistant**.

---

### Method 2: Manual Installation
1. Clone or download this repository.
2. Copy the `custom_components/vimar_view_door` directory into your Home Assistant's `config/custom_components/` folder:
   ```text
   config/
   └── custom_components/
       └── vimar_view_door/
           ├── __init__.py
           ├── binary_sensor.py
           ├── button.py
           ├── config_flow.py
           ├── const.py
           ├── lock.py
           ├── manifest.json
           ├── sensor.py
           ├── strings.json
           ├── vimar_api.py
           └── translations/
               ├── en.json
               └── it.json
   ```
3. **Restart Home Assistant**.

---

## 🔑 Retrieving your Device Auth Code (Local Token)

To operate in **100% Offline Local Mode** (recommended, no MyVIMAR credentials stored in Home Assistant), you need the 64-character **Auth Code** associated with your video intercom.

A helper script is provided in the `tools/` directory:

1. Run the script on your computer:
   ```bash
   python3 tools/get_auth_code.py
   ```
2. Enter your **MyVIMAR** email and password when prompted.
3. The script will securely authenticate with MyVIMAR OAuth and display your device information:
   ```text
   🎉 FOUND 1 DEVICE(S):
     • Name:      Main Entrance
     • Model:     IDS9457AW
     • Device ID: 2502424...
     • AUTH CODE: a1b2c3d4e5f6... (64 hex characters)
   ```
4. Copy the **AUTH CODE** to use during Home Assistant setup.

---

## ⚙️ Configuration in Home Assistant

1. In Home Assistant, navigate to **Settings** ➔ **Devices & Services** ➔ **Add Integration**.
2. Search for **Vimar VIEW Door**.
3. Choose one of the two setup options:

### Option A: Direct Local Mode (Recommended - 100% Offline)
* **MyVIMAR Email:** *(leave blank)*
* **MyVIMAR Password:** *(leave blank)*
* **Local IP Address:** Enter your intercom's LAN IP address (e.g. `192.168.1.100`).
* **Auth Code / Token:** Paste the 64-character Auth Code obtained from `tools/get_auth_code.py`.

### Option B: Cloud Mode
* **MyVIMAR Email:** Your MyVIMAR account email.
* **MyVIMAR Password:** Your MyVIMAR account password.
* **Local IP Address:** Your intercom's LAN IP address (e.g. `192.168.1.100`).
* **Auth Code / Token:** *(leave blank)*

Click **Submit**. The integration will discover and configure your locks, buttons, and sensors immediately.

---

## 📱 Apple HomeKit & Siri Integration

When exposing the lock entities to Apple Home (via Home Assistant's built-in *HomeKit Bridge* or *Homebridge*):
* Tapping the lock or using Siri (*"Open the pedestrian gate"*) triggers the pulse unlock.
* After **5 seconds**, the lock state automatically resets to **"Locked"**, ready for the next activation without requiring manual reset.

---

## 💡 Network Tip

While the integration includes automatic subnet scanning to rediscover your intercom if its IP changes, it is strongly recommended to set a **static IP / DHCP reservation** in your router for your intercom's MAC address.

---

## 📄 License

Released under the [MIT License](LICENSE).

---

## ⚠️ Disclaimer
This project is an independent community project and is not affiliated with, endorsed by, or sponsored by Vimar S.p.A. or Qualvision. All product names, trademarks, and registered trademarks are the property of their respective owners.
