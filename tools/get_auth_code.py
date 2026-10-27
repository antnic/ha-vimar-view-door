#!/usr/bin/env python3
"""
Utility script to retrieve the Auth Code (Device Token) for Vimar VIEW Door video intercoms.
This tool performs a secure login to your MyVIMAR account and queries the QVCloud service
to obtain the local authentication token needed for 100% offline Home Assistant operation.
"""

import sys
import getpass
import json
import base64
import urllib.request
import urllib.parse
import re
import time
import ssl
import xml.etree.ElementTree as ET

def get_devices(email, password):
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    client_id = "003-2078-a989bc1285e51ad8"
    oem_id = "G0078"
    app_id = "2078"
    region_id = 1
    host = "r1-2-sec.qvcloud.net"

    print(f"[*] Connecting to MyVIMAR OAuth for account: {email}...")

    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(),
        urllib.request.HTTPSHandler(context=ssl_ctx)
    )

    state_obj = {"mode": "usrpwd", "oem": oem_id, "client_id": client_id, "rgn": region_id}
    state_str = base64.b64encode(json.dumps(state_obj).encode()).decode()
    auth_url = f"https://oauth.vimar.com/it/it/oauth/authorization-code/authorize?scope=openid+email&response_type=code&access_type=offline&client_id=qualvision&redirect_uri=https://sso.qvcloud.net/vimar/callback&state={urllib.parse.quote(state_str)}"

    req1 = urllib.request.Request(auth_url, headers={
        "User-Agent": "Mozilla/5.0 (Linux; Android 13; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/151.0.7922.199 Mobile Safari/537.36",
        "X-Requested-With": "com.vimar.viewdoor"
    })

    try:
        resp1 = opener.open(req1)
        html1 = resp1.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"[-] Error connecting to oauth.vimar.com: {e}")
        return []

    match = re.search(r'<input[^>]*value="([^"]+)"[^>]*name="hash"', html1) or re.search(r'<input[^>]*name="hash"[^>]*value="([^"]+)"', html1)
    csrf_hash = match.group(1) if match else ""

    boundary = "----WebKitFormBoundary" + hex(int(time.time() * 1000))[2:]
    body_data = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="hash"\r\n\r\n{csrf_hash}\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="email"\r\n\r\n{email.strip()}\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="passw"\r\n\r\n{password.strip()}\r\n'
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

    try:
        resp2 = opener.open(req2)
        raw_sso = resp2.read().decode('utf-8')
        sso_data = json.loads(raw_sso)
    except json.JSONDecodeError:
        print("[-] Login failed! Please verify your email and password.")
        return []
    except Exception as e:
        print(f"[-] Authentication error: {e}")
        return []

    if sso_data.get("result") != 0:
        print(f"[-] Vimar SSO returned error: {sso_data}")
        return []

    qv_account = sso_data["account"]
    qv_password = sso_data["password"]
    region_id = sso_data.get("rgn", 1)
    print(f"[+] MyVIMAR Authentication successful! (Account: {qv_account})")

    # Cloud Duplex Handshake
    print(f"[*] Establishing duplex data channel with cloud ({host})...")
    down_url = f"https://{host}/auth/user;jus_duplex=down"
    req_down = urllib.request.Request(down_url, headers={
        "User-Agent": "okhttp/3.12.1",
        "Accept-Language": "en-US"
    })
    
    jsessionid = None
    with urllib.request.urlopen(req_down, context=ssl_ctx, timeout=10) as resp:
        set_cookie = resp.headers.get("Set-Cookie", "")
        for part in set_cookie.split(";"):
            if "jsessionid=" in part:
                jsessionid = part.strip().split("=")[1]
                break

    if not jsessionid:
        print("[-] Failed to establish cloud duplex session.")
        return []

    login_xml = f"""<?xml version="1.0" encoding="UTF-8"?><envelope>
   <content class="com.quvii.qvweb.userauth.bean.request.LoginReqContent">
      <account>{qv_account}</account>
      <auth-code></auth-code>
      <ip-region-id>{region_id}</ip-region-id>
      <password>{qv_password}</password>
      <auth-type>0</auth-type>
   </content>
   <header>
      <client>
         <app>{app_id}</app>
         <id>{client_id}</id>
         <oem>{oem_id}</oem>
         <type>3</type>
      </client>
      <command>login</command>
      <flag>tdkcloud</flag>
      <seq>1</seq>
      <user-data></user-data>
      <version>v1.13</version>
   </header>
</envelope>"""

    up_url = f"https://{host}/auth/user;jus_duplex=up"
    req_up = urllib.request.Request(up_url, data=login_xml.encode('utf-8'), headers={
        "Content-Type": "application/xml",
        "Cookie": f"jsessionid={jsessionid}",
        "User-Agent": "okhttp/3.12.1"
    })
    with urllib.request.urlopen(req_up, context=ssl_ctx, timeout=10):
        pass

    down_poll = urllib.request.Request(down_url, headers={
        "Cookie": f"jsessionid={jsessionid}",
        "User-Agent": "okhttp/3.12.1"
    })
    with urllib.request.urlopen(down_poll, context=ssl_ctx, timeout=10) as resp:
        login_resp_xml = resp.read().decode('utf-8')
        root = ET.fromstring(login_resp_xml)
        session_elem = root.find(".//session/id")
        session_id = session_elem.text if session_elem is not None else None

    if not session_id:
        print("[-] Received invalid login response from cloud.")
        return []

    # Get Device List
    print("[*] Retrieving registered video intercoms...")
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
         <app>{app_id}</app>
         <id>{client_id}</id>
         <oem>{oem_id}</oem>
         <type>3</type>
      </client>
      <command>get-device-list</command>
      <flag>tdkcloud</flag>
      <seq>2</seq>
      <session>{session_id}</session>
      <user-data></user-data>
      <version>v1.13</version>
   </header>
