"""Download specified public Douyin video posts from the official embedded player."""
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ID = r"[0-9]{15,22}"
POST_HOSTS = {"douyin.com", "www.douyin.com", "m.douyin.com", "iesdouyin.com",
              "www.iesdouyin.com", "v.douyin.com"}
LINK = re.compile(r"https?://[^\s<>\"'，。；！？、【】（）]+", re.I)
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


class Failure(Exception):
    pass


def tokens(text):
    clean = html.unescape(text).replace(r"\:", ":").replace(r"\/", "/")
    for line in clean.splitlines():
        if re.fullmatch(ID, line.strip()):
            yield line.strip()
        else:
            for match in LINK.finditer(line):
                yield match.group().rstrip(".,;!?)]}…")


def safe_host(url):
    u = urlsplit(url)
    if u.scheme != "https" or u.username is not None or u.password is not None or u.port not in (None, 443):
        return ""
    return u.hostname or ""


def work_id(url):
    u = urlsplit(url)
    if safe_host(url) not in POST_HOSTS:
        return None
    m = re.fullmatch(r"/(?:share/)?video/(" + ID + r")/?", u.path)
    if m:
        return m.group(1)
    modal = parse_qs(u.query).get("modal_id", [""])[0]
    if u.hostname in {"douyin.com", "www.douyin.com"} and re.fullmatch(ID, modal):
        return modal
    return None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def resolve(token):
    if re.fullmatch(ID, token):
        return token
    url = re.sub(r"^http://", "https://", token, flags=re.I)
    opener = build_opener(NoRedirect())
    for _ in range(6):
        if safe_host(url) not in POST_HOSTS:
            raise Failure("需要抖音官方作品链接。")
        vid = work_id(url)
        if vid:
            return vid
        if safe_host(url) != "v.douyin.com" or not re.fullmatch(r"/[A-Za-z0-9_-]+/?", urlsplit(url).path):
            raise Failure("链接未指向单条视频作品。")
        try:
            with opener.open(Request(url, headers={"User-Agent": UA}), timeout=20):
                raise Failure("短链没有跳转到作品，可能已失效。")
        except HTTPError as exc:
            with exc:
                location = exc.headers.get("Location")
                if exc.code not in (301, 302, 303, 307, 308) or not location:
                    raise
                url = urljoin(url, location)
    raise Failure("短链跳转次数过多。")


def launch(stack):
    try:
        from playwright.sync_api import Error, sync_playwright
    except ImportError:
        raise Failure("当前 Python 缺少 playwright。") from None
    api = stack.enter_context(sync_playwright())
    for options in ({"channel": "chrome"}, {}):
        try:
            browser = api.chromium.launch(headless=True, **options)
        except Error:
            continue
        stack.callback(browser.close)
        return browser
    raise Failure("未能启动 Chrome 或 Playwright Chromium，请检查浏览器安装和运行权限。")


def media_host(url):
    host = safe_host(url)
    return any(host == root or host.endswith("." + root) for root in ("douyinvod.com", "douyin.com"))


class MediaRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not media_host(urljoin(req.full_url, newurl)):
            raise Failure("播放器媒体跳转到了未识别的域名。")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(browser, vid, path):
    from playwright.sync_api import Error
    iframe = "https://open.douyin.com/player/video?vid=" + vid
    page = browser.new_page()
    try:
        try:
            page.goto(iframe, wait_until="domcontentloaded", timeout=30000)
            source = page.wait_for_function("""() => {
                const video = document.querySelector('video');
                const src = video?.currentSrc || video?.src;
                return src?.startsWith('https://') ? src : false;
            }""", timeout=25000).json_value()
            ua = page.evaluate("navigator.userAgent")
        except Error:
            raise Failure("官方播放器未返回视频源；请检查作品是否仍可公开播放或稍后重试。") from None
        if not media_host(source):
            raise Failure("播放器提供的媒体地址不属于已支持的抖音域名。")
        req = Request(source, headers={"Referer": iframe, "User-Agent": ua, "Accept-Encoding": "identity"})
        with build_opener(MediaRedirect()).open(req, timeout=45) as response:
            if response.status not in (200, 206):
                raise Failure("媒体服务器未返回可下载的视频。")
            with path.open("xb") as output:
                shutil.copyfileobj(response, output, 256 * 1024)
            size = path.stat().st_size
            length = response.headers.get("Content-Length")
            if length and int(length) != size:
                raise Failure("传输中断，收到的文件长度与服务器声明不一致。")
            if response.status == 206 and response.headers.get("Content-Range") != f"bytes 0-{size-1}/{size}":
                raise Failure("服务器只返回了部分视频。")
    finally:
        page.close()


def inspect(path, require_audio):
    if path.is_symlink() or not path.is_file():
        raise Failure("目标路径不是常规视频文件。")
    with path.open("rb") as f:
        if f.read(12)[4:8] != b"ftyp":
            raise Failure("文件不是可识别的 MP4。")
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format",
                            "-of", "json", str(path)], capture_output=True, text=True)
    if probe.returncode:
        raise Failure("ffprobe 无法读取视频。")
    meta = json.loads(probe.stdout)
    streams = meta.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video" and
                  not s.get("disposition", {}).get("attached_pic") and s.get("width") and s.get("height")), None)
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    duration = float(meta.get("format", {}).get("duration", 0))
    if not video or not duration > 0:
        raise Failure("缺少有效画面或视频时长。")
    if require_audio and not audios:
        raise Failure("作品缺少所需音轨。")
    check = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", str(path),
                            "-map", f"0:{video['index']}", "-map", "0:a?", "-f", "null", "-"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if check.returncode:
        raise Failure("完整解码失败，文件可能不完整。")
    return {"seconds": round(duration, 3), "width": video["width"], "height": video["height"],
            "video_codec": video["codec_name"], "audio_codecs": [s["codec_name"] for s in audios],
            "bytes": path.stat().st_size}


def existing(path, require_audio):
    try:
        return {"status": "existing", "path": str(path), **inspect(path, require_audio)}
    except Failure as exc:
        raise Failure("已有同名文件，已保留。" + str(exc)) from None


def download(vid, args, get_browser):
    for binary in ("ffprobe", "ffmpeg"):
        if not shutil.which(binary):
            raise Failure("缺少媒体校验工具 " + binary)
    folder = args.output.expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / (vid + ".mp4")
    if os.path.lexists(dest):
        return existing(dest, args.require_audio)
    with tempfile.TemporaryDirectory(dir=folder, prefix=".douyin-") as tmp:
        part = Path(tmp) / "source.mp4"
        fetch(get_browser(), vid, part)
        details = inspect(part, args.require_audio)
        try:
            os.link(part, dest)
        except FileExistsError:
            return existing(dest, args.require_audio)
    return {"status": "saved", "path": str(dest), **details}


def error_text(exc):
    if isinstance(exc, Failure):
        return str(exc)
    if isinstance(exc, HTTPError):
        return f"服务器返回 HTTP {exc.code}。"
    if isinstance(exc, (URLError, HTTPException, TimeoutError)):
        return "网络连接或媒体传输失败，请重试。"
    if isinstance(exc, OSError):
        return exc.strerror or type(exc).__name__
    return "处理失败：" + type(exc).__name__
