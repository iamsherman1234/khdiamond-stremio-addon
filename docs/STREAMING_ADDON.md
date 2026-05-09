# 💎 KhDiamond Streaming Addon

A personal Stremio streaming addon for your purchased movies and series from [khdiamond.net](https://khdiamond.net). Stream your Khmer-dubbed library directly in Stremio — on any device.

---

## 🎬 Background

### About KhDiamond

**KhDiaMonD** is the third website of the *អ្នកនាំរឿង* (Movie Dubber) family, following **KhFullHD** and **KhAnime**.

The mission is simple — share high-quality Khmer-dubbed movies with the community, not for profit. Every movie on the platform costs only **2,000 រៀល (~$0.50)** — barely the price of two bottles of water — just enough to cover the cost of dubbing, subtitling, and technical production.

> *"វាមិនមែនជាការទិញដូរដើម្បីផលចំណេញបុគ្គលទេ តែវាជាការ Share ចែករំលែកដើម្បីភាពរីករាយទៅវិញ"*
> — "It is not a commercial transaction for personal gain, but a sharing for the joy of all."

---

### Why I Built This

After buying a new **LG WebOS TV**, I discovered [khdiamond.net](https://khdiamond.net) and loved its quality Khmer-dubbed movie library. I created an account and started buying movies and series.

But watching through the **LG WebOS browser was painful**:
- Constant buffering and stops
- Browser crashes mid-movie
- TV slowing down significantly

I then found **Stremio** in the LG app store — smooth playback, beautiful UI, great addon ecosystem. But Stremio had no Khmer content at all.

So I built this addon to stream my purchased KhDiamond movies directly in Stremio, on my TV and any other device.

---

## ✨ What It Does

- 🎬 **Streams your purchased movies** directly from KhDiamond CDN
- 👤 **Personal library** — only shows movies you've bought
- 🔄 **Auto-sync** — nightly pipeline picks up new purchases automatically
- 📺 **Works on all Stremio devices** — TV, phone, desktop, web
- 🌐 **Redundant streams** — multiple quality/CDN/proxy combinations per movie
- 4️⃣ **4K support** — detects and serves 4K streams where available

---

## 🚀 Get Your Addon

### Step 1 — Export Your Cookies

Your khdiamond.net session cookies are needed to access your personal library.

1. Install the **[Get cookies.txt](https://chrome.google.com/webstore/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)** Chrome extension
2. Open Chrome and go to **[khdiamond.net](https://khdiamond.net)**
3. Make sure you are **logged in**
4. Click the extension icon → export cookies for this site
5. Save the file as `cookies.txt`

### Step 2 — Upload Your Cookies

Go to the addon setup page:

🔗 **`https://sudolocal.qzz.io/khdiamond-ui/`**

Upload your `cookies.txt` file and click **Get My Addon URL**.

### Step 3 — Wait for Your Catalog to Build

The system will:
1. Scrape your purchased movies from khdiamond.net
2. Resolve stream IDs for each title
3. Fetch metadata (poster, description, IMDB rating)
4. Build your personal `catalog.json`

This takes **3–5 minutes**. The page refreshes automatically.

### Step 4 — Install in Stremio

Once ready, you'll get a unique addon URL like:

```
https://sudolocal.qzz.io/khdiamond-ui/u/YOUR_TOKEN/manifest.json
```

Copy it and install in Stremio:
- **Stremio Web/Desktop:** Addons → Install from URL → paste URL
- **Stremio Mobile:** Settings → Addons → paste URL

**Bookmark your status page** — you'll need it to refresh cookies later:
```
https://sudolocal.qzz.io/khdiamond-ui/status/YOUR_TOKEN
```

---

## 🔄 Stream Options

Each movie provides up to **12 stream options**:

```
Quality  │ CDN  │ Proxy
─────────┼──────┼───────────────────────────
4K       │ CDN1 │ S10 (home server)
4K       │ CDN1 │ Cloud (Render.com)
4K       │ CDN2 │ S10
4K       │ CDN2 │ Cloud
1080p    │ CDN1 │ S10
1080p    │ CDN1 │ Cloud
1080p    │ CDN2 │ S10
1080p    │ CDN2 │ Cloud
720p     │ CDN1 │ S10
720p     │ CDN1 │ Cloud
720p     │ CDN2 │ S10
720p     │ CDN2 │ Cloud
```

4K streams only appear for movies that have 4K available on khdiamond.net.

---

## 🔁 Keeping Your Catalog Up to Date

### Auto-update (nightly)
Your catalog is automatically refreshed every night at 2 AM. New purchases will appear the next morning.

### Manual refresh
If you buy a new movie and want it immediately, go to your status page and click **Re-upload Cookies** (fresh cookies trigger a re-sync).

### Cookies expired?
Cookies expire periodically. When they do, your status page will show a warning. Simply:
1. Export fresh cookies from your browser
2. Go to your status page → **Re-upload Cookies**
3. Wait 3–5 minutes for the catalog to rebuild

---

## 📺 Best Experience

Install **both addons** together in Stremio:

| Addon | Purpose | URL |
|---|---|---|
| 🎬 Streaming (this addon) | Play your purchased movies | `https://sudolocal.qzz.io/khdiamond-ui/` |
| 📚 Catalog addon | Browse all 400+ KhDiamond titles | `https://khdiamond-catalog.chumlayan95.workers.dev/manifest.json` |

With both installed:
- Browse the full KhDiamond catalog in Stremio
- Click any movie you own → your streams appear automatically
- Click a movie you haven't bought → see info + buy link

---

## ❓ FAQ

**Q: Is my data safe?**
Your cookies are stored only on the server and used exclusively to access your khdiamond.net account. They are never shared.

**Q: What if I lose my addon URL?**
As long as you have your token (part of the URL), you can always access your status page at `https://sudolocal.qzz.io/khdiamond-ui/status/YOUR_TOKEN`.

**Q: Can I share my addon URL?**
Technically yes, but it will show your personal library and use your account cookies. Not recommended.

**Q: Why don't I see my newly purchased movie?**
It syncs automatically every night. For immediate access, re-upload your cookies from the status page.

**Q: The stream is buffering. What should I try?**
Try a different stream option — switch from S10 to Cloud proxy, or from CDN1 to CDN2. Lower quality (720p) also buffers less on slow connections.

---

## 🔗 Related

| Resource | Link |
|---|---|
| KhDiamond website | [khdiamond.net](https://khdiamond.net) |
| Catalog addon (browse all titles) | `https://khdiamond-catalog.chumlayan95.workers.dev/manifest.json` |
| Stremio | [stremio.com](https://stremio.com) |
| Get cookies.txt extension | [Chrome Web Store](https://chrome.google.com/webstore/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) |
