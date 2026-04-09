"""List serial COM ports for button bridge debugging."""

import serial.tools.list_ports


print("Scanning COM ports...")
print("=" * 50)

ports = serial.tools.list_ports.comports()

if not ports:
    print("No COM ports found.")
    print("Check USB cable and driver installation.")
else:
    print(f"Found {len(ports)} COM port(s):\n")
    for idx, port in enumerate(ports, 1):
        print(f"{idx}. {port.device}")
        print(f"   Description: {port.description}")
        print(f"   HWID: {port.hwid}\n")

print("=" * 50)
print("midi_bridge.py now auto-detects Mega boards from their READY banner.")
print("Use this helper only to confirm which COM ports are currently visible.")
input("\nPress Enter to close...")
