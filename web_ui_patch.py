#!/usr/bin/env python3
"""Clean patch for web_ui.py — adds login tab + paste + file upload"""
from pathlib import Path

f = Path('/root/khdiamond/web_ui.py')
content = f.read_text()

# ── 1. Add login_khdiamond() after validate_cookies() ──────────────────────
OLD1 = '''def load_catalog(token: str):'''

NEW1 = '''def login_khdiamond(username: str, password: str, cookies_path: Path) -> tuple[bool, str]:
    """Login to khdiamond.net via AJAX and save session cookies."""
    import urllib.request, urllib.parse
    cookie_jar = MozillaCookieJar(str(cookies_path))
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    opener.addheaders = [
        ('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0'),
        ('Referer', 'https://khdiamond.net/my-account/'),
        ('Content-Type', 'application/x-www-form-urlencoded'),
    ]
    data = urllib.parse.urlencode({
        'action': 'dooplay_login',
        'log': username,
        'pwd': password,
        'rmb': 'forever',
        'red': 'https://khdiamond.net/my-account/',
    }).encode()
    try:
        resp = opener.open('https://khdiamond.net/wp-admin/admin-ajax.php', data, timeout=30)
        result = json.loads(resp.read().decode())
        if result.get('response'):
            cookie_jar.save(ignore_discard=True, ignore_expires=True)
            return True, "Login successful"
        return False, result.get('message', 'Login failed')
    except Exception as e:
        return False, str(e)


def load_catalog(token: str):'''

assert OLD1 in content, "PATCH 1 FAILED: load_catalog not found"
content = content.replace(OLD1, NEW1)
print("✓ Patch 1: login_khdiamond() added")

# ── 2. Replace UPLOAD_PAGE ──────────────────────────────────────────────────
# Find and replace the entire UPLOAD_PAGE block
up_start = content.index('UPLOAD_PAGE = page(')
up_end = content.index('\n""")\n', up_start) + 6

OLD2 = content[up_start:up_end]

NEW2 = '''UPLOAD_PAGE = page("KhDiamond Setup", """
  <h1>KhDiamond Addon</h1>
  <p>Provide your khdiamond.net credentials to get your personal Stremio addon.</p>

  <div class="tabs">
    <div class="tab active" onclick="switchTab(0)">🔑 Login</div>
    <div class="tab" onclick="switchTab(1)">📋 Paste Cookies</div>
    <div class="tab" onclick="switchTab(2)">📁 Upload File</div>
  </div>

  <div id="tab0">
    <form action="/khdiamond-ui/upload" method="post">
      <input type="hidden" name="method" value="login">
      <input type="text" name="username" placeholder="Email / Username / Phone" required
        style="width:100%;background:#111;border:1px solid #333;border-radius:8px;color:#eee;padding:12px;font-size:0.95rem;margin-bottom:12px;display:block">
      <input type="password" name="password" placeholder="Password" required
        style="width:100%;background:#111;border:1px solid #333;border-radius:8px;color:#eee;padding:12px;font-size:0.95rem;margin-bottom:12px;display:block">
      <button type="submit" class="btn">Login & Get Addon URL</button>
    </form>
  </div>

  <div id="tab1" style="display:none">
    <form action="/khdiamond-ui/upload" method="post">
      <input type="hidden" name="method" value="paste">
      <textarea name="cookies_text" placeholder="Paste your full cookies.txt content here..."></textarea>
      <button type="submit" class="btn">Get My Addon URL</button>
    </form>
  </div>

  <div id="tab2" style="display:none">
    <form action="/khdiamond-ui/upload" method="post" enctype="multipart/form-data">
      <input type="hidden" name="method" value="file">
      <div class="upload-area" onclick="document.getElementById('file').click()">
        <p style="margin:0">📁 Click to select <strong>cookies.txt</strong></p>
        <p style="margin:8px 0 0; font-size:0.8rem" id="fname">Netscape format</p>
      </div>
      <input type="file" id="file" name="cookies" accept=".txt" onchange="document.getElementById('fname').textContent=this.files[0]?.name||'No file chosen'">
      <button type="submit" class="btn">Get My Addon URL</button>
    </form>
  </div>

  <p style="margin-top:18px; font-size:0.8rem">
    Need help? Use the <a href="https://chrome.google.com/webstore/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc" target="_blank">Get cookies.txt LOCALLY</a> extension on khdiamond.net.
  </p>

  <script>
    function switchTab(n) {
      [0,1,2].forEach(i => document.getElementById('tab'+i).style.display = i===n ? 'block' : 'none');
      document.querySelectorAll('.tab').forEach((t, i) => t.classList.toggle('active', i === n));
    }
  </script>
""")'''

