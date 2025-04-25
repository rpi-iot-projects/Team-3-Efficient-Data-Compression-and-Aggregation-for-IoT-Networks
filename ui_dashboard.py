#!/usr/bin/env python3
"""
Streamlit dashboard for FP-16 bit-plane demo (4  KB blocks, bit-level packing).
• Fetches compressed segments, decompresses, unpacks bits,
  concatenates per-plane bits across segments, reconstructs FP16 values
• Shows live chart, overall + per-plane ratios, latencies
• Simulates bandwidth throttle & packet loss
• CSV download (unique key each refresh)
"""
import json, socket, struct, time, random
from datetime import datetime, timedelta
import numpy as np, pandas as pd
import lz4.frame as lz4, zstandard as zstd
import streamlit as st

import iot_proj_crypto

PI_HOST = "127.0.0.1"      # ← your Pi IP
PORT    = 50007

def recvall(sock,n):
    buf=bytearray()
    while len(buf)<n:
        chunk=sock.recv(n-len(buf))
        if not chunk: raise ConnectionError("socket closed")
        buf.extend(chunk)
    return buf

def decompress(block, hdr):
    if hdr["algo"]=="lz4":
        try:
            return np.frombuffer(lz4.decompress(block),dtype=np.uint8)
        except Exception as e:
            print(f"{hdr['algo']}: {e}")
            return np.frombuffer(b"lhello", dtype=np.uint8)
    elif hdr["algo"]=="zstd":
        try:
            return np.frombuffer(zstd.ZstdDecompressor(max_window_size=2147483648).decompress(block),dtype=np.uint8)
        except Exception as e:
            print(f"{hdr['algo']}: {e}")
            return np.frombuffer(b"zhello", dtype=np.uint8)
    else:
        try:
            return block
        except Exception as e:
            print(f"{hdr['algo']}: {e}")
            return np.frombuffer(b"uhello", dtype=np.uint8)


# ---------- fetch & reconstruct -----------------------------------------
def fetch(seconds_back, planes_req, algo, net_quality):
    now=time.time()
    req=dict(from_=now-seconds_back, to=now, planes=planes_req, algo=algo, net_quality=net_quality)
    rb=json.dumps(req).replace("from_","from").encode()

    t0=time.time()
    with socket.create_connection((PI_HOST,PORT),timeout=4) as s:
        s.sendall(struct.pack("!I",len(rb))); s.sendall(rb)
        frame_len=struct.unpack("!I",recvall(s,4))[0]
        frame=recvall(s,frame_len)

    net_ms=(time.time()-t0)*1000

    frame = iot_proj_crypto.fernet.decrypt(bytes(frame))

    hlen=struct.unpack("!I",frame[:4])[0]
    hdr=json.loads(frame[4:4+hlen])
    mv=memoryview(frame[4+hlen:])

    # choose decompression
    decomp = lambda b: decompress(b, hdr)

    sensors=hdr["sensors"]; planes=hdr["planes"]
    groups={p:[] for p in planes}
    off=0
    for seg in hdr["segments"]:
        for i,p in enumerate(planes):
            n_bits=seg["plane_num_bits"][i]
            bits=[]
            for sz in seg["plane_block_sizes"][i]:
                bits.append(decomp(mv[off:off+sz])); off+=sz
            bits=np.unpackbits(np.concatenate(bits))[:n_bits]
            groups[p].append(bits)

    total_vals=sum(seg["samples"]*sensors for seg in hdr["segments"])
    vals=np.zeros(total_vals,dtype=np.uint16)
    for p,bits_list in groups.items():
        bits=np.concatenate(bits_list)
        vals|=(bits.astype(np.uint16)<<p)
    fp=vals.view(np.float16).astype(np.float32).reshape(-1,sensors)
    return fp,hdr,net_ms

# ---------- Streamlit UI -------------------------------------------------
st.set_page_config("IoT Bit-plane Dashboard",layout="wide")
st.title("FP-16 Bit-plane Compression Demo (4  KB blocks, bit-packed)")

