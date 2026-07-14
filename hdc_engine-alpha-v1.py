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
import time
import ctypes
import sqlite3
import platform
import subprocess
import numpy as np

# =====================================================================
# CONFIGURATION & CONSTANTS
# =====================================================================
VECTOR_DIMENSIONS = 10048 # Must match 157 * 64 bits
VECTOR_SIZE_64 = 157      # 157 uint64 integers = 10,048 bits
DATABASE_FILE = "hdc_vault.db"
PAYLOAD_DIR = "./payloads"

# Ensure clean setup directories
os.makedirs(PAYLOAD_DIR, exist_ok=True)

# =====================================================================
# 1. GENERATE THE COMPACT C ENGINE SOURCE CODE
# =====================================================================
C_SOURCE_CODE = """
#include <stdint.h>
#include <stdlib.h>

#define VECTOR_SIZE_64 157

typedef struct {
    uint64_t data[VECTOR_SIZE_64];
} HDCVector;

#ifdef _WIN32
    #define EXPORT __declspec(dllexport)
#else
    #define EXPORT
#endif

// High-speed, single-instruction POPCNT vector similarity calculator
EXPORT double hdc_similarity(const HDCVector* vec1, const HDCVector* vec2) {
    uint64_t total_diff_bits = 0;
    for (int i = 0; i < VECTOR_SIZE_64; i++) {
        #ifdef _MSC_VER
            total_diff_bits += __popcnt64(vec1->data[i] ^ vec2->data[i]);
        #else
            total_diff_bits += __builtin_popcountll(vec1->data[i] ^ vec2->data[i]);
        #endif
    }
    double total_bits = VECTOR_SIZE_64 * 64.0;
    return 1.0 - ((double)total_diff_bits / total_bits);
}

EXPORT void hdc_bind(const HDCVector* vec1, const HDCVector* vec2, HDCVector* result) {
    for (int i = 0; i < VECTOR_SIZE_64; i++) {
        result->data[i] = vec1->data[i] ^ vec2->data[i];
    }
}

// THE ZERO-TAX BATCH ENGINE
// Processes the search query entirely on bare metal.
// Python passes a contiguous memory buffer of DB vectors once.
EXPORT int hdc_search_batch(const HDCVector* query_vec, const HDCVector* db_vectors, int count, double threshold, double* out_best_similarity) {
    int best_idx = -1;
    double max_sim = -1.0;
    
    for (int i = 0; i < count; i++) {
        double sim = hdc_similarity(query_vec, &db_vectors[i]);
        if (sim > max_sim) {
            max_sim = sim;
            best_idx = i;
        }
    }
    
    *out_best_similarity = max_sim;
    if (max_sim >= threshold) {
        return best_idx;
    }
    return -1; // No matching concept exceeds the threshold
}
"""

# =====================================================================
# 2. AUTOMATIC COMPILATION & PACKAGING WORKFLOW
# =====================================================================
def compile_and_load():
    c_file = "hdc_core.c"
    with open(c_file, "w") as f:
        f.write(C_SOURCE_CODE.strip())
        
    system = platform.system()
    if system == "Windows":
        lib_file = "hdc_core.dll"
        compile_cmd = ["gcc", "-shared", "-o", lib_file, c_file, "-O3", "-march=native"]
    elif system == "Darwin":
        lib_file = "hdc_core.dylib"
        compile_cmd = ["clang", "-shared", "-o", lib_file, c_file, "-O3", "-march=native"]
    else:
        lib_file = "hdc_core.so"
        compile_cmd = ["gcc", "-shared", "-fPIC", "-o", lib_file, c_file, "-O3", "-march=native"]
        
    print(f"[Core] Compiling bare-metal shared library using Compiler command...")
    subprocess.run(compile_cmd, check=True)
    
    # Load with ctypes
    lib_path = os.path.abspath(lib_file)
    lib = ctypes.CDLL(lib_path)
    
    # Map interfaces
    class HDCVector(ctypes.Structure):
        _fields_ = [("data", ctypes.c_uint64 * VECTOR_SIZE_64)]
        
    lib.hdc_bind.argtypes = [ctypes.POINTER(HDCVector), ctypes.POINTER(HDCVector), ctypes.POINTER(HDCVector)]
    lib.hdc_bind.restype = None
    
    lib.hdc_similarity.argtypes = [ctypes.POINTER(HDCVector), ctypes.POINTER(HDCVector)]
    lib.hdc_similarity.restype = ctypes.c_double
    
    lib.hdc_search_batch.argtypes = [
        ctypes.POINTER(HDCVector),
        ctypes.POINTER(HDCVector),
        ctypes.c_int,
        ctypes.c_double,
        ctypes.POINTER(ctypes.c_double)
    ]
    lib.hdc_search_batch.restype = ctypes.c_int
    
    return lib, HDCVector

