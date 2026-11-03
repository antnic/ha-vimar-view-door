"""API Client for Vimar VIEW Door."""
import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import logging
import re
import socket
import ssl
import struct
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

_LOGGER = logging.getLogger(__name__)

def _get_cloud_ssl_context():
    """Get a verifying SSL context for cloud communication."""
    try:
        from homeassistant.util.ssl import client_context
        return client_context()
    except Exception:
        return ssl.create_default_context()

def _get_local_ssl_context():
    """Get an unverified SSL context for local intercom (self-signed cert)."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx

def encode_device_password(auth_code):
    """Calcola l'hash della password dispositivo esattamente come QvEncrypt.EncodeDevicePassword dell'APK."""
    if not auth_code:
        return ""
    if len(auth_code) == 64:
        return auth_code
    return hashlib.sha256(auth_code.encode('utf-8')).hexdigest()

class VimarDeviceApi:
    def __init__(
        self,
        email="",
        password="",
        device_ip=None,
        client_id="003-2078-a989bc1285e51ad8",
        oem_id="G0078",
        app_id="2078",
        out_auth_code=None,
        device_id=None,
        device_name=None,
        device_mac=None,
    ):
        self.email = email.strip() if email else ""
        self.password = password.strip() if password else ""
        self.device_ip = device_ip.strip() if device_ip else None
        self.client_id = client_id
        self.oem_id = oem_id
        self.app_id = app_id
        
        self.cloud_ssl_ctx = _get_cloud_ssl_context()
        self.local_ssl_ctx = _get_local_ssl_context()

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
        self.device_mac = (device_mac or "").strip().lower() or None
        self.device_info = {}

        self._last_discovery_time = 0.0
        self._discovery_backoff = 180.0  # 3 minutes initial backoff
        self._discovery_lock = threading.Lock()

        if self.out_auth_code:
            gen_id = hashlib.md5(self.out_auth_code.encode()).hexdigest()[:12]
            self.device_info = {
                "id": self.device_id or f"vimar_{gen_id}",
                "name": self.device_name or "Vimar Intercom",
                "model": "IDS9457AW",
                "out_auth_code": self.out_auth_code,
                "mac": self.device_mac or "",
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
            urllib.request.HTTPSHandler(context=self.cloud_ssl_ctx)
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
        with urllib.request.urlopen(req_down, context=self.cloud_ssl_ctx, timeout=10) as resp:
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
        with urllib.request.urlopen(req_up, context=self.cloud_ssl_ctx, timeout=10):
            pass

        down_poll = urllib.request.Request(down_url, headers={
            "Cookie": f"jsessionid={self.jsessionid}",
            "User-Agent": "okhttp/3.12.1"
        })
        with urllib.request.urlopen(down_poll, context=self.cloud_ssl_ctx, timeout=10) as resp:
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
        with urllib.request.urlopen(req_up2, context=self.cloud_ssl_ctx, timeout=10):
            pass

        with urllib.request.urlopen(down_poll, context=self.cloud_ssl_ctx, timeout=10) as resp:
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
                self.device_id = self.device_info["id"]
                return self.device_info
            raise ValueError("No devices found in Vimar account.")

    def _build_digest_header(self, auth_header_val, username, password):
        """Genera l'header Authorization Digest conforme a DeviceAuthHeaderInterceptor dell'APK."""
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

    def _execute_cgi_on_ip(self, ip, command_name, content_xml=""):
        """Execute a local CGI command against a specific IP."""
        if not ip:
            raise ValueError("IP address required.")
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
        if ip.startswith("http://") or ip.startswith("https://"):
            urls_to_try.append(f"{ip.rstrip('/')}/tdkcgi")
        else:
            urls_to_try.append(f"https://{ip}/tdkcgi")
            urls_to_try.append(f"http://{ip}/tdkcgi")

        headers = {
            "Content-Type": "application/xml; charset=UTF-8",
            "User-Agent": "okhttp/3.12.1"
        }

        last_error = None
        for url in urls_to_try:
            req = urllib.request.Request(url, data=xml_body.encode('utf-8'), headers=headers)
            ctx = self.local_ssl_ctx if url.startswith("https") else None
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
            raise last_error

    def discover_intercom_ip(self):
        """Rate-limited rediscovery of intercom IP if changed by router DHCP."""
        if not self.device_ip:
            return None

        now = time.time()
        with self._discovery_lock:
            if now - self._last_discovery_time < self._discovery_backoff:
                _LOGGER.debug(
                    "Skipping intercom IP rediscovery: throttled (backoff %ds remaining)",
                    int(self._discovery_backoff - (now - self._last_discovery_time)),
                )
                return None
            self._last_discovery_time = now

        if "." not in self.device_ip:
            return None

        parts = self.device_ip.split(".")
        if len(parts) != 4:
            return None

        subnet_base = ".".join(parts[:3])
        candidate_ips = [f"{subnet_base}.{i}" for i in range(1, 255) if f"{subnet_base}.{i}" != self.device_ip]

        def _probe_candidate(ip):
            # 1. Quick TCP pre-check on port 443
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.25)
            try:
                if sock.connect_ex((ip, 443)) != 0:
                    return None
            except Exception:
                return None
            finally:
                sock.close()

            # 2. Check TLS certificate to verify it is a Qualvision device before sending requests
            try:
                tls_sock = self.local_ssl_ctx.wrap_socket(socket.socket())
                tls_sock.settimeout(1.0)
                tls_sock.connect((ip, 443))
                der = tls_sock.getpeercert(binary_form=True)
                tls_sock.close()
                if not der or (b"QUALVISION" not in der and b"QV" not in der):
                    return None
            except Exception:
                return None

            # 3. Verify device identity via get.device.status
            try:
                raw_xml = self._execute_cgi_on_ip(ip, "get.device.status")
                root = ET.fromstring(raw_xml)
                err_text = root.findtext(".//error", "-1")
                if err_text != "0":
                    return None

                mac_text = root.findtext(".//info/mac", "").strip().lower().replace(":", "")
                expected_mac = (self.device_mac or "").strip().lower().replace(":", "")
                if expected_mac and mac_text:
                    if mac_text == expected_mac:
                        return ip
                    return None

                # Fallback if MAC was not configured yet: match model and learn MAC
                model_text = root.findtext(".//info/model", "").strip()
                expected_model = self.device_info.get("model", "IDS9457AW")
                if model_text and model_text == expected_model:
                    if root.findtext(".//info/mac"):
                        self.device_mac = root.findtext(".//info/mac").strip().lower()
                    return ip
            except Exception:
                return None

            return None

        found_ip = None
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(_probe_candidate, ip): ip for ip in candidate_ips}
            for future in as_completed(futures):
                res = future.result()
                if res:
                    found_ip = res
                    for f in futures:
                        f.cancel()
                    break

        if found_ip:
            self._discovery_backoff = 180.0
            _LOGGER.info("Vimar Intercom rediscovered at IP: %s (previously %s)", found_ip, self.device_ip)
            self.device_ip = found_ip
            return found_ip
        else:
            self._discovery_backoff = min(self._discovery_backoff * 2, 900.0)
            _LOGGER.debug(
                "Intercom IP rediscovery finished: no matching device found on %s.0/24 (next attempt in %ds)",
                subnet_base,
                int(self._discovery_backoff),
            )
            return None

    def local_cgi_command(self, command_name, content_xml="", is_retry=False):
        """Execute a local CGI command directly on LAN with Digest Auth support."""
        if not self.device_ip:
            raise ValueError("Device IP not configured for local LAN communication.")

        try:
            return self._execute_cgi_on_ip(self.device_ip, command_name, content_xml)
        except Exception as err:
            if not is_retry and self.device_ip:
                new_ip = self.discover_intercom_ip()
                if new_ip and new_ip != self.device_ip:
                    self.device_ip = new_ip
                    return self.local_cgi_command(command_name, content_xml=content_xml, is_retry=True)
            raise err

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

            if status.get("info_mac"):
                self.device_mac = status["info_mac"].strip().lower()
                if self.device_info:
                    self.device_info["mac"] = self.device_mac

            return status
        except Exception as err:
            _LOGGER.warning("Error fetching Vimar status: %s", err)
            return {}

    def _stream_unlock(self, locknumber=2, channel=1, is_retry=False):
        """Esegue lo sblocco fisico del relè tramite flusso multimediale UMSP port 34567."""
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
            _LOGGER.warning("Error reading streamkey on %s: %s", self.device_ip, e)
            if not is_retry and self.device_ip:
                new_ip = self.discover_intercom_ip()
                if new_ip and new_ip != self.device_ip:
                    self.device_ip = new_ip
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
            _LOGGER.warning("UMSP stream unlock error on %s: %s", self.device_ip, err)
            if not is_retry and self.device_ip:
                new_ip = self.discover_intercom_ip()
                if new_ip and new_ip != self.device_ip:
                    self.device_ip = new_ip
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
