# =====================================================================
#  Project PHDE: Potato HyperDimensional Engine
#  Copyright (C) 2026 The Hub Studio. All Rights Reserved.
# =====================================================================
#  DUAL-LICENSE NOTICE:
#
#  This file is part of Project PHDE. This software is dual-licensed, 
#  and you may choose to use it under the terms of either:
#
#  TRACK A: GNU Affero General Public License version 3 (AGPLv3)
#  as published by the Free Software Foundation. This program is 
#  distributed in the hope that it will be useful, but WITHOUT ANY 
#  WARRANTY; without even the implied warranty of MERCHANTABILITY or 
#  FITNESS FOR A PARTICULAR PURPOSE. See the GNU Affero General Public 
#  License for more details at <https://www.gnu.org/licenses/>.
#
#  OR
#
#  TRACK B: The Hub Studio Commercial Proprietary License.
#  If you have obtained a commercial license agreement from The Hub 
#  Studio, your use of this source code is governed exclusively by 
#  the terms of that agreement. Commercial use or network deployment 
#  without a valid commercial agreement is strictly prohibited.
# =====================================================================
import os
import sys
import socket
import struct
import threading
import shutil
from hdc_engine import UnifiedStorageEngine, HDCVectorClass, DATABASE_FILE, PAYLOAD_DIR

HOST = "127.0.0.1"
PORT = 8080

# Command Definitions
CMD_ADD = 1
CMD_VIEW = 2
CMD_BACKUP = 3

class HDCTCPServer:
    def __init__(self, host=HOST, port=PORT):
        self.host = host
        self.port = port
        self.engine = UnifiedStorageEngine()
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    def start(self):
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)
        print(f"[*] HDC Unified Server listening on {self.host}:{self.port}...")
        
        try:
            while True:
                client_sock, addr = self.server_socket.accept()
                print(f"[*] Connection accepted from {addr[0]}:{addr[1]}")
                # Spin up a thread to prevent blocking
                client_thread = threading.Thread(target=self.handle_client, args=(client_sock,))
                client_thread.daemon = True
                client_thread.start()
        except KeyboardInterrupt:
            print("\n[*] Shutting down server...")
        finally:
            self.server_socket.close()

    def recv_all(self, sock, length):
        """Helper to guarantee we read exactly the number of bytes requested."""
        data = bytearray()
        while len(data) < length:
            packet = sock.recv(length - len(data))
            if not packet:
                return None
            data.extend(packet)
        return bytes(data)

    def handle_client(self, sock):
        try:
            # 1. Read the 1-byte command header
            cmd_data = sock.recv(1)
            if not cmd_data:
                return
            cmd = cmd_data[0]

            # 2. Command ADD: Register a file index
            if cmd == CMD_ADD:
                print("    [ADD] Request received. Processing packet headers...")
                # Read 1256 bytes (vector) + 4 bytes (payload length) + 2 bytes (filename length)
                header = self.recv_all(sock, 1256 + 4 + 2)
                vector_bytes = header[0:1256]
                payload_len, filename_len = struct.unpack("!IH", header[1256:])
                
                # Read variable data
                filename = self.recv_all(sock, filename_len).decode('utf-8')
                content = self.recv_all(sock, payload_len).decode('utf-8')
                
                # Convert raw incoming bytes back to our C-aligned struct
                vector = HDCVectorClass()
                import ctypes
                ctypes.memmove(vector.data, vector_bytes, 1256)
                
                # Save
                file_hash = self.engine.add_file(filename, content, vector)
                
                # Respond with status and SHA-256 hash
                response_payload = f"SUCCESS:{file_hash}".encode('utf-8')
                sock.sendall(struct.pack("!I", len(response_payload)) + response_payload)
                print(f"    [ADD] Successfully registered '{filename}' -> Hash: {file_hash[:10]}...")

            # 3. Command VIEW: Search for a conceptual index match
            elif cmd == CMD_VIEW:
                print("    [VIEW] Query request received. Reading search vector...")
                # Read 1256-byte search vector
                vector_bytes = self.recv_all(sock, 1256)
                
                vector = HDCVectorClass()
                import ctypes
                ctypes.memmove(vector.data, vector_bytes, 1256)
                
                # Scan vector database using our fast C sweep
                result = self.engine.search_vector(vector, threshold=0.75)
                
                if result:
                    # Read the file content from disk
                    with open(result['payload_path'], 'r') as f:
                        file_data = f.read()
                    
                    # Pack and respond
                    response_str = f"MATCH|{result['filename']}|{result['similarity']:.4f}|{file_data}"
                else:
                    response_str = "ERR:No matching files found under the threshold."
                
                response_bytes = response_str.encode('utf-8')
                sock.sendall(struct.pack("!I", len(response_bytes)) + response_bytes)
                print("    [VIEW] Search complete. Query response dispatched.")

            # 4. Command BACKUP: Create unified index + storage archive and stream it
            elif cmd == CMD_BACKUP:
                print("    [BACKUP] Export requested. Compressing physical database and payload state...")
                backup_zip_name = "hdc_vault_export"
                
                # Generate a temporary zip archive of both SQLite DB and the physical /payloads/ directory
                shutil.make_archive(backup_zip_name, 'zip', base_dir=PAYLOAD_DIR)
                
                # Create a temporary directory to bundle both the SQLite DB and file assets
                temp_bundle_dir = "./temp_bundle"
                os.makedirs(temp_bundle_dir, exist_ok=True)
                shutil.copy2(DATABASE_FILE, temp_bundle_dir)
                if os.path.exists(PAYLOAD_DIR):
                    shutil.copytree(PAYLOAD_DIR, os.path.join(temp_bundle_dir, "payloads"), dirs_exist_ok=True)
                
                shutil.make_archive(backup_zip_name, 'zip', temp_bundle_dir)
                zip_file_path = f"{backup_zip_name}.zip"
                
                # Stream zip file directly over the socket
                zip_size = os.path.getsize(zip_file_path)
                sock.sendall(struct.pack("!I", zip_size)) # 4-byte size header
                
                with open(zip_file_path, "rb") as f:
                    shutil.copyfileobj(f, sock)
                
                # Clean up temporary bundle files
                os.remove(zip_file_path)
                shutil.rmtree(temp_bundle_dir)
                print(f"    [BACKUP] Streamed {zip_size:,} bytes of complete state package to client.")

        except Exception as e:
            print(f"    [Error] Client processing halted: {e}")
        finally:
            sock.close()

if __name__ == "__main__":
    server = HDCTCPServer()
    server.start()
