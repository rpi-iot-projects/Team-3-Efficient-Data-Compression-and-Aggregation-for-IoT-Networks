
# IoT Bit-Plane Compression Demo

A lightweight, lossless compression framework for continuous IoT sensor streams using FP16 bit-plane disaggregation, dense bit-packing, and 4 KB block compression (LZ4/Zstandard). A Streamlit dashboard enables real-time visualization, compression metrics, network simulation, and CSV export.

---

## Table of Contents

- [IoT Bit-Plane Compression Demo](#iot-bit-plane-compression-demo)
  - [Table of Contents](#table-of-contents)
  - [Features](#features)
  - [Hardware Components](#hardware-components)
  - [Software and Dependencies](#requirements)
  - [Installation](#installation)
  - [Usage](#usage)
    - [Running the Sender](#running-the-sender)
    - [Running the Dashboard](#running-the-dashboard)
  - [How It Works](#how-it-works)
  - [Results \& Demonstration](#results--demonstration)

---

## Features

- **Bit-Plane Disaggregation**  
  Splits each FP16 sample into 16 separate bit-planes and packs bits with NumPy’s `packbits`.  
- **4 KB Block Compression**  
  Divides each packed bit-plane into 4 KB blocks (or one block if smaller) and compresses using LZ4 or Zstandard.  
- **Multi-Sensor Simulation**  
  Generates synthetic temperature and humidity streams for demonstration.  
- **Secure, Framed Transport**  
  Uses a hybrid RSA-OAEP/AES-Fernet scheme and length-prefixed framing over TCP.  
- **Interactive Dashboard**  
  Streamlit UI with controls for history window, bit-planes, codec, bandwidth throttle, and packet-loss simulation.  
- **Metrics & Export**  
  Live chart of reconstructed values, overall and per-plane compression ratios, latency and energy stats, plus CSV download.

---
## Hardware Components

- **Raspberry Pi**
  The more the merrier. Can connect to the central server.
- **Laptop**
  Usual, run of the mill laptop with a browser.
- **Sensors**
  Any variety of sensors that can be interfaced with Raspberry Pi. E.g., BME280 for humidity and TMP36 for temperature etc. 

## Software and Dependencies

- **Python**: 3.7 or newer  
- **Dependencies**:  
  ```bash
  pip install numpy lz4 zstandard streamlit cryptography
  ```

---

## Installation

1. Clone the repository:  
   ```bash
   git clone https://github.com/rpi-iot-projects/Team-3-Efficient-Data-Compression-and-Aggregation-for-IoT-Networks.git
   cd Team-3-Efficient-Data-Compression-and-Aggregation-for-IoT-Networks.git
   ```
2. Install the required Python packages (see [Requirements](#requirements)).

---

## Usage

### Running the Sender

The sender simulates sensor data, applies FP16 conversion, bit-plane packing, block compression, encryption, and serves frames over TCP.

```bash
python pi_offline_sender.py
```

### Running the Dashboard

1. Open `ui_dashboard.py` and set `PI_HOST` to the sender’s IP address.  
2. Launch Streamlit:  
   ```bash
   streamlit run ui_dashboard.py
   ```
3. Use the sidebar to:
   - Adjust the time-window for displayed data  
   - Select how many bit-planes to fetch  
   - Choose compression codec (LZ4, Zstd, or none)  
   - Simulate network bandwidth limits and packet loss  
   - Toggle auto-refresh or fetch manually  
   - Download reconstructed data as CSV  

---

## How It Works

1. **Data Acquisition & FP16 Conversion**  
   Sensor readings (e.g., temperature, humidity) are sampled at a fixed rate and converted from 32-bit floats to IEEE-754 half-precision (FP16).

2. **Bit-Plane Disaggregation & Packing**  
   Each 16-bit FP16 value is split into its individual bits. Bits from the same position across a batch of samples are densely packed into byte arrays.

3. **4 KB Block Compression**  
   Packed bit-plane arrays are segmented into 4 KB chunks (or retained as a single block) and compressed with the chosen codec.

4. **Secure Framing & Transmission**  
   - Raspberry Pi based collector nodes run a key sharing server, that can share AES key upon request using a public RSA key.
   - A fresh AES-128 (Fernet) key is generated per batch and encrypted with RSA-OAEP for secure key exchange.  
   - The encrypted key and compressed payload are each length-prefixed and sent over TCP.
   - An update of AES key can be requested by the central control/deashboard at any time. This allows for a robustly secure, yet fast encryption framework.

5. **Reconstruction & Visualization**  
   The dashboard:
   - Receives and decrypts the AES key, then the payload  
   - Decompresses each bit-plane block and unpacks bits  
   - Reassembles 16-bit words into FP16 values (converted back to float32)  
   - Displays live charts, compression stats, latency, and energy metrics

---

## Results & Demonstration

- **Compression Ratio**: Up to 2.13× for large batches (≈50 % size reduction) compared to monolithic LZ4 on raw FP16.  

- Watch the demo video:  
https://drive.google.com/file/d/1etdjNjO-VFhYkczx4EUn0cCFB4SHXUjU/view?usp=sharing