</envelope>"""

    req_up2 = urllib.request.Request(up_url, data=dev_list_xml.encode('utf-8'), headers={
        "Content-Type": "application/xml",
        "Cookie": f"jsessionid={jsessionid}",
        "User-Agent": "okhttp/3.12.1"
    })
    with urllib.request.urlopen(req_up2, context=ssl_ctx, timeout=10):
        pass

    devices = []
    with urllib.request.urlopen(down_poll, context=ssl_ctx, timeout=10) as resp:
        xml_data = resp.read().decode('utf-8')
        root = ET.fromstring(xml_data)
        for dev in root.findall(".//device"):
            dev_id = dev.findtext("id", default="N/A")
            name = dev.findtext("name", default="Vimar Intercom")
            model = dev.findtext("model", default="VIEW Door")
            auth_code = dev.findtext("out-auth-code", default="")
            devices.append({
                "id": dev_id,
                "name": name,
                "model": model,
                "auth_code": auth_code
            })

    return devices

def main():
    print("=" * 65)
    print("   Vimar VIEW Door - Device Auth Code (Token) Retrieval Tool")
    print("=" * 65)

    if len(sys.argv) >= 3:
        email = sys.argv[1]
        password = sys.argv[2]
    else:
        email = input("Enter your MyVIMAR email: ").strip()
        password = getpass.getpass("Enter your MyVIMAR password: ").strip()

    if not email or not password:
        print("[-] Both email and password are required.")
        sys.exit(1)

    devices = get_devices(email, password)

    if not devices:
        print("\n[-] No devices found or an error occurred during authentication.")
        sys.exit(1)

    print("\n" + "=" * 65)
    print(f"🎉 FOUND {len(devices)} DEVICE(S):")
    print("=" * 65)

    for i, dev in enumerate(devices, 1):
        print(f"\nDevice #{i}:")
        print(f"  • Name:      {dev['name']}")
        print(f"  • Model:     {dev['model']}")
        print(f"  • Device ID: {dev['id']}")
        print(f"  • AUTH CODE: {dev['auth_code']}")
        print("\n  👉 For Home Assistant (100% Offline Local Mode):")
        print(f"     In the configuration form, leave email and password blank,")
        print(f"     enter the local IP of your intercom, and paste this Auth Code:")
        print(f"     {dev['auth_code']}")

    print("\n" + "=" * 65)

if __name__ == "__main__":
    main()
