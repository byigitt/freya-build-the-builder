"""Mirror a public Google Drive folder (recursively) into a local folder; prints files that are new or changed.

    python3 lab/drive_sync.py <folder_id> <dest>
"""
import html, pathlib, re, sys, urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"}


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read()


def listing(folder_id):
    page = get("https://drive.google.com/embeddedfolderview?id=" + folder_id).decode("utf-8", "replace")
    out = []
    for m in re.finditer(r'<a href="([^"]+)"[^>]*>.*?<div class="flip-entry-title">(.*?)</div>', page, re.S):
        href, name = html.unescape(m.group(1)), html.unescape(m.group(2)).strip()
        f = re.search(r"/folders/([\w-]+)", href)
        d = re.search(r"/file/d/([\w-]+)", href)
        if f:
            out.append(("dir", f.group(1), name))
        elif d:
            out.append(("file", d.group(1), name))
    return out


def download(file_id):
    data = get("https://drive.google.com/uc?export=download&id=" + file_id)
    if data[:200].lstrip().lower().startswith(b"<!doctype html") and b"confirm" in data:
        tok = re.search(rb'name="confirm" value="([^"]+)"', data)
        uuid = re.search(rb'name="uuid" value="([^"]+)"', data)
        url = "https://drive.usercontent.google.com/download?id=" + file_id + "&export=download"
        if tok:
            url += "&confirm=" + tok.group(1).decode()
        if uuid:
            url += "&uuid=" + uuid.group(1).decode()
        data = get(url)
    return data


def sync(folder_id, dest, changed):
    dest.mkdir(parents=True, exist_ok=True)
    for kind, fid, name in listing(folder_id):
        target = dest / name
        if kind == "dir":
            sync(fid, target, changed)
            continue
        data = download(fid)
        if not target.exists() or target.read_bytes() != data:
            target.write_bytes(data)
            changed.append(str(target))


if __name__ == "__main__":
    changed = []
    sync(sys.argv[1], pathlib.Path(sys.argv[2]), changed)
    print("\n".join("NEW/CHANGED " + c for c in changed) or "no changes")
