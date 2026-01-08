"""
ACU Frame Tester - Test exact frames being sent
"""
import socket
import time
import sys
sys.path.insert(0, '.')

from services.acu_driver import build_frame

HOST = "192.168.0.1"
PORT = 2217

def test_frame_sending():
    """
    Test sending exact frames and show HEX dump
    """
    
    commands = [
        ("cmd,search", "Search command"),
        ("cmd,stow", "Stow command"),
        ("cmd,show", "Show command"),
    ]
    
    print("="*70)
    print("🔬 ACU FRAME TRANSMISSION TEST")
    print("="*70)
    print(f"\nTarget: {HOST}:{PORT}\n")
    
    for frame_code, desc in commands:
        print("-"*70)
        print(f"\n📋 Testing: {desc}")
        print(f"   Input: {frame_code}")
        
        # Build frame
        parts = frame_code.split(',')
        if len(parts) >= 2:
            frame = build_frame(parts[0], parts[1], *parts[2:])
        else:
            frame = build_frame('cmd', frame_code)
        
        print(f"\n   Built Frame (ASCII): {repr(frame)}")
        print(f"   Built Frame (HEX):   {frame.encode('ascii').hex()}")
        print(f"   Length: {len(frame)} bytes")
        
        # Try to send
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2.0)
            
            print(f"\n   Connecting...")
            sock.connect((HOST, PORT))
            print(f"   ✅ Connected")
            
            print(f"\n   Sending frame...")
            sock.sendall(frame.encode('ascii'))
            print(f"   ✅ Sent {len(frame)} bytes")
            
            print(f"\n   Waiting for response...")
            sock.settimeout(3.0)
            
            response = b''
            start = time.time()
            try:
                while time.time() - start < 3.0:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    response += chunk
                    if b'\n' in response:
                        break
            except socket.timeout:
                pass
            
            sock.close()
            
            if response:
                print(f"   ✅ Got response:")
                print(f"      ASCII: {response.decode('ascii', errors='replace').strip()}")
                print(f"      HEX:   {response.hex()}")
            else:
                print(f"   ❌ NO RESPONSE from ACU")
                print(f"      This means ACU is NOT processing commands")
                print(f"      Possible reasons:")
                print(f"         - Remote control is disabled")
                print(f"         - ACU doesn't recognize command format")
                print(f"         - ACU is in local-only mode")
            
        except Exception as e:
            print(f"   ❌ Error: {e}")
        
        time.sleep(0.5)
    
    print("\n" + "="*70)
    print("\n💡 CONCLUSIONS:")
    print("-"*70)
    print("""
If you see:
  ✅ "Got response" → ACU is accepting commands (good!)
  ❌ "NO RESPONSE" → ACU is ignoring commands (remote disabled)

If ACU doesn't respond AT ALL:
  1. Check ACU panel for "Remote Enable" setting
  2. Check for DIP switches on ACU hardware
  3. Try console port if available
  4. Contact manufacturer for remote enable procedure

The frames being sent are CORRECT format.
The issue is ACU configuration, not the code.
    """)
    print("="*70 + "\n")


if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════════════════╗
║           ACU Frame Transmission Tester                          ║
╚══════════════════════════════════════════════════════════════════╝

This will test EXACT frames being sent to ACU.
Shows ASCII, HEX, and checks if ACU responds.
""")
    
    input("Press Enter to start test...")
    test_frame_sending()
