# 🚀 Ground Control Station - Quick Start Guide

Welcome to the Team VAJRA Ground Control Station (GCS)! 

This software is the central hub for monitoring your rocket during flight. Don't worry if you don't have programming experience—this guide will walk you through launching and using the software step-by-step.

---

## 🛠️ Step 1: Getting Ready

Before you open the software, make sure your hardware is connected:
1. **Connect the Radio (RX):** Plug your XBee or radio receiver (which receives data from the rocket) into a USB port on your laptop.
2. **Connect the Referee Station (TX):** Plug the official TEKNOFEST RGS hardware into another USB port on your laptop.

---

## 💻 Step 2: Starting the Software

This software runs in two parts: a "Backend" (which talks to the cables) and a "Dashboard" (the screen you look at).

### 1. Start the Backend
1. Open up your computer's **Terminal** (or Command Prompt).
2. Type the following command and press **Enter**:
   ```bash
   python main/gcs_backend.py
   ```
3. *What happens?* You will see some text scrolling. The software is turning on and automatically trying to find your plugged-in USB cables. Leave this black box open in the background!

### 2. Open the Dashboard
1. Open your "File Explorer" and navigate to the folder containing this software.
2. Go into the `main` folder.
3. Double-click the file named **`gcs_dashboard.html`**. 
4. *What happens?* It will open your default web browser (like Chrome or Edge) and show the Mission Control interface!

---

## 🎛️ Step 3: Using the Dashboard

Now that you are looking at the Dashboard, here is a quick tour of what everything means:

### 📡 The Left Panel (Settings & Communication)
- **Port Selection:** At the top left, click "Scan Ports" to find your radio cables. Select your RX port (from the rocket) from the dropdown and click "Connect". 
- **Mission Console:** Below that is a scrolling black box. If you see numbers flying by, congratulations! You are receiving data from the rocket.

### 📊 The Center Panel (Charts & Status)
- **Status Indicators:** Look at the top center. "ROCKET LINK VERIFIED" means the rocket is talking to you. Green means Good. Red means Bad.
- **Flight Phase:** It will legally trace if the rocket is "ON PAD", "IN ASCENT", etc.
- **Live Charts:** Watch the graphs draw lines as the rocket's altitude and speed change in real-time.

### 🗺️ The Right Panel (Recovery Map)
- **GPS Map:** The bottom right shows a real-world map. You will see a Rocket icon hovering over your launch location. Keep an eye on this when it lands—this shows you exactly where to go pick it up!

---

## 🛑 Troubleshooting (FAQ)

**Q: I clicked "Connect" but nothing is happening, and the graphs are empty?**
- Make sure the rocket is turned on.
- Look at the Terminal box (from Step 2). Is it showing an error? Unplug your USB cables and plug them back in, then refresh the web page.

**Q: My "RGS LINK" status says disconnected. Does this matter?**
- **Yes.** If the RGS Link is broken, you cannot launch. Ensure the RGS USB is plugged in, and restart the backend.

---
*Good luck with your launch!* 🚀