with st.sidebar:
    seconds     = st.slider("History window (s)",5,300,60,5)
    planes      = st.slider("Requested bit-planes",7,16,12)
    codec       = st.selectbox("Codec",["lz4","zstd", "uncompressed"],0)
    period      = st.slider("Auto-refresh (s)",1,30,3)
    net_quality = st.slider("Simulated network quality",0,100,10)
    auto        = st.checkbox("Auto-refresh",True)
    once        = st.button("Fetch once")
    csv_box     = st.sidebar.empty()

chart = st.empty(); stats = st.empty(); table = st.expander("Per-plane",False)
hist  = pd.DataFrame()

def push(arr,names):
    global hist
    hist = pd.DataFrame()
    now=datetime.utcnow(); n=len(arr)
    times=[now-timedelta(seconds=(n-i-1)*seconds/n) for i in range(n)]
    df=pd.DataFrame(arr,index=pd.to_datetime(times),columns=names)
    # hist=pd.concat([hist,df]).last(f"{seconds}s")
    hist=pd.concat([hist,df])
    threshold = hist.index.max() - pd.Timedelta(seconds=seconds)
    hist = hist.loc[hist.index >= threshold]

def csv_dl():
    csv_box.empty()
    csv=hist.to_csv(index_label="timestamp")
    csv_box.download_button("Download CSV",csv,"sensor_history.csv","text/csv",
                            key=f"csv_{int(time.time()*1000)}")

###################### KEY COMMUNICATION SECTION ######################
# 1. IoT-node generates RSA pub/priv key pair.
# 2. IoT-node sends the RSA pub key to Control-center.
# 3. Control-center encrypts AES key using RSA pub key.
# 4. Control-center sends encrypted AES key to IoT-node.
# 5. IoT-node uses priv key to decrypt AES key.

# 2. Control-center receives the RSA pub key from IoT-node
client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

print("Attempting to connect to IoT-node.")
client_sock.connect((PI_HOST, PORT+1))
server_pub = iot_proj_crypto.receive_data(client_sock)
public_key = iot_proj_crypto.load_public_key(server_pub)
print("RSA public key received")

# 3. Control-center encrypts AES key using RSA pub key.
AES_key = iot_proj_crypto.Fernet.generate_key()
print(f"Generated AES Key: {AES_key}\nWill encrypt it with RSA public key and send to the IoT-node")
AES_key_enc = iot_proj_crypto.encrypt_message(public_key, AES_key)

# 4. Control-center sends encrypted AES key to IoT-node.
iot_proj_crypto.send_data(client_sock, AES_key_enc)

client_sock.close()

############################# MAIN LOOP #############################
while True:
    if auto or once:
        try:
            data,hdr,net=fetch(seconds,planes,codec,net_quality)
            push(data,hdr["sensor_names"])
            chart.line_chart(hist)
            ci=hdr["compression_info"]
            stats.markdown(
f"""
**Samples (window):** {hist.shape[0]} × {hdr['sensors']}  
**Planes sent:** {len(hdr['planes'])}/{planes}  **Ratio:** {ci['compression_ratio']}×  
**Compressed:** {ci['compressed_bytes']}  B  
**Avg comp lat (sender):** {ci['avg_compression_latency_ms']}  ms    
**RTT:** {net:.2f}  ms
""")
            seg0=hdr["segments"][0]
            table.dataframe(pd.DataFrame({
                "Plane": hdr["planes"],
                "#Blocks":[len(x) for x in seg0["plane_block_sizes"]],
                "CompBytes":[sum(x) for x in seg0["plane_block_sizes"]],
                "Ratio": seg0["plane_block_ratios"]
            }))
            csv_dl()
        except Exception as e:
            stats.error(f"Fetch failed: {e}")
        once=False
    if not auto:
        break
    time.sleep(period)