content = content[:up_start] + NEW2 + content[up_end:]
print("✓ Patch 2: UPLOAD_PAGE updated")

# ── 3. Replace upload() handler ─────────────────────────────────────────────
OLD3 = '''@app.post("/upload", response_class=HTMLResponse)
async def upload(cookies: UploadFile = File(...)):
    content = await cookies.read()

    # Generate token + save cookies
    token = str(uuid.uuid4())[:8]
    d = user_dir(token)
    d.mkdir(parents=True, exist_ok=True)
    cookies_path = d / "cookies.txt"
    cookies_path.write_bytes(content)

    # Validate cookies format
    if not validate_cookies(cookies_path):
        cookies_path.unlink(missing_ok=True)
        d.rmdir()
        return HTMLResponse(page("Error", """
          <h1>Invalid Cookies</h1>
          <p>The file doesn't appear to be a valid Netscape cookies file. Please export again from your browser.</p>
          <a href="/khdiamond-ui/"><button class="btn btn-secondary">Try Again</button></a>
        """))

    # Save metadata
    (d / "meta.json").write_text(json.dumps({
        "token": token,
        "created": datetime.now().isoformat(),
        "filename": cookies.filename,
    }))

    # Run pipeline in background
    threading.Thread(target=run_pipeline, args=(token,), daemon=True).start()

    return RedirectResponse(f"/khdiamond-ui/status/{token}", status_code=303)'''

NEW3 = '''@app.post("/upload", response_class=HTMLResponse)
async def upload(
    request: Request,
    cookies: UploadFile = File(None),
    cookies_text: str = Form(None),
    method: str = Form("login"),
    username: str = Form(None),
    password: str = Form(None),
):
    token = str(uuid.uuid4())[:8]
    d = user_dir(token)
    d.mkdir(parents=True, exist_ok=True)
    cookies_path = d / "cookies.txt"

    if method == "login":
        u = (username or "").strip()
        p = (password or "").strip()
        if not u or not p:
            d.rmdir()
            return HTMLResponse(page("Error", """
              <h1>Missing Credentials</h1>
              <p>Please enter your username and password.</p>
              <a href="/khdiamond-ui/"><button class="btn btn-secondary">Try Again</button></a>
            """))
        ok, msg = login_khdiamond(u, p, cookies_path)
        if not ok:
            cookies_path.unlink(missing_ok=True)
            d.rmdir()
            return HTMLResponse(page("Login Failed", f"""
              <h1>Login Failed</h1>
              <p>{msg}</p>
              <p>Please check your credentials and try again.</p>
              <a href="/khdiamond-ui/"><button class="btn btn-secondary">Try Again</button></a>
            """))
        source = "login"

    elif method == "paste":
        txt = (cookies_text or "").strip()
        if not txt:
            d.rmdir()
            return HTMLResponse(page("Error", """
              <h1>No Cookies Provided</h1>
              <p>Please paste your cookies content.</p>
              <a href="/khdiamond-ui/"><button class="btn btn-secondary">Try Again</button></a>
            """))
        cookies_path.write_bytes(txt.encode("utf-8"))
        if not validate_cookies(cookies_path):
            cookies_path.unlink(missing_ok=True)
            d.rmdir()
            return HTMLResponse(page("Error", """
              <h1>Invalid Cookies</h1>
              <p>The cookies don't appear to be valid Netscape format.</p>
              <a href="/khdiamond-ui/"><button class="btn btn-secondary">Try Again</button></a>
            """))
        source = "paste"

    elif method == "file":
        if not cookies or not cookies.filename:
            d.rmdir()
            return HTMLResponse(page("Error", """
              <h1>No File Selected</h1>
              <p>Please select a cookies.txt file.</p>
              <a href="/khdiamond-ui/"><button class="btn btn-secondary">Try Again</button></a>
            """))
        cookies_path.write_bytes(await cookies.read())
        if not validate_cookies(cookies_path):
            cookies_path.unlink(missing_ok=True)
            d.rmdir()
            return HTMLResponse(page("Error", """
              <h1>Invalid Cookies</h1>
              <p>The file doesn't appear to be a valid Netscape cookies file.</p>
              <a href="/khdiamond-ui/"><button class="btn btn-secondary">Try Again</button></a>
            """))
        source = "file"

    else:
        d.rmdir()
        return HTMLResponse(page("Error", """
          <h1>Invalid Request</h1>
          <a href="/khdiamond-ui/"><button class="btn btn-secondary">Try Again</button></a>
        """))

    (d / "meta.json").write_text(json.dumps({
        "token": token,
        "created": datetime.now().isoformat(),
        "source": source,
    }, indent=2))

    threading.Thread(target=run_pipeline, args=(token,), daemon=True).start()
    return RedirectResponse(f"/khdiamond-ui/status/{token}", status_code=303)'''

