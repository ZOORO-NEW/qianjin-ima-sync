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
import sys
import time

try:
    import requests
except ImportError:
    sys.exit("缺少 requests，请运行: pip install requests")

IMA_BASE = "https://ima.qq.com"

# 文件扩展名 -> IMA media_type 枚举（pdf=1, ppt=4, xlsx=5, 图片=3, 未知=1）
MEDIA_TYPE_MAP = {
    "pdf": 1, "doc": 1, "docx": 1, "md": 1, "txt": 1, "html": 1, "htm": 1,
    "xls": 5, "xlsx": 5,
    "ppt": 4, "pptx": 4,
    "png": 3, "jpg": 3, "jpeg": 3, "gif": 3, "webp": 3, "svg": 3,
}
SUPPORTED_EXTS = set(MEDIA_TYPE_MAP.keys()) | {"bmp", "tiff"}
UNSUPPORTED_HINT = {
    "mp4": "视频文件不支持，请用 IMA 桌面客户端",
    "mov": "视频文件不支持，请用 IMA 桌面客户端",
    "mp3": "音频文件不支持，请用 IMA 桌面客户端",
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
        r.raise_for_status()
    except requests.RequestException as e:
        sys.exit(f"❌ 网络/请求失败: {e}")
    try:
        data = r.json()
    except ValueError:
        sys.exit(f"❌ 响应非 JSON: {r.text[:200]}")
    if data.get("retcode", 0) != 0:
        sys.exit(f"❌ API 错误 {data.get('retcode')}: {data.get('errmsg')}")
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
    for rule in routes.get("rules", []):
        m = rule.get("match", {})
        if m.get("path_prefix") and file_path.startswith(m["path_prefix"]):
            return rule["target"]
        if m.get("file_type") and file_path.lower().endswith("." + m["file_type"]):
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
            if ext in SUPPORTED_EXTS:
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