# Instantiating high-performance runtime binding
HDC_LIB, HDCVectorClass = compile_and_load()

# =====================================================================
# 3. UNIFIED SQLITE DATABASE & INDEX CONTROLLER
# =====================================================================
class UnifiedStorageEngine:
    def __init__(self):
        self.conn = sqlite3.connect(DATABASE_FILE)
        self.cursor = self.conn.cursor()
        self.init_database()

    def init_database(self):
        # Stores both raw file index tracking and serialized 10,000-D coordinate vector
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS hdc_file_index (
                file_hash TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                payload_path TEXT NOT NULL,
                hdc_vector BLOB NOT NULL
            )
        """)
        self.conn.commit()

    def add_file(self, filename: str, content: str, vector: HDCVectorClass):
        # 1. Write the physical payload to our isolated directory
        import hashlib
        file_hash = hashlib.sha256(content.encode()).hexdigest()
        physical_path = os.path.join(PAYLOAD_DIR, f"{file_hash}.bin")
        
        with open(physical_path, "w") as f:
            f.write(content)
            
        # 2. Serialize raw memory structure of our 157 uint64 integers into SQLite BLOB
        vector_bytes = bytes(vector)
        
        # 3. Write metadata and vector directly inside an atomic transaction
        self.cursor.execute(
            "INSERT OR REPLACE INTO hdc_file_index (file_hash, filename, payload_path, hdc_vector) VALUES (?, ?, ?, ?)",
            (file_hash, filename, physical_path, vector_bytes)
        )
        self.conn.commit()
        return file_hash

    def search_vector(self, query_vector: HDCVectorClass, threshold=0.6) -> dict:
        """Runs the search sweep entirely in optimized C, zero Python allocation loops."""
        # Pull down all records
        self.cursor.execute("SELECT file_hash, filename, payload_path, hdc_vector FROM hdc_file_index")
        records = self.cursor.fetchall()
        
        if not records:
            return None
            
        count = len(records)
        
        # Construct a contiguous, flat C-array in Python memory structure
        # (Equivalent to: HDCVector database_vectors[count])
        C_Vector_Array_Type = HDCVectorClass * count
        c_vector_array = C_Vector_Array_Type()
        
        # Directly move binary blobs straight to C pointers bypassing object deserializations
        for idx, row in enumerate(records):
            ctypes.memmove(c_vector_array[idx].data, row[3], len(row[3]))
            
        # Call the single border-crossing dynamic batch compiler sweep
        best_sim = ctypes.c_double(0.0)
        match_idx = HDC_LIB.hdc_search_batch(
            ctypes.byref(query_vector),
            c_vector_array,
            count,
            threshold,
            ctypes.byref(best_sim)
        )
        
        if match_idx != -1:
            matched_record = records[match_idx]
            return {
                "file_hash": matched_record[0],
                "filename": matched_record[1],
                "payload_path": matched_record[2],
                "similarity": best_sim.value
            }
        return None

# =====================================================================
# HELPER UTILITIES
# =====================================================================
def create_random_vector() -> HDCVectorClass:
    rand_ints = np.random.randint(0, 2**64, size=VECTOR_SIZE_64, dtype=np.uint64)
    vec = HDCVectorClass()
    for i in range(VECTOR_SIZE_64):
        vec.data[i] = int(rand_ints[i])
    return vec

# =====================================================================
# 4. EXECUTION FLOW & VALIDATION DEPLOYMENT
# =====================================================================
if __name__ == "__main__":
    print("-" * 75)
    print("HYPERDIMENSIONAL COMPUTING HARDWARE ENGINE PROTOTYPE INITIALIZED")
    print("-" * 75)
    
    # Initialize unified index engine
    engine = UnifiedStorageEngine()
    
    # Generate static, distinct vector coordinate markers
    system_log_vector = create_random_vector()
    network_conf_vector = create_random_vector()
    credential_key_vector = create_random_vector()
    
    # Save simulated physical payloads and their HDC indexes
    print("\n[Unified Engine] Populating unified local vault...")
    engine.add_file("system_diagnostics.log", "ERROR: CPU Core 3 Thermal Exceeded Threshold.", system_log_vector)
    engine.add_file("static_routing.conf", "IP ROUTE 10.0.0.0/24 VIA 192.168.1.1", network_conf_vector)
    engine.add_file("access_keys.pem", "ssh-rsa AAAAB3NzaC1yc2E...== key", credential_key_vector)
    print("                 Stored 3 unified payloads and updated SQLite index indexes.")
    
    # Simulate a "Fuzzy Search Query" (Let's query for a vector close to network configuration)
    # We create a noisy variant of network_conf_vector to mimic conceptual retrieval.
    query_vector = HDCVectorClass()
    ctypes.memmove(query_vector.data, network_conf_vector.data, 1256)
    
    # We mutate exactly 5 elements out of 157 to simulate conceptual noise/fuzziness (~3% error margin)
    for index in [12, 45, 88, 120, 144]:
        query_vector.data[index] = query_vector.data[index] ^ 0xFFFFFFFFFFFFFFFF
        
    print("\n[Retrieval] Executing high-dimensional indexing scan...")
    result = engine.search_vector(query_vector, threshold=0.75)
    
    if result:
        print(f"            MATCH FOUND!")
        print(f"            ---------------------------------------")
        print(f"            Filename   : {result['filename']}")
        print(f"            Hash ID    : {result['file_hash']}")
        print(f"            Local Path : {result['payload_path']}")
        print(f"            Similarity : {result['similarity'] * 100:.2f}% Match")
        print(f"            ---------------------------------------")
    else:
        print("            No matching coordinate cluster was located.")
        
    # =====================================================================
    # 5. ZERO-TAX BATCH SPEED BENCHMARK
    # =====================================================================
    print("\n[Benchmark] Stress testing Batch Pointer Sweeping performance...")
    print("            Scaling internal vault load to 10,000 synthetic indexed records in-memory.")
    
    # Generate 10,000 mock database indexes
    C_Vector_Array_Type = HDCVectorClass * 10000
    benchmark_db_array = C_Vector_Array_Type()
    for idx in range(10000):
        # Populating raw memory array
        rand_ints = np.random.randint(0, 2**64, size=VECTOR_SIZE_64, dtype=np.uint64)
        for d_idx in range(VECTOR_SIZE_64):
            benchmark_db_array[idx].data[d_idx] = int(rand_ints[d_idx])
            
    # Measure total execution speed over 10,000 records
    out_similarity = ctypes.c_double(0.0)
    iterations = 500 # Perform 500 complete database query sweeps (500 sweeps * 10,000 rows = 5,000,000 evaluations)
    
    start_time = time.perf_counter()
    for _ in range(iterations):
        _ = HDC_LIB.hdc_search_batch(
            ctypes.byref(query_vector),
            benchmark_db_array,
            10000,
            0.85,
            ctypes.byref(out_similarity)
        )
    end_time = time.perf_counter()
    
    total_time = end_time - start_time
    time_per_sweep = (total_time / iterations) * 1000 # Milliseconds per sweep
    
    print("-" * 75)
    print(f"      SWEEPS PROCESSED       : {iterations:,} database search sweeps")
    print(f"      SWEEP SIZE             : 10,000 index rows per run")
    print(f"      TOTAL RUNTIME          : {total_time:.5f} seconds")
    print(f"      LATENCY PER FULL SWEEP : {time_per_sweep:.3f} milliseconds (ms)")
    print(f"      COMPUTES PER SECOND    : {int((iterations * 10000) / total_time):,} vector similarities/sec")
    print("-" * 75)