assert OLD3 in content, "PATCH 3 FAILED: upload() not found"
content = content.replace(OLD3, NEW3)
print("✓ Patch 3: upload() handler updated")

# ── 4. Replace refresh page ─────────────────────────────────────────────────
OLD4 = '''@app.get("/refresh/{token}", response_class=HTMLResponse)
async def refresh_page(token: str):
    if user_status(token) == "not_found":
        return RedirectResponse("/khdiamond-ui/")
    return HTMLResponse(page("Refresh", f"""
      <h1>Re-upload Cookies</h1>
      <p>Your cookies may have expired. Upload a fresh <strong>cookies.txt</strong> to refresh your catalog.</p>
      <form action="/khdiamond-ui/refresh/{token}" method="post" enctype="multipart/form-data">
        <div class="upload-area" onclick="document.getElementById('file2').click()">
          <p style="margin:0">📁 Click to select <strong>cookies.txt</strong></p>
        </div>
        <input type="file" id="file2" name="cookies" accept=".txt">
        <button type="submit" class="btn">Refresh My Catalog</button>
      </form>
    """))'''

NEW4 = '''@app.get("/refresh/{token}", response_class=HTMLResponse)
async def refresh_page(token: str):
    if user_status(token) == "not_found":
        return RedirectResponse("/khdiamond-ui/")
    return HTMLResponse(page("Refresh Cookies", f"""
      <h1>Refresh Cookies</h1>
      <p>Your cookies may have expired. Login again or provide fresh cookies.</p>

      <div class="tabs">
        <div class="tab active" onclick="switchTab(0)">🔑 Login</div>
        <div class="tab" onclick="switchTab(1)">📋 Paste Cookies</div>
        <div class="tab" onclick="switchTab(2)">📁 Upload File</div>
      </div>

      <div id="tab0">
        <form action="/khdiamond-ui/refresh/{token}" method="post">
          <input type="hidden" name="method" value="login">
          <input type="text" name="username" placeholder="Email / Username / Phone" required
            style="width:100%;background:#111;border:1px solid #333;border-radius:8px;color:#eee;padding:12px;font-size:0.95rem;margin-bottom:12px;display:block">
          <input type="password" name="password" placeholder="Password" required
            style="width:100%;background:#111;border:1px solid #333;border-radius:8px;color:#eee;padding:12px;font-size:0.95rem;margin-bottom:12px;display:block">
          <button type="submit" class="btn">Login & Refresh</button>
        </form>
      </div>

      <div id="tab1" style="display:none">
        <form action="/khdiamond-ui/refresh/{token}" method="post">
          <input type="hidden" name="method" value="paste">
          <textarea name="cookies_text" placeholder="Paste your full cookies.txt content here..."></textarea>
          <button type="submit" class="btn">Refresh My Catalog</button>
        </form>
      </div>

      <div id="tab2" style="display:none">
        <form action="/khdiamond-ui/refresh/{token}" method="post" enctype="multipart/form-data">
          <input type="hidden" name="method" value="file">
          <div class="upload-area" onclick="document.getElementById('file2').click()">
            <p style="margin:0">📁 Click to select <strong>cookies.txt</strong></p>
          </div>
          <input type="file" id="file2" name="cookies" accept=".txt">
          <button type="submit" class="btn">Refresh My Catalog</button>
        </form>
      </div>

      <script>
        function switchTab(n) {{
          [0,1,2].forEach(i => document.getElementById('tab'+i).style.display = i===n ? 'block' : 'none');
          document.querySelectorAll('.tab').forEach((t, i) => t.classList.toggle('active', i === n));
        }}
      </script>
    """))'''

