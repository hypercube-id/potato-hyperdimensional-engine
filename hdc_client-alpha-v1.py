# =====================================================================
#  Project PHDE: Potato HyperDimensional Engine
#  Copyright (C) 2026 The Hub Studio
#  GPLv3
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#  GNU General Public License for more details.
# =====================================================================
import os
import sys
import socket
import struct
import argparse
import numpy as np

HOST = "127.0.0.1"
PORT = 8080
VECTOR_SIZE_64 = 157

# Binary Protocol Commands
CMD_ADD = 1
CMD_VIEW = 2
CMD_BACKUP = 3

def generate_random_vector() -> bytes:
    """Generates a random 10,048-D bitpacked vector (1256 bytes)."""
    rand_ints = np.random.randint(0, 2**64, size=VECTOR_SIZE_64, dtype=np.uint64)
    return rand_ints.tobytes()

def add_file(filename: str, filepath: str):
    """Reads a file, registers its indexing key, and uploads it to the PHDE server."""
    if not os.path.exists(filepath):
        print(f"[-] Error: Local file '{filepath}' not found.")
        return
        
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
        
    # Generate a unique coordinate vector key for this file
    # (This behaves like the file's conceptual 'fingerprint')
    vector_bytes = generate_random_vector()
    
    # Save the key locally so you can use it to query the database later
    vector_path = f"{filename}.key"
    with open(vector_path, "wb") as f_vec:
        f_vec.write(vector_bytes)
    print(f"[*] Generated unique coordinate key -> Saved to '{vector_path}'")
    
    filename_bytes = filename.encode('utf-8')
    content_bytes = content.encode('utf-8')
    
    # Pack structural data: 4 bytes for payload length, 2 bytes for filename length
    header = struct.pack("!IH", len(content_bytes), len(filename_bytes))
    
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((HOST, PORT))
            # 1-byte Command + 1256-byte Vector + sizes header + filename + content
            s.sendall(bytes([CMD_ADD]))
            s.sendall(vector_bytes + header + filename_bytes + content_bytes)
            
            # Await transactional confirmation
            resp_len_bytes = s.recv(4)
            if not resp_len_bytes:
                print("[-] Server cut connection early.")
                return
            resp_len = struct.unpack("!I", resp_len_bytes)[0]
            response = s.recv(resp_len).decode('utf-8')
            print(f"[+] Server Response: {response}")
            
    except ConnectionRefusedError:
        print("[-] Error: Could not connect to PHDE server. Is it running?")

def search_file(key_path: str):
    """Sends a coordinate key to the server to perform a zero-overhead search sweep."""
    if not os.path.exists(key_path):
        print(f"[-] Error: Coordinate key file '{key_path}' does not exist.")
        return
        
    with open(key_path, "rb") as f:
        vector_bytes = f.read()
        
    if len(vector_bytes) != 1256:
        print("[-] Error: Key is corrupt. Must be exactly 1256 bytes.")
        return
        
    # Option to introduce noise to show off the robustness of high-dimensional math
    noise = input("Simulate high-dimensional signal noise? (y/N): ").strip().lower() == 'y'
    if noise:
        vector_array = np.frombuffer(vector_bytes, dtype=np.uint64).copy()
        # Flip bit values in 5 structural registers to mock fuzzy-search environments
        for idx in [5, 33, 72, 115, 142]:
            vector_array[idx] ^= 0xFFFFFFFFFFFFFFFF
        vector_bytes = vector_array.tobytes()
        print("[*] Modified index state with ~3% artificial coordinate drift.")

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((HOST, PORT))
            s.sendall(bytes([CMD_VIEW]))
            s.sendall(vector_bytes)
            
            resp_len_bytes = s.recv(4)
            if not resp_len_bytes:
                print("[-] Server returned no search results.")
                return
            resp_len = struct.unpack("!I", resp_len_bytes)[0]
            
            # Stream response body safely
            data = bytearray()
            while len(data) < resp_len:
                chunk = s.recv(resp_len - len(data))
                if not chunk:
                    break
                data.extend(chunk)
                
            response = data.decode('utf-8')
            
            if response.startswith("MATCH"):
                _, filename, similarity, file_content = response.split("|", 3)
                print("\n" + "="*60)
                print("[i]CONTEXTUAL FILE IDENTIFIED")
                print("="*60)
                print(f"File Name:  {filename}")
                print(f"Confidence: {float(similarity)*100:.2f}% Match")
                print("-"*60)
                print(f"Payload:\n{file_content}")
                print("="*60 + "\n")
            else:
                print(f"[-] Search Response: {response}")
                
    except ConnectionRefusedError:
        print("[-] Error: Connection refused by server.")

def retrieve_backup(output_zip: str):
    """Requests and streams a complete database and physical storage backup file."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((HOST, PORT))
            s.sendall(bytes([CMD_BACKUP]))
            
            # Get 4-byte archive size
            size_bytes = s.recv(4)
            if not size_bytes:
                print("[-] Server failed to initialize backup stream.")
                return
            zip_size = struct.unpack("!I", size_bytes)[0]
            print(f"[*] Downloading unified backup archive ({zip_size:,} bytes)...")
            
            # Stream directly to output path
            received = bytearray()
            while len(received) < zip_size:
                chunk = s.recv(min(4096, zip_size - len(received)))
                if not chunk:
                    break
                received.extend(chunk)
                
            with open(output_zip, "wb") as f:
                f.write(received)
                
            print(f"[+] Offline storage backup successfully written to: '{output_zip}'")
            
    except ConnectionRefusedError:
        print("[-] Error: Connection refused by server.")

# =====================================================================
# CLI PARSER CONFIGURATION
# =====================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Potato HyperDimensional Engine (PHDE) CLI Interface")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # Add File
    add_parser = subparsers.add_parser("add", help="Index and register a new local file")
    add_parser.add_argument("filename", type=str, help="Logical filename in the engine database")
    add_parser.add_argument("filepath", type=str, help="Path to local file content")
    
    # Search Vector
    search_parser = subparsers.add_parser("search", help="Query database using a generated key file")
    search_parser.add_argument("key_path", type=str, help="Path to local .key file")
    
    # System Backup
    backup_parser = subparsers.add_parser("backup", help="Download complete database state")
    backup_parser.add_argument("--out", type=str, default="phde_vault_backup.zip", help="Destination file")
    
    args = parser.parse_args()
    
    if args.command == "add":
        add_file(args.filename, args.filepath)
    elif args.command == "search":
        search_file(args.key_path)
    elif args.command == "backup":
        retrieve_backup(args.out)
