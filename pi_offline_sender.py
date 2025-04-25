#!/usr/bin/env python3

import socket, struct, json, threading, time, collections, random, math
import numpy as np, lz4.frame as lz4, zstandard as zstd

import iot_proj_crypto

# ─── parameters ─────────────────────────────────────────────
SAMPLE_HZ      = 10
BATCH_SAMPLES  = 256
CACHE_BATCHES  = 120
COMP_ALGO      = "lz4"           # or "zstd"
HOST, PORT     = "", 50007
BLOCK_BYTES    = 4096            # 4 KB
# ─────────────────────────────────────────────────────────────

# Simulated sensors
SENSORS = ["temperature", "humidity"]
NUM_SENSORS = len(SENSORS)

def synth_temp(t): return 25.0 + 2.0*math.sin(t/120) + random.uniform(-.05,.05)
def synth_hum(t):  return 50.0 + 5.0*math.cos(t/150) + random.uniform(-.2,.2)
SIM_FUN = {"temperature": synth_temp, "humidity": synth_hum}

# Bit-plane policy: always send sign+exponent, then top mantissa bits
MANDATORY = {15,14,13,12,11,10}
def choose_planes(requested:int):
    extra = max(0, requested-len(MANDATORY))
    mant  = list(range(9, 9-extra, -1))
    return sorted(MANDATORY.union(mant))

# ---------- compression helpers -----------------------------------------
def compress_blocks(packed: np.ndarray, comp):
    """Return (sizes, blobs) where each blob ≤ BLOCK_BYTES."""
    if packed.nbytes == 0:
        return [], []
    sizes, blobs = [], []
    for off in range(0, len(packed), BLOCK_BYTES):
        blob = comp(packed[off:off+BLOCK_BYTES].tobytes())
        blobs.append(blob); sizes.append(len(blob))
    return sizes, blobs

# ---------- batch cache structure ---------------------------------------
Batch = collections.namedtuple(
    "Batch",
    "start_ts end_ts samples plane_blocks plane_block_sizes comp_time_ms"
)
cache_lock = threading.Lock()
batch_cache = collections.deque(maxlen=CACHE_BATCHES)

# ---------- producer thread ---------------------------------------------
def producer():
    buf = np.empty((BATCH_SAMPLES, NUM_SENSORS), np.float16)
    idx = 0
    while True:
        t = time.time()
        for i, name in enumerate(SENSORS):
            buf[idx,i] = np.float16(SIM_FUN[name](t))
        idx += 1
        if idx == BATCH_SAMPLES:
            compress_and_store(buf.copy())
            idx = 0
        time.sleep(1/SAMPLE_HZ)

def compress():
    if COMP_ALGO=="lz4":
        return (lambda block: lz4.compress(block,0))
    elif COMP_ALGO=="zstd":
        return zstd.ZstdCompressor(level=3).compress
    else:
        return (lambda block: block)
        
# ---------- compress one batch ------------------------------------------
def compress_and_store(batch_fp16):
    t0 = time.time()
    u16 = batch_fp16.flatten().view(np.uint16)
    n_vals = u16.size

    # 16 bit-planes densely packed
    planes_packed = []
    for b in range(16):
        bits  = ((u16 >> b) & 1).astype(np.uint8)
        planes_packed.append((np.packbits(bits), n_vals))  # (bytes, num_bits)

    #comp = (lambda a: lz4.compress(a,0)) if COMP_ALGO=="lz4" else zstd.ZstdCompressor(level=1).compress
    comp = compress()

    plane_blocks, plane_sizes = [], []
    for packed, _ in planes_packed:
        sizes, blobs = compress_blocks(packed, comp)
        plane_blocks.append(blobs)
        plane_sizes.append(sizes)

    comp_ms = (time.time()-t0)*1000
    now = time.time()
    with cache_lock:
        batch_cache.append(Batch(now-BATCH_SAMPLES/SAMPLE_HZ, now,
                                 BATCH_SAMPLES, plane_blocks,
                                 plane_sizes, comp_ms))

