"""API Client for Vimar VIEW Door."""
import asyncio
import base64
import json
import logging
import re
import ssl
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

_LOGGER = logging.getLogger(__name__)

def encode_device_password(auth_code):
    """Calcola l'hash della password dispositivo esattamente come QvEncrypt.EncodeDevicePassword dell'APK."""
    if not auth_code:
        return ""
    if len(auth_code) == 64:
        return auth_code
    import hashlib
    return hashlib.sha256(auth_code.encode('utf-8')).hexdigest()

class VimarDeviceApi:
    def __init__(self, email="", password="", device_ip=None, client_id="003-2078-a989bc1285e51ad8", oem_id="G0078", app_id="2078", out_auth_code=None, device_id=None, device_name=None):
        self.email = email.strip() if email else ""
        self.password = password.strip() if password else ""
        self.device_ip = device_ip.strip() if device_ip else None
        self.client_id = client_id
        self.oem_id = oem_id
        self.app_id = app_id
        
        self.ssl_ctx = ssl.create_default_context()
        self.ssl_ctx.check_hostname = False
        self.ssl_ctx.verify_mode = ssl.CERT_NONE

        self.qv_account = None
        self.qv_password = None
        self.region_id = 1
        self.host = "r1-2-sec.qvcloud.net"
        self.jsessionid = None
        self.session_id = None
        self.account_id = None
        self.out_auth_code = out_auth_code.strip() if out_auth_code else None
        self.device_id = device_id
        self.device_name = device_name
        self.device_info = {}

        if self.out_auth_code:
            gen_id = hashlib.md5(self.out_auth_code.encode()).hexdigest()[:12]
            self.device_info = {
                "id": self.device_id or f"vimar_{gen_id}",
                "name": self.device_name or "Vimar Intercom",
                "model": "IDS9457AW",
                "out_auth_code": self.out_auth_code
            }

    def authenticate_and_fetch_devices(self):
        """Execute full cloud login and retrieve device list & auth tokens."""
        if self.out_auth_code and self.device_info.get("id"):
            return self.device_info

        if not self.email or not self.password:
            raise ValueError("Missing MyVIMAR credentials: enter email and password or local Auth Code.")

        # 1. OAuth SSO Login
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(),
            urllib.request.HTTPSHandler(context=self.ssl_ctx)
        )

        state_obj = {"mode": "usrpwd", "oem": self.oem_id, "client_id": self.client_id, "rgn": self.region_id}
        state_str = base64.b64encode(json.dumps(state_obj).encode()).decode()
        auth_url = f"https://oauth.vimar.com/it/it/oauth/authorization-code/authorize?scope=openid+email&response_type=code&access_type=offline&client_id=qualvision&redirect_uri=https://sso.qvcloud.net/vimar/callback&state={urllib.parse.quote(state_str)}"

        req1 = urllib.request.Request(auth_url, headers={
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/151.0.7922.199 Mobile Safari/537.36",
            "X-Requested-With": "com.vimar.viewdoor"
        })

        resp1 = opener.open(req1)
        html1 = resp1.read().decode('utf-8', errors='ignore')

        match = re.search(r'<input[^>]*value="([^"]+)"[^>]*name="hash"', html1)
        if not match:
            match = re.search(r'<input[^>]*name="hash"[^>]*value="([^"]+)"', html1)
        csrf_hash = match.group(1) if match else ""

        boundary = "----WebKitFormBoundary" + hex(int(time.time() * 1000))[2:]
        body_data = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="hash"\r\n\r\n{csrf_hash}\r\n'
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="email"\r\n\r\n{self.email}\r\n'
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="passw"\r\n\r\n{self.password}\r\n'
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="go"\r\n\r\n\r\n'
            f"--{boundary}--\r\n"
        ).encode('utf-8')

        login_url = resp1.geturl()
        req2 = urllib.request.Request(login_url, data=body_data, headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/151.0.7922.199 Mobile Safari/537.36",
            "X-Requested-With": "com.vimar.viewdoor",
            "Origin": "https://oauth.vimar.com",
            "Referer": login_url
        })

        resp2 = opener.open(req2)
        raw_sso = resp2.read().decode('utf-8')
        try:
            sso_data = json.loads(raw_sso)
        except Exception as e:
            raise ValueError("Invalid MyVIMAR credentials or service unavailable") from e

        if sso_data.get("result") != 0:
            raise ValueError(f"SSO Login failed: {sso_data}")

        self.qv_account = sso_data["account"]
        self.qv_password = sso_data["password"]
        self.region_id = sso_data.get("rgn", 1)

        # 2. Establish Cloud Duplex
        down_url = f"https://{self.host}/auth/user;jus_duplex=down"
        req_down = urllib.request.Request(down_url, headers={
            "User-Agent": "okhttp/3.12.1",
            "Accept-Language": "it-IT"
        })
        with urllib.request.urlopen(req_down, context=self.ssl_ctx, timeout=10) as resp:
            set_cookie = resp.headers.get("Set-Cookie", "")
            for part in set_cookie.split(";"):
                if "jsessionid=" in part:
                    self.jsessionid = part.strip().split("=")[1]
                    break

        login_xml = f"""<?xml version="1.0" encoding="UTF-8"?><envelope>
   <content class="com.quvii.qvweb.userauth.bean.request.LoginReqContent">
      <account>{self.qv_account}</account>
      <auth-code></auth-code>
      <ip-region-id>{self.region_id}</ip-region-id>
      <password>{self.qv_password}</password>
      <auth-type>0</auth-type>
   </content>
   <header>
      <client>
         <app>{self.app_id}</app>
         <id>{self.client_id}</id>
         <oem>{self.oem_id}</oem>
         <type>3</type>
      </client>
      <command>login</command>
      <flag>tdkcloud</flag>
      <seq>1</seq>
      <user-data></user-data>
      <version>v1.13</version>
   </header>
</envelope>"""

        up_url = f"https://{self.host}/auth/user;jus_duplex=up"
        req_up = urllib.request.Request(up_url, data=login_xml.encode('utf-8'), headers={
            "Content-Type": "application/xml",
            "Cookie": f"jsessionid={self.jsessionid}",
            "User-Agent": "okhttp/3.12.1"
        })
        with urllib.request.urlopen(req_up, context=self.ssl_ctx, timeout=10):
            pass

        down_poll = urllib.request.Request(down_url, headers={
            "Cookie": f"jsessionid={self.jsessionid}",
            "User-Agent": "okhttp/3.12.1"
        })
        with urllib.request.urlopen(down_poll, context=self.ssl_ctx, timeout=10) as resp:
            login_resp_xml = resp.read().decode('utf-8')
            root = ET.fromstring(login_resp_xml)
            self.session_id = root.find(".//session/id").text
            self.account_id = root.find(".//account-id").text

        # 3. Get Device List
        dev_list_xml = f"""<?xml version="1.0" encoding="UTF-8"?><envelope>
   <content class="com.quvii.qvweb.userauth.bean.request.DevListReqContent">
      <count>128</count>
      <filter></filter>
      <manual-accept-device-share>1</manual-accept-device-share>
      <order>0</order>
      <owner></owner>
      <page>0</page>
   </content>
   <header>
      <client>
         <app>{self.app_id}</app>
         <id>{self.client_id}</id>
         <oem>{self.oem_id}</oem>
         <type>3</type>
      </client>
      <command>get-device-list</command>
      <flag>tdkcloud</flag>
      <seq>2</seq>
      <session>{self.session_id}</session>
      <user-data></user-data>
      <version>v1.13</version>
   </header>
</envelope>"""

        req_up2 = urllib.request.Request(up_url, data=dev_list_xml.encode('utf-8'), headers={
            "Content-Type": "application/xml",
            "Cookie": f"jsessionid={self.jsessionid}",
            "User-Agent": "okhttp/3.12.1"
        })
        with urllib.request.urlopen(req_up2, context=self.ssl_ctx, timeout=10):
            pass

        with urllib.request.urlopen(down_poll, context=self.ssl_ctx, timeout=10) as resp:
            xml_data = resp.read().decode('utf-8')
            root = ET.fromstring(xml_data)
            dev = root.find(".//device")
            if dev is not None:
                self.device_info = {
                    "id": dev.find("id").text if dev.find("id") is not None else "doorbell",
                    "name": dev.find("name").text if dev.find("name") is not None else "Vimar Intercom",
                    "model": dev.find("model").text if dev.find("model") is not None else "IDS9457AW",
                    "out_auth_code": dev.find("out-auth-code").text if dev.find("out-auth-code") is not None else "",
                    "data_encode_key": dev.find("data-encode-key").text if dev.find("data-encode-key") is not None else "",
                    "dynamic_password": dev.find("dynamic-password").text if dev.find("dynamic-password") is not None else ""
                }
                self.out_auth_code = self.device_info["out_auth_code"]
                return self.device_info
            raise ValueError("No devices found in Vimar account.")

    def _build_digest_header(self, auth_header_val, username, password):
        """Genera l'header Authorization Digest conforme a DeviceAuthHeaderInterceptor dell'APK."""
        import hashlib
        fields = {}
        raw_params = re.sub(r'^Digest\s+', '', auth_header_val.strip(), flags=re.IGNORECASE)
        for part in re.split(r',\s*(?=[a-zA-Z0-9_]+=)', raw_params):
            if '=' in part:
                k, v = part.split('=', 1)
                fields[k.strip()] = v.strip().strip('"')

        realm = fields.get("realm", "")
        nonce = fields.get("nonce", "")
        opaque = fields.get("opaque", "")
        qop = fields.get("qop", "auth")

        if not realm or not nonce:
            return None

        ha1 = hashlib.md5(f"{username}:{realm}:{password}".encode('utf-8')).hexdigest()
        ha2 = hashlib.md5("POST:/tdkcgi".encode('utf-8')).hexdigest()
        nc = "nc00001"
        cnonce = "suiji"
        resp_str = f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}"
        response = hashlib.md5(resp_str.encode('utf-8')).hexdigest()

        return f'Digest username="{username}",realm="{realm}",nonce="{nonce}",uri="/tdkcgi",algorithm=MD5,response="{response}",opaque="{opaque}",qop={qop},nc={nc},cnonce="{cnonce}"'

    def discover_intercom_ip(self):
        """Scansiona la sottorete locale in parallelo per aggiornare l'IP se cambiato dal DHCP del router."""
        import socket
        from concurrent.futures import ThreadPoolExecutor, as_completed

        subnet_base = ".".join(self.device_ip.split(".")[:3]) if (self.device_ip and "." in self.device_ip) else "192.168.1"
        ips = [f"{subnet_base}.{i}" for i in range(1, 255)]

        def probe_ip(ip):
            req = urllib.request.Request(
                f"https://{ip}/tdkcgi",
                data=b"<envelope><body><command>get.device.status</command></body></envelope>",
                headers={"Content-Type": "application/xml", "User-Agent": "okhttp/3.12.1"}
            )
            try:
                with urllib.request.urlopen(req, context=self.ssl_ctx, timeout=1.2) as resp:
                    data = resp.read(100).decode("utf-8", errors="ignore")
                    if "<envelope" in data:
                        return ip
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    return ip
            except Exception:
                pass
            return None

        with ThreadPoolExecutor(max_workers=50) as ex:
            futures = [ex.submit(probe_ip, ip) for ip in ips]
            for f in as_completed(futures):
                found_ip = f.result()
                if found_ip:
                    _LOGGER.info("Vimar Intercom rediscovered at IP: %s (previously %s)", found_ip, self.device_ip)
                    self.device_ip = found_ip
                    return found_ip
        return None

    def local_cgi_command(self, command_name, content_xml="", is_retry=False):
        """Execute a local CGI command directly on LAN with Digest Auth support."""
        if not self.device_ip:
            self.discover_intercom_ip()
            if not self.device_ip:
                raise ValueError("Device IP not configured for local LAN communication.")
        if not self.out_auth_code:
            self.authenticate_and_fetch_devices()

        encoded_pwd = encode_device_password(self.out_auth_code)
        username = "adminapp2"

        xml_body = f"""<envelope>
   <body>
      <command>{command_name}</command>
      {content_xml if content_xml else '<content class="com.quvii.qvweb.device.bean.requset.Content"/>'}
   </body>
   <header>
      <password>{encoded_pwd}</password>
      <passwordencode>1</passwordencode>
      <security>username</security>
      <username>{username}</username>
   </header>
</envelope>"""

        urls_to_try = []
        if self.device_ip.startswith("http://") or self.device_ip.startswith("https://"):
            urls_to_try.append(f"{self.device_ip.rstrip('/')}/tdkcgi")
        else:
            urls_to_try.append(f"https://{self.device_ip}/tdkcgi")
            urls_to_try.append(f"http://{self.device_ip}/tdkcgi")

        headers = {
            "Content-Type": "application/xml; charset=UTF-8",
            "User-Agent": "okhttp/3.12.1"
        }

        last_error = None
        for url in urls_to_try:
            req = urllib.request.Request(url, data=xml_body.encode('utf-8'), headers=headers)
            ctx = self.ssl_ctx if url.startswith("https") else None
            try:
                with urllib.request.urlopen(req, context=ctx, timeout=4) as resp:
                    return resp.read().decode('utf-8')
            except urllib.error.HTTPError as e:
                if e.code == 401 and "WWW-Authenticate" in e.headers:
                    auth_hdr = e.headers["WWW-Authenticate"]
                    digest_auth = self._build_digest_header(auth_hdr, username, encoded_pwd)
                    if digest_auth:
                        retry_headers = dict(headers)
                        retry_headers["Authorization"] = digest_auth
                        req_retry = urllib.request.Request(url, data=xml_body.encode('utf-8'), headers=retry_headers)
                        with urllib.request.urlopen(req_retry, context=ctx, timeout=4) as resp_retry:
                            return resp_retry.read().decode('utf-8')
                last_error = e
                break
            except Exception as e:
                last_error = e
                continue

        if last_error:
            if not is_retry:
                new_ip = self.discover_intercom_ip()
                if new_ip:
                    return self.local_cgi_command(command_name, content_xml=content_xml, is_retry=True)
            raise last_error

    def get_status(self):
        """Fetch real-time device status."""
        try:
            res = self.local_cgi_command("get.device.status")
            root = ET.fromstring(res)
            status_elem = root.find(".//devicestatus")
            status = {}
            if status_elem is not None:
                for child in status_elem:
                    status[child.tag] = child.text == "true"
            
            # Product info
            info_elem = root.find(".//info")
            if info_elem is not None:
                for child in info_elem:
                    status[f"info_{child.tag}"] = child.text
            return status
        except Exception as err:
            _LOGGER.warning(f"Error fetching Vimar status: {err}")
            return {}

    def _stream_unlock(self, locknumber=2, channel=1, is_retry=False):
        """Esegue lo sblocco fisico del relè tramite flusso multimediale UMSP port 34567."""
        import socket
        import struct
        import hashlib
        import time

        if not self.device_ip or not self.out_auth_code:
            return False

        # 1. Recupera chiave AES dal citofono
        try:
            res_key = self.local_cgi_command("get.device.streamkey")
            root = ET.fromstring(res_key.strip())
            key_elem = root.find(".//key")
            if key_elem is None or not key_elem.text:
                return False
            key = key_elem.text.strip().encode("ascii")
        except Exception as e:
            _LOGGER.warning(f"Errore lettura streamkey su {self.device_ip}: {e}")
            if not is_retry:
                new_ip = self.discover_intercom_ip()
                if new_ip:
                    return self._stream_unlock(locknumber=locknumber, channel=channel, is_retry=True)
            return False

        iv = b"0" * 16

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5.0)
            s.connect((self.device_ip, 34567))

            # Handshake SendFastPlay (0xaa) con auth_code grezzo 64 car.
            username = "adminapp2"
            payload = f"{username}&&{self.out_auth_code}\x00\x00\x00".encode("ascii")
            raw_len = len(payload)
            pad_len = (16 - ((raw_len + 32) % 16)) % 16
            enc_len = raw_len + 32 + pad_len

            header = bytearray(32)
            header[0] = 0xaa
            now_ts = int(time.time())
            struct.pack_into("<Q", header, 1, now_ts)
            struct.pack_into("<H", header, 9, enc_len)
            struct.pack_into("<H", header, 11, raw_len)
            struct.pack_into("<H", header, 13, channel)  # idc = channel (es. 1)
            header[15] = 0x01
            header[16] = 0x01  # ids - 1 = 1
            header[17] = 0x00

            sha = hashlib.sha256(header + payload).digest()
            enc_payload = _aes_cbc_encrypt(key, iv, payload + sha)
            s.sendall(bytes(header) + enc_payload)

            rep = s.recv(1024)
            if len(rep) < 32:
                s.close()
                return False

            # Invio pacchetto Transparent UNLOCK (cmd=0x04)
            # lockId: 1 = Pedonale (LOCK1), 2 = Carrabile (GATE1)
            unlock_data = bytearray()
            unlock_data.append(locknumber & 0xFF)
            unlock_data.append(0x00)
            unlock_data.append(channel & 0xFF)
            unlock_data.append(0x01)
            unlock_data.extend(b"\x00" * 12)
            unlock_data.extend(self.out_auth_code.encode("ascii"))

            trans_header = bytearray(32)
            trans_header[0] = 0xfe
            struct.pack_into("<Q", trans_header, 1, now_ts)
            pad_len_u = (16 - ((len(unlock_data) + 32) % 16)) % 16
            enc_len_u = len(unlock_data) + 32 + pad_len_u
            struct.pack_into("<H", trans_header, 9, enc_len_u)
            struct.pack_into("<H", trans_header, 11, len(unlock_data))
            trans_header[13] = 0x04  # VIDEO_CHANNEL_ORDER_UNLOCK

            sha_u = hashlib.sha256(trans_header + unlock_data).digest()
            enc_u = _aes_cbc_encrypt(key, iv, unlock_data + sha_u)
            s.sendall(bytes(trans_header) + enc_u)

            # Invia contemporaneamente anche CGI durante lo stream caldo
            cgi_xml = f"""<content class="com.quvii.qvweb.device.bean.requset.DeviceUnlockContent">
   <door>{channel}</door>
   <locknumber>{locknumber}</locknumber>
   <password>{self.out_auth_code}</password>
</content>"""
            try:
                self.local_cgi_command("set.device.opendoor", cgi_xml)
            except Exception:
                pass

            time.sleep(0.3)
            s.close()
            return True
        except Exception as err:
            _LOGGER.warning(f"Errore sblocco UMSP stream su {self.device_ip}: {err}")
            if not is_retry:
                new_ip = self.discover_intercom_ip()
                if new_ip:
                    return self._stream_unlock(locknumber=locknumber, channel=channel, is_retry=True)
            return False

    def unlock(self, door=1, locknumber=1):
        """
        Sblocca porta o cancello:
        - locknumber=1: Pedonale (LOCK1)
        - locknumber=2: Carrabile (GATE1)
        """
        if not self.out_auth_code:
            self.authenticate_and_fetch_devices()

        if locknumber == 2:
            # Per il carrabile: procedura di streaming autenticato
            stream_ok = self._stream_unlock(locknumber=2, channel=door)
            if stream_ok:
                return True
            return self._stream_unlock(locknumber=2, channel=0)
        else:
            # Per il pedonale: stessa identica procedura di streaming autenticato
            stream_ok = self._stream_unlock(locknumber=1, channel=door)
            if stream_ok:
                return True
            return self._stream_unlock(locknumber=1, channel=0)


