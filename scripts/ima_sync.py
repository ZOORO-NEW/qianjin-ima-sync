#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qianjin-ima-sync · 真实可运行的 IMA 备份脚本
底层接口：腾讯官方 IMA OpenAPI (https://ima.qq.com)
依赖：pip install requests cos-python-sdk-v5
"""
import argparse
import hashlib
import json
import mimetypes
import os
import re
import sys
import time

try:
    import requests
except ImportError:
    sys.exit("缺少 requests，请运行: pip install requests")

# 兼容 Windows GBK 控制台：强制 stdout/stderr 使用 utf-8，避免打印 emoji 时 UnicodeEncodeError 崩溃
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

IMA_BASE = "https://ima.qq.com"

# 文件扩展名 -> IMA media_type 枚举（pdf=1, ppt=4, xlsx=5, 图片=3, 未知=1）
MEDIA_TYPE_MAP = {
    "pdf": 1, "doc": 1, "docx": 1, "md": 1, "txt": 1, "html": 1, "htm": 1,
    "xls": 5, "xlsx": 5,
    "ppt": 4, "pptx": 4,
    "png": 3, "jpg": 3, "jpeg": 3, "gif": 3, "webp": 3,
}
SUPPORTED_EXTS = set(MEDIA_TYPE_MAP.keys()) | {"bmp", "tiff"}
UNSUPPORTED_HINT = {
    "mp4": "视频文件不支持，请用 IMA 桌面客户端",
    "mov": "视频文件不支持，请用 IMA 桌面客户端",
    "mp3": "音频文件不支持，请用 IMA 桌面客户端",
    # 2026-07-31 实测：IMA OpenAPI 对 .svg 返回 220001 invalid media_type（矢量图不受支持）
    # 需要入库请先转成 png/jpg 再同步
    "svg": "SVG 矢量图不受 IMA 支持（API 报 220001），请先转 png/jpg 再同步",
}


# ───────────────────────── 凭据 & 基础请求 ─────────────────────────
def _read_secret(path):
    p = os.path.expanduser(path)
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            return f.read().strip()
    return None


def load_credentials():
    cid = os.environ.get("IMA_OPENAPI_CLIENTID") or _read_secret("~/.config/ima/client_id")
    key = os.environ.get("IMA_OPENAPI_APIKEY") or _read_secret("~/.config/ima/api_key")
    return cid, key


# 鉴权失败全局标志：一旦置位，auto-backup 立即终止，避免几十个文件排队重试
AUTH_FAILED = {"flag": False}

AUTH_HINT = """❌ IMA 凭证鉴权失败（skill auth failed / code 200002）
这不是网络问题，也不是脚本 bug。原因是 API Key 已过期或被撤销 —— IMA Skills API Key 有效期约 1 个月。
修复三步：
  1) 打开 https://ima.qq.com/agent-interface 登录
  2) 重新生成 API Key（只显示一次，立即复制）；若整套凭证重生成，client_id 也要一起换
  3) 覆盖写入 ~/.config/ima/api_key（及 ~/.config/ima/client_id），可用环境变量 IMA_OPENAPI_CLIENTID / IMA_OPENAPI_APIKEY 覆盖