# ---------- networking ---------------------------------------------------
def handle_client(conn):
    global COMP_ALGO
    try:
        rlen = struct.unpack("!I", conn.recv(4))[0]
        req  = json.loads(conn.recv(rlen).decode())
        planes = choose_planes(req.get("planes",16))
        COMP_ALGO = req.get("algo", "lz4")
        base_delay_ms = (100 - req.get("net_quality"))/1000
        #print(delay)
        # print(f"COMP_ALGO: {COMP_ALGO}")
        t0,t1  = req["from"], req["to"]

        with cache_lock:
            segs = [b for b in batch_cache if not (b.end_ts<t0 or b.start_ts>t1)]
        if not segs:
            conn.close(); return

        hdr = dict(algo=COMP_ALGO,dtype="fp16",planes=planes,
                   sensor_names=SENSORS,sensors=NUM_SENSORS,segments=[])

        payload, total_cbytes, total_bits = [], 0, 0
        for seg in segs:
            sinfo = dict(start=seg.start_ts,end=seg.end_ts,samples=seg.samples,
                         plane_block_sizes=[],plane_block_ratios=[],plane_num_bits=[])
            for p in planes:
                sizes = seg.plane_block_sizes[p]
                blobs = seg.plane_blocks[p]
                payload.extend(blobs)
                cbytes = sum(sizes)
                n_bits = seg.samples*NUM_SENSORS
                raw_bytes = (n_bits+7)//8
                sinfo["plane_block_sizes"].append(sizes)
                sinfo["plane_block_ratios"].append(round(raw_bytes/cbytes,3))
                sinfo["plane_num_bits"].append(n_bits)
                total_cbytes += cbytes
            total_bits += seg.samples*NUM_SENSORS*16
            hdr["segments"].append(sinfo)

        hdr["compression_info"] = dict(
            compressed_bytes = total_cbytes,
            compression_ratio= round((total_bits//8)/total_cbytes,3),
            avg_compression_latency_ms = round(sum(s.comp_time_ms for s in segs)/len(segs),2)
        )

        hbytes = json.dumps(hdr).encode()
        frame  = struct.pack("!I",len(hbytes))+hbytes+b"".join(payload)
        frame = iot_proj_crypto.fernet.encrypt(frame)
        # print(frame)
        # Insert delay here. Function of delay:(100-network quality)
        time.sleep(base_delay_ms/hdr['compression_info']['compression_ratio'])
        conn.sendall(struct.pack("!I",len(frame))); conn.sendall(frame)
        print(f"🛰  sent {len(segs)} batch(es)  ratio {hdr['compression_info']['compression_ratio']}×")
    finally: conn.close()

def server():
    with socket.create_server((HOST,PORT),reuse_port=True) as srv:
        print(f"sender on :{PORT}  ({COMP_ALGO}, 4 KB blocks)")
        while True:
            c,_ = srv.accept()
            threading.Thread(target=handle_client,args=(c,),daemon=True).start()

###################### KEY COMMUNICATION SECTION ######################
# 1. IoT-node generates RSA pub/priv key pair.
# 2. IoT-node sends the RSA pub key to Control-center.
# 3. Control-center encrypts AES key using RSA pub key.
# 4. Control-center sends encrypted AES key to IoT-node.
# 5. IoT-node uses priv key to decrypt AES key.

# 1. Key generation
private_key, public_key = iot_proj_crypto.generate_rsa_key_pair()
print(f"private_key: {private_key}\npublic_key: {public_key}")

def key_sharing_server():
    # 2. sending the pub key
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_sock:
        server_sock.bind(("", PORT+1))
        server_sock.listen(1)

        while True:
            print(f"Key sharing server waiting for connection on port {PORT+1}...")
            conn, addr = server_sock.accept()

            print(f"Connection accepted from {addr} for RSA public key communication")

            iot_proj_crypto.send_data(conn, iot_proj_crypto.serialize_public_key(public_key))

            # 4. Control-center sends encrypted AES key to IoT-node. 
            AES_key_enc = iot_proj_crypto.receive_data(conn)

            # 5. IoT-node uses priv key to decrypt AES key.
            AES_key = iot_proj_crypto.decrypt_message(private_key, AES_key_enc)

            print(f"Received AES key: {AES_key}")
            conn.close()

############################# MAIN LOOP #############################
if __name__=="__main__":
    threading.Thread(target=key_sharing_server,daemon=True).start()
    threading.Thread(target=producer,daemon=True).start()
    server()