assert OLD4 in content, "PATCH 4 FAILED: refresh_page() not found"
content = content.replace(OLD4, NEW4)
print("✓ Patch 4: refresh_page() updated")

# ── 5. Replace refresh_upload() handler ────────────────────────────────────
OLD5 = '''@app.post("/refresh/{token}", response_class=HTMLResponse)
async def refresh_upload(token: str, cookies: UploadFile = File(...)):
    if user_status(token) == "not_found":
        return RedirectResponse("/khdiamond-ui/")
    content = await cookies.read()
    d = user_dir(token)
    cookies_path = d / "cookies.txt"
    cookies_path.write_bytes(content)

    if not validate_cookies(cookies_path):
        return HTMLResponse(page("Error", f"""
          <h1>Invalid Cookies</h1>
          <p>Please export again from your browser.</p>
          <a href="/khdiamond-ui/refresh/{token}"><button class="btn btn-secondary">Try Again</button></a>
        """))

    # Clear old catalog + error, re-run pipeline
    (d / "catalog.json").unlink(missing_ok=True)
    (d / "error.txt").unlink(missing_ok=True)
    (d / "expired.txt").unlink(missing_ok=True)
    threading.Thread(target=run_pipeline, args=(token,), daemon=True).start()
    return RedirectResponse(f"/khdiamond-ui/status/{token}", status_code=303)'''

NEW5 = '''@app.post("/refresh/{token}", response_class=HTMLResponse)
async def refresh_upload(
    token: str,
    request: Request,
    cookies: UploadFile = File(None),
    cookies_text: str = Form(None),
    method: str = Form("login"),
    username: str = Form(None),
    password: str = Form(None),
):
    if user_status(token) == "not_found":
        return RedirectResponse("/khdiamond-ui/")

    d = user_dir(token)
    cookies_path = d / "cookies.txt"

    if method == "login":
        u = (username or "").strip()
        p = (password or "").strip()
        if not u or not p:
            return HTMLResponse(page("Error", f"""
              <h1>Missing Credentials</h1>
              <a href="/khdiamond-ui/refresh/{token}"><button class="btn btn-secondary">Try Again</button></a>
            """))
        ok, msg = login_khdiamond(u, p, cookies_path)
        if not ok:
            return HTMLResponse(page("Login Failed", f"""
              <h1>Login Failed</h1>
              <p>{msg}</p>
              <a href="/khdiamond-ui/refresh/{token}"><button class="btn btn-secondary">Try Again</button></a>
            """))

    elif method == "paste":
        txt = (cookies_text or "").strip()
        if not txt:
            return HTMLResponse(page("Error", "<h1>No Cookies Provided</h1>"))
        cookies_path.write_bytes(txt.encode("utf-8"))
        if not validate_cookies(cookies_path):
            return HTMLResponse(page("Error", f"""
              <h1>Invalid Cookies</h1>
              <a href="/khdiamond-ui/refresh/{token}"><button class="btn btn-secondary">Try Again</button></a>
            """))

    elif method == "file":
        if not cookies or not cookies.filename:
            return HTMLResponse(page("Error", "<h1>No File Selected</h1>"))
        cookies_path.write_bytes(await cookies.read())
        if not validate_cookies(cookies_path):
            return HTMLResponse(page("Error", f"""
              <h1>Invalid Cookies</h1>
              <a href="/khdiamond-ui/refresh/{token}"><button class="btn btn-secondary">Try Again</button></a>
            """))

    # Clear old data and re-run pipeline
    for fn in ["catalog.json", "error.txt", "expired.txt"]:
        (d / fn).unlink(missing_ok=True)
    threading.Thread(target=run_pipeline, args=(token,), daemon=True).start()
    return RedirectResponse(f"/khdiamond-ui/status/{token}", status_code=303)'''

assert OLD5 in content, "PATCH 5 FAILED: refresh_upload() not found"
content = content.replace(OLD5, NEW5)
print("✓ Patch 5: refresh_upload() updated")

# ── Write and verify ────────────────────────────────────────────────────────
f.write_text(content)
print(f"\n✅ All patches applied! Lines: {len(content.splitlines())}")
print("Run: systemctl restart khdiamond-ui")