def _aes_cbc_encrypt(key_bytes, iv_bytes, plaintext):
    """Cifra in AES-256-CBC con padding zero a 16 byte, compatibile con HA OS / Linux / Mac."""
    plaintext = bytes(plaintext)
    pad_len = (16 - (len(plaintext) % 16)) % 16
    padded = plaintext + b'\x00' * pad_len

    # Metodo 1: cryptography (nativo e garantito in Home Assistant Core)
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.backends import default_backend
        cipher = Cipher(algorithms.AES(key_bytes), modes.CBC(iv_bytes), backend=default_backend())
        encryptor = cipher.encryptor()
        return encryptor.update(padded) + encryptor.finalize()
    except Exception:
        pass

    # Metodo 2: pycryptodome / pycrypto
    try:
        from Crypto.Cipher import AES
        c = AES.new(key_bytes, AES.MODE_CBC, iv_bytes)
        return c.encrypt(padded)
    except Exception:
        pass

    # Metodo 3: ctypes libcrypto fallback (macOS / Linux)
    import ctypes
    import ctypes.util
    for libname in ['/opt/homebrew/lib/libcrypto.dylib', 'libcrypto.so.3', 'libcrypto.so.1.1', ctypes.util.find_library('crypto')]:
        if not libname:
            continue
        try:
            c_lib = ctypes.CDLL(libname)
            class _AES_KEY(ctypes.Structure):
                _fields_ = [('rd_key', ctypes.c_uint32 * 60), ('rounds', ctypes.c_int)]
            k = _AES_KEY()
            c_lib.AES_set_encrypt_key(key_bytes, len(key_bytes) * 8, ctypes.byref(k))
            ivec = ctypes.create_string_buffer(bytes(iv_bytes), 16)
            in_buf = ctypes.create_string_buffer(padded, len(padded))
            out_buf = ctypes.create_string_buffer(len(padded))
            c_lib.AES_cbc_encrypt(in_buf, out_buf, len(padded), ctypes.byref(k), ivec, 1)
            return out_buf.raw
        except Exception:
            continue

    raise RuntimeError("Nessun modulo di crittografia AES disponibile")