补传：凭证更新后重跑 auto-backup，脚本按 state.json 指纹增量补传全部积压文件，无需手动重来。"""


def _auth_fail(resp=None, data=None):
    AUTH_FAILED["flag"] = True
    extra = ""
    if resp is not None:
        extra = f"\n  HTTP {resp.status_code}"
    if data:
        extra += f" | code={data.get('code')} msg={data.get('msg')}"
    sys.exit(AUTH_HINT + extra)


def ima_api(path, body, timeout=30):
    """统一的 IMA OpenAPI POST 调用，返回 data 字典。"""
    cid, key = load_credentials()
    if not cid or not key:
        sys.exit("⚠️ 缺少 IMA 凭证，请配置 IMA_OPENAPI_CLIENTID/KEY 或 ~/.config/ima/client_id|api_key")
    headers = {
        "ima-openapi-clientid": cid,
        "ima-openapi-apikey": key,
        "Content-Type": "application/json",
    }
    try:
        r = requests.post(f"{IMA_BASE}/{path}", headers=headers, json=body, timeout=timeout)
    except requests.RequestException as e:
        sys.exit(f"❌ 网络/请求失败: {e}")
    # 鉴权失败优先识别：HTTP 401/403 或业务码 200002，不要误报成网络问题
    if r.status_code in (401, 403):
        _auth_fail(r)
    try:
        data = r.json()
    except ValueError:
        sys.exit(f"❌ 响应非 JSON: {r.text[:200]}")
    code = data.get("code", 0)
    if code == 200002 or "auth failed" in str(data.get("msg", "")).lower():
        _auth_fail(r, data)
    if code != 0:
        sys.exit(f"❌ API 错误 {code}: {data.get('msg')}")
    return data.get("data", {})


# ───────────────────────── COS 上传 ─────────────────────────
def cos_upload(file_path, cos_cred, content_type):
    try:
        from qcloud_cos import CosConfig, CosS3Client
    except ImportError:
        sys.exit("❌ COS 上传需 cos-python-sdk-v5，请运行: pip install cos-python-sdk-v5")
    cfg = CosConfig(
        SecretId=cos_cred["secret_id"],
        SecretKey=cos_cred["secret_key"],
        Token=cos_cred.get("token"),
        Region=cos_cred["region"],
    )
    client = CosS3Client(cfg)
    client.upload_file(
        Bucket=cos_cred["bucket_name"],
        Key=cos_cred["cos_key"],
        LocalFilePath=file_path,
        EnableMD5=True,
    )


# ───────────────────────── 核心：单文件上传 ─────────────────────────
def upload_file(file_path, kb_id, verbose=True):
    if not os.path.isfile(file_path):
        raise FileNotFoundError(file_path)
    ext = file_path.rsplit(".", 1)[-1].lower() if "." in os.path.basename(file_path) else ""
    if ext in UNSUPPORTED_HINT:
        sys.exit(f"❌ {UNSUPPORTED_HINT[ext]}: {file_path}")
    if ext not in SUPPORTED_EXTS:
        print(f"⚠️ 未知扩展名 {ext}，尝试以通用文件上传: {file_path}")
    content_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
    media_type = MEDIA_TYPE_MAP.get(ext, 1)
    size = os.path.getsize(file_path)

    if verbose:
        print(f"  Step1 预检: {ext or '无扩展名'} -> media_type={media_type} ✅")

    cm = ima_api("openapi/wiki/v1/create_media", {
        "file_name": os.path.basename(file_path),
        "file_size": size,
        "content_type": content_type,
        "knowledge_base_id": kb_id,
        "file_ext": ext,
    })
    media_id = cm["media_id"]
    cos_cred = cm["cos_credential"]
    if verbose:
        print(f"  Step2 建媒体: media_id={media_id} ✅")

    cos_upload(file_path, cos_cred, content_type)
    if verbose:
        print(f"  Step3 COS上传: {size}B ✅")

    ak = ima_api("openapi/wiki/v1/add_knowledge", {
        "media_type": media_type,
        "media_id": media_id,
        "title": os.path.basename(file_path),
        "knowledge_base_id": kb_id,
        "file_info": {
            "cos_key": cos_cred["cos_key"],
            "file_size": size,
            "file_name": os.path.basename(file_path),
        },
    })
    if verbose:
        print(f"  Step4 关联知识库 ✅")
    return ak


# ───────────────────────── 批量目录上传 ─────────────────────────
def upload_dir(directory, kb_id, recursive=True, file_types=None, confirm=True):
    files = []
    for root, _, names in os.walk(directory):
        if not recursive and os.path.relpath(root, directory):
            continue
        for n in names:
            p = os.path.join(root, n)
            ext = n.rsplit(".", 1)[-1].lower() if "." in n else ""
            if file_types and ext not in file_types:
                continue
            if ext in SUPPORTED_EXTS:
                files.append(p)
    if not files:
        print("📭 没有符合条件的文件")
        return
    total = sum(os.path.getsize(f) for f in files)
    print(f"📊 准备上传 {len(files)} 个文件，总大小 {total/1024:.1f}KB")
    print(f"⏱️ 预计耗时 {len(files)*3}-{len(files)*12} 秒")
    if confirm and input("是否继续？[y/N] ") not in ("y", "Y"):
        return
    ok, fail = [], []
    for i, f in enumerate(files, 1):
        print(f"\n[{i}/{len(files)}] {os.path.basename(f)}")
        for attempt in range(3):
            try:
                upload_file(f, kb_id, verbose=False)
                ok.append(f)
                print("  ✅ 成功")
                break
            except SystemExit as e:
                if attempt < 2:
                    time.sleep([2, 5, 10][attempt])
                    print(f"  🔁 重试 {attempt+1}...")
                else:
                    fail.append((f, str(e)))
                    print(f"  ❌ 失败: {e}")
        time.sleep(1.5)  # IMA 限频保护
    print(f"\n✅ 批量完成：成功 {len(ok)}，失败 {len(fail)}")
    for f, e in fail:
        print(f"   ❌ {f}: {e}")


# ───────────────────────── 自动增量备份 ─────────────────────────
def _fingerprint(path):
    st = os.stat(path)
    return f"{st.st_mtime:.0f}:{st.st_size}"


# 中间产物排除规则：_workdir / audio / video 子目录，以及视频帧 (frame_*.png 等)
_FRAME_RE = re.compile(r"(?i)^frame_.*\.(png|jpe?g|gif|webp|svg|bmp|tiff)$")
def _is_excluded(path):
    rp = path.replace("\\", "/").lower()
    if "_workdir" in rp:
        return True
    if re.search(r"/(audio|video)/", rp):
        return True
    if _FRAME_RE.match(os.path.basename(path)):
        return True
    return False


def _load_state(state_file):
    state_file = os.path.expanduser(state_file)
    if os.path.exists(state_file):
        with open(state_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_state(state_file, state):
    state_file = os.path.expanduser(state_file)
    os.makedirs(os.path.dirname(state_file) or ".", exist_ok=True)
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _load_routes():
    rp = os.path.expanduser("~/.config/ima-sync/routes.json")
    if os.path.exists(rp):
        with open(rp, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"rules": [], "default": None}


def _route(file_path, routes):
    fp = file_path.replace("\\", "/")
    for rule in routes.get("rules", []):
        m = rule.get("match", {})
        pfx = (m.get("path_prefix") or "").replace("\\", "/")
        if pfx and fp.startswith(pfx):
            return rule["target"]
        if m.get("file_type") and fp.lower().endswith("." + m["file_type"]):
            return rule["target"]
    return routes.get("default")


def auto_backup(watch, state_file="~/.config/ima-sync/state.json", recursive=True):
    watch = os.path.expanduser(watch)
    state = _load_state(state_file)
    routes = _load_routes()
    files = []
    for root, _, names in os.walk(watch):
        if not recursive and os.path.relpath(root, watch):
            continue
        for n in names:
            p = os.path.join(root, n)
            ext = n.rsplit(".", 1)[-1].lower() if "." in n else ""
            if ext in SUPPORTED_EXTS and not _is_excluded(p):
                files.append(p)
    new = [f for f in files if state.get(os.path.relpath(f, watch)) != _fingerprint(f)]
    if not new:
        print("✅ 无新增/修改文件，无需备份")
        return
    print(f"🔍 发现 {len(new)} 个新增/修改文件")
    ok, fail = [], []
    for f in new:
        rel = os.path.relpath(f, watch)
        tgt = _route(f, routes)
        if not tgt:
            print(f"⚠️ 跳过（无路由且无默认库）: {rel}")
            continue
        kb_id = tgt.get("knowledge_base_id")
        print(f"📤 {rel} -> {tgt}")
        try:
            if tgt.get("type") == "note":
                _file_to_note(f, tgt.get("folder"))
                ok.append(f)
            else:
                upload_file(f, kb_id, verbose=False)
                ok.append(f)
            state[rel] = _fingerprint(f)
        except SystemExit as e:
            fail.append((rel, str(e)))
            print(f"  ❌ {e}")
            if AUTH_FAILED["flag"]:
                print("\n⛔ 凭证失效，终止本轮备份。剩余文件未处理，修复凭证后重跑即可自动补传。")
                break
        time.sleep(1.5)
    _save_state(state_file, state)
    print(f"\n✅ 自动备份完成：成功 {len(ok)}，失败 {len(fail)}")


# ───────────────────────── 笔记 ─────────────────────────
def _read_utf8(path):
    """读取文件并确保 UTF-8（非法字节清洗），避免 ima 乱码。"""
    raw = open(os.path.expanduser(path), "rb").read()
    for enc in ("utf-8", "gbk", "gb2312", "big5", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def note_new(title, content, content_file=None, folder=None):
    if content_file:
        content = _read_utf8(content_file)
    body = {"content_format": 1, "content": content}
    if title:
        # import_doc 无 title 字段，标题写进正文首行
        body["content"] = f"# {title}\n\n{content}"
    if folder:
        body["folder_id"] = folder
    res = ima_api("openapi/note/v1/import_doc", body)
    print(f"✅ 笔记已创建: doc_id={res.get('doc_id')}")


def note_append(doc_id, content):
    ima_api("openapi/note/v1/append_doc", {"doc_id": doc_id, "content_format": 1, "content": content})
    print(f"✅ 已追加到笔记 {doc_id}")


def _file_to_note(file_path, folder=None):
    content = _read_utf8(file_path)
    title = os.path.splitext(os.path.basename(file_path))[0]
    note_new(title, content, folder=folder)


# ───────────────────────── 网页 & 检索 ─────────────────────────
def save_url(url, kb_id):
    if "bilibili.com" in url or "youtube.com" in url:
        sys.exit("❌ 视频链接不支持，请用 IMA 桌面客户端")
    ima_api("openapi/wiki/v1/import_urls", {"knowledge_base_id": kb_id, "urls": [url]})
    print(f"✅ 网页已收藏: {url}")


def search_kb(query, kb_id=None):
    body = {"query": query, "cursor": ""}
    if kb_id:
        body["knowledge_base_id"] = kb_id
    res = ima_api("openapi/wiki/v1/search_knowledge", body)
    items = res.get("info_list", res.get("items", res.get("list", res.get("search_results", []))))
    print(f"🔍 知识库搜索「{query}」命中 {len(items)} 条:")
    for it in items:
        print(f"  - {it.get('title', it.get('name'))} ({it.get('doc_id', it.get('entry_id', it.get('id', '')))}")


def list_kb():
    res = ima_api("openapi/wiki/v1/get_addable_knowledge_base_list", {"cursor": "", "limit": 50})
    items = res.get("addable_knowledge_base_list", res.get("knowledge_base_list", res.get("list", [])))
    print(f"📚 可添加知识库 {len(items)} 个:")
    for it in items:
        print(f"  - {it.get('name')}  [{it.get('id', it.get('knowledge_base_id'))}]")


def check():
    cid, key = load_credentials()
    if not cid or not key:
        sys.exit("⚠️ 未配置凭证")
    # 用一个只读接口验证
    list_kb()
    print("✅ 凭证有效")


# ───────────────────────── CLI ─────────────────────────
def main():
    ap = argparse.ArgumentParser(description="qianjin-ima-sync · IMA 备份工具")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", help="检查凭证")

    p1 = sub.add_parser("upload-file", help="上传单文件")
    p1.add_argument("file"); p1.add_argument("--kb", required=True)

    p2 = sub.add_parser("upload-dir", help="批量上传目录")
    p2.add_argument("directory"); p2.add_argument("--kb", required=True)
    p2.add_argument("--no-recursive", action="store_true")
    p2.add_argument("--types", nargs="*", default=None)
    p2.add_argument("--yes", action="store_true", help="跳过确认")

    p3 = sub.add_parser("auto-backup", help="自动增量备份")
    p3.add_argument("--watch", default="E:/workbuddy/outputs")
    p3.add_argument("--state", default="~/.config/ima-sync/state.json")

    p4 = sub.add_parser("note-new", help="文本转笔记")
    p4.add_argument("--title", default=None)
    p4.add_argument("--content", default=None)
    p4.add_argument("--content-file", default=None)
    p4.add_argument("--folder", default=None)

    p5 = sub.add_parser("note-append", help="追加到笔记")
    p5.add_argument("--doc-id", required=True); p5.add_argument("--content", required=True)

    p6 = sub.add_parser("save-url", help="网页收藏")
    p6.add_argument("url"); p6.add_argument("--kb", required=True)

    p7 = sub.add_parser("search-kb", help="搜索知识库")
    p7.add_argument("query"); p7.add_argument("--kb", default=None)

    sub.add_parser("list-kb", help="列出可添加知识库")

    args = ap.parse_args()
    if args.cmd == "check":
        check()
    elif args.cmd == "upload-file":
        upload_file(os.path.expanduser(args.file), args.kb)
    elif args.cmd == "upload-dir":
        upload_dir(os.path.expanduser(args.directory), args.kb,
                   recursive=not args.no_recursive, file_types=args.types, confirm=not args.yes)
    elif args.cmd == "auto-backup":
        auto_backup(args.watch, args.state)
    elif args.cmd == "note-new":
        note_new(args.title, args.content, args.content_file, args.folder)
    elif args.cmd == "note-append":
        note_append(args.doc_id, args.content)
    elif args.cmd == "save-url":
        save_url(args.url, args.kb)
    elif args.cmd == "search-kb":
        search_kb(args.query, args.kb)
    elif args.cmd == "list-kb":
        list_kb()


if __name__ == "__main__":
    main()
