from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization, hashes
import socket

def generate_rsa_key_pair(key_size: int = 2048):
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=key_size
    )
    public_key = private_key.public_key()
    return private_key, public_key

def encrypt_message(public_key, message: bytes) -> bytes:
    ciphertext = public_key.encrypt(
        message,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None
        )
    )
    return ciphertext


def decrypt_message(private_key, ciphertext: bytes) -> bytes:
    plaintext = private_key.decrypt(
        ciphertext,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None
        )
    )
    return plaintext

##################### RSA KEY LOADING AND SERIALIZATION #####################

def serialize_private_key(private_key, password: bytes = None) -> bytes:
    encryption_algo = (
        serialization.BestAvailableEncryption(password) if password
        else serialization.NoEncryption()
    )
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=encryption_algo
    )
    return pem


def serialize_public_key(public_key) -> bytes:
    pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return pem

def load_private_key(pem_data: bytes, password: bytes = None):
    private_key = serialization.load_pem_private_key(
        pem_data,
        password=password
    )
    return private_key


def load_public_key(pem_data: bytes):
    public_key = serialization.load_pem_public_key(pem_data)
    return public_key

###################### AES KEY ######################
from cryptography.fernet import Fernet
AES_key = b'6RI6X-764VwOTixq5lUSNBoR7tKy-Qo0FTOHlkvy2XI='
fernet = Fernet(AES_key)


###################### RSA COMMUNICATION ###################### 

def send_data(sock: socket.socket, data: bytes) -> None:
    # Prefix message with a 4-byte length header (big-endian)
    length = len(data).to_bytes(4, 'big')
    sock.sendall(length + data)

def receive_data(sock: socket.socket) -> bytes:
    # Read the 4-byte length header
    length_bytes = sock.recv(4)
    if not length_bytes:
        raise ConnectionError("Socket closed before reading data length")
    length = int.from_bytes(length_bytes, 'big')

    # Read the actual data
    data = b''
    while len(data) < length:
        packet = sock.recv(length - len(data))
        if not packet:
            raise ConnectionError("Socket closed during data reception")
        data += packet
    return data