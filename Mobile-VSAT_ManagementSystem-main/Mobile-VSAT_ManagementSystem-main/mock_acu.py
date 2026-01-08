import socket
import threading
import time
import random

HOST = '0.0.0.0'
PORT = 2217

def xor_checksum(payload: str) -> str:
    """Calculate 2-digit HEX checksum (XOR of bytes)."""
    csum = 0
    for b in payload.encode("ascii"):
        csum ^= b
    return f"{csum:02X}"

def build_response(frame_type: str, *args) -> str:
    """Build a protocol frame with checksum."""
    content = f"${frame_type}," + ",".join(map(str, args))
    csum = xor_checksum(content[1:]) # exclude $
    return f"{content}*{csum}\r\n"

# Global state for the Mock ACU
ACU_STATE = {
    "az": 120.0,
    "el": 45.0,
    "pol": 0.0,
    "target_az": 120.0,
    "target_el": 45.0,
    "target_pol": 0.0,
    "scanned_az": 120.0, # for showing movement
    "scanned_el": 45.0,
    "scanned_pol": 0.0,
}

def update_simulation():
    """Simple simulation to move current pos towards target."""
    step = 2.0 # degrees per poll
    
    for axis in ["az", "el", "pol"]:
        curr = ACU_STATE[axis]
        target = ACU_STATE[f"target_{axis}"]
        
        if abs(curr - target) < step:
            ACU_STATE[axis] = target
        elif curr < target:
            ACU_STATE[axis] += step
        else:
            ACU_STATE[axis] -= step

def handle_client(conn, addr):
    print(f"Connection from {addr}")
    buffer = ""
    try:
        while True:
            data = conn.recv(1024)
            if not data:
                break
            
            # Append new data to buffer
            buffer += data.decode('ascii', errors='ignore')
            
            # Process all complete lines in the buffer
            while '\n' in buffer:
                line, buffer = buffer.split('\n', 1)
                line = line.strip()
                if not line:
                    continue
            
                print(f"Received: {line}")
                
                # Update simulation state on every command receipt
                update_simulation()
                
                # Simple command parsing
                if "cmd,show" in line.lower() or "get show" in line.lower():
                    # Use state variables
                    curr_azi = ACU_STATE["az"] + random.uniform(-0.05, 0.05)
                    curr_ele = ACU_STATE["el"] + random.uniform(-0.05, 0.05)
                    curr_pol = ACU_STATE["pol"]
                    
                    # Target is what we set
                    azi = ACU_STATE["target_az"]
                    ele = ACU_STATE["target_el"]
                    pol = ACU_STATE["target_pol"]
                    
                    status = "track" if abs(curr_azi - azi) < 1.0 else "search"
                    heading = 180.0
                    pitch = 0.0
                    roll = 0.0
                    
                    resp = build_response(
                        "show", 
                        f"{azi:.1f}", f"{ele:.1f}", f"{pol:.1f}", 
                        f"{curr_azi:.1f}", f"{curr_ele:.1f}", f"{curr_pol:.1f}",
                        status,
                        f"{heading:.1f}", f"{pitch:.1f}", f"{roll:.1f}",
                        "106.8", "-6.2", # Lon/Lat (Jakarta approx)
                        "lock", # GPS
                        "0000", # Limits
                        "0000", # Alerts
                        f"{random.uniform(2.0, 4.5):.2f}", # AGC
                        "0", "0", # Pots
                        "2023-11-20 10:00:00" # Time
                    )
                    conn.sendall(resp.encode('ascii'))
                    
                elif "cmd,sat" in line.lower() and len(line.split(',')) < 3:
                    # Read SAT
                    resp = build_response(
                        "cmd,sat",
                        "MOCK-SAT", "11000", "1500", "256", "113.0", "0", "5.0"
                    )
                    conn.sendall(resp.encode('ascii'))
                    
                elif "cmd,place" in line.lower() and len(line.split(',')) < 3:
                     # Read PLACE
                    resp = build_response(
                        "cmd,place",
                        "106.8456", "-6.2088", "180.0"
                    )
                    conn.sendall(resp.encode('ascii'))

                # ✅ NEW handlers for Manual Control to prevent timeout crash
                elif "cmd,dir" in line.lower():
                    # $cmd,dir,AZ,EL,POL*CS
                    # Remove checksum if present
                    content = line.split('*')[0]
                    parts = content.split(',')
                    
                    if len(parts) >= 5:
                        try:
                            # parts[0]=$cmd, [1]=dir, [2]=az, [3]=el, [4]=pol
                            ACU_STATE["target_az"] = float(parts[2])
                            ACU_STATE["target_el"] = float(parts[3])
                            ACU_STATE["target_pol"] = float(parts[4])
                            print(f" -> Moving to AZ={parts[2]} EL={parts[3]} POL={parts[4]}")
                        except ValueError as e:
                            print(f"Error parsing manual command: {e}")
                    
                    # Echo back
                    conn.sendall(f"{line}\r\n".encode('ascii'))
                    
                elif "cmd,dirx" in line.lower():
                     # $cmd,dirx,sport,...*CS
                    conn.sendall(f"{line}\r\n".encode('ascii'))
                    
                elif "cmd,manual" in line.lower():
                    # $cmd,manual,dir,speed*CS
                    conn.sendall(f"{line}\r\n".encode('ascii'))
                    
                else:
                    conn.sendall(f"{line}\r\n".encode('ascii'))
                
    except ConnectionResetError:
        pass
    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()
        print(f"Connection closed: {addr}")

def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((HOST, PORT))
    server.listen(5)
    print(f"Mock ACU Server listening on {HOST}:{PORT}")
    
    while True:
        conn, addr = server.accept()
        t = threading.Thread(target=handle_client, args=(conn, addr))
        t.start()

if __name__ == "__main__":
    main()
