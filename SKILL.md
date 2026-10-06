---
slug: qianjin-ima-sync
displayName: IMA知识库同步
summary: "'WorkBuddy 生成成果自动备份到腾讯 ima 知识库（基于官方 IMA OpenAPI）。支持单文件上传、整目录批量备份、文本转笔记、网页/微信文章收藏、自动增量备份、知识库与笔记搜索。智能路由按路径/类型自动选择目标知识库。..."
name: qianjin-ima-sync
description: "WorkBuddy 生成成果自动备份到腾讯 ima 知识库（基于官方 IMA OpenAPI）。支持单文件上传、整目录批量备份、文本转笔记、网页/微信文章收藏、自动增量备份、知识库与笔记搜索。智能路由按路径/类型自动选择目标知识库。触发词：备份到ima、上传到ima、存到ima知识库、ima同步、ima备份、归档到ima、自动备份、保存到腾讯ima、搜ima知识库、搜ima笔记。"
version: 2.1.1
category: 效率工具
platforms: [workbuddy, claude-code, cursor, windsurf, codex, linux, macos, windows]
author: qianjin
tags:
  - ima
  - knowledge-base
  - backup
  - tencent
  - workbuddy-integration
  - file-upload
  - automation
license: MIT
---

# qianjin-ima-sync · WorkBuddy 成果自动备份到 ima（v2）

> 基于**官方 IMA OpenAPI**（`ima.qq.com`）封装的 WorkBuddy 专用备份技能。
> 底层接口与腾讯官方 `ima-skills` 完全一致，本技能在其之上额外提供：
> **整目录批量上传 + 智能路由（按路径自动选库）+ 自动增量备份（配合自动化定时运行）**。

---

## 一、能力概述

| 能力 | 说明 | 典型场景 |
|------|------|---------|
| **单文件上传** | 本地文件 → ima 知识库（4 步：预检→建媒体→COS→关联） | 写完文章立即备份 |
| **批量目录上传** | 扫描整个目录，按类型过滤，逐个上传 | 项目结束整包归档 |
| **自动增量备份** | 扫描 outputs，仅上传新增/修改的文件（去重） | 配自动化，每小时自动存档 |
| **文本转笔记** | 文本直接创建为 ima 笔记（Markdown） | 会议纪要/对话总结存为笔记 |
| **网页收藏** | 微信文章/公开网页加入知识库 | 看到好文一键收藏 |
| **智能路由** | 按文件类型/路径自动选知识库，免手动指定 | 不同项目自动归档到对应库 |
| **双向检索** | 搜索知识库内容、搜索/读取笔记（对齐官方） | 让 AI 调用 ima 做 RAG 第二大脑 |

---

## 二、与官方 `ima-skills` 的关系

本技能**不复刻官方底层**，而是建立在同一条官方 OpenAPI 之上：

| 维度 | 官方 `ima-skills` | 本技能 `qianjin-ima-sync` |
|------|------|------|
| 底层 API | `ima.qq.com` OpenAPI | 同一套（完全一致） |
| 认证 | `ima-openapi-clientid/key` | 同一套 |
| 笔记读写/搜索 | ✅ 原生支持 | ✅ 已对齐（import_doc/append_doc/search） |
| 知识库上传/检索 | ✅ 原生支持 | ✅ 已对齐（create_media/add_knowledge/search） |
| **整目录批量上传** | ❌（需手动逐个） | ✅ 核心差异化 |
| **智能路由（自动选库）** | ❌ | ✅ 核心差异化 |
| **自动增量备份（去重）** | ❌ | ✅ 配合自动化 |
| **与 WorkBuddy outputs 集成** | ❌ | ✅ 设计目标 |

> 结论：装了官方 `ima-skills` 也能用，但本技能让你「一键整包归档 + 自动定时备份」更省事。两者凭据通用，可并存。

---

## 三、API 基础（真实路径，务必以此为准）

| 项目 | 值 |
|------|------|
| **Base URL** | `https://ima.qq.com` |
| **认证方式** | 两个请求头：`ima-openapi-clientid`、`ima-openapi-apikey` |
| **请求方法** | **全部 POST** + JSON Body |
| **响应结构** | `{"retcode": 0, "errmsg": "", "data": {...}}`（`retcode != 0` 即失败） |
| **官方文档** | https://ima.qq.com/agent-interface |

> ⚠️ 旧版误写为 `https://api.ima.qq.com/v1` + Bearer，已废弃。**所有接口路径见下方各模块。**

### 3.1 辅助调用函数（Agent 现用）

```bash
ima_api() {
  local path="$1" body="$2"
  curl -s -X POST "https://ima.qq.com/$path" \
    -H "ima-openapi-clientid: $IMA_OPENAPI_CLIENTID" \
    -H "ima-openapi-apikey: $IMA_OPENAPI_APIKEY" \
    -H "Content-Type: application/json" \
    -d "$body"
}
```

> 推荐直接调用本技能脚本：`python scripts/ima_sync.py <子命令>`，无需手拼 curl。

---

## 四、凭据配置（与官方完全一致）

优先级：环境变量 → 配置文件。

```bash
# 方式 A：环境变量（推荐）
export IMA_OPENAPI_CLIENTID="你的ClientID"
export IMA_OPENAPI_APIKEY="你的APIKey"

# 方式 B：配置文件
mkdir -p ~/.config/ima
echo "你的ClientID"  > ~/.config/ima/client_id
echo "你的APIKey"    > ~/.config/ima/api_key
```

获取地址：https://ima.qq.com/agent-interface（Client ID + API Key，仅显示一次，立即保存）

---

## 五、脚本使用（真实可运行）

技能自带 `scripts/ima_sync.py`（纯 Python + requests + cos-python-sdk-v5），覆盖全部能力。

```bash
# 依赖（首次）
pip install requests cos-python-sdk-v5

# 凭据检查
python scripts/ima_sync.py check

# 单文件上传
python scripts/ima_sync.py upload-file "报告.md" --kb <knowledge_base_id>

# 整目录批量上传
python scripts/ima_sync.py upload-dir "E:/workbuddy/outputs/2026-07" --kb <kb_id>

# 自动增量备份（配合自动化定时运行）
python scripts/ima_sync.py auto-backup --watch "E:/workbuddy/outputs" --state "~/.config/ima-sync/state.json"

# 文本转笔记
python scripts/ima_sync.py note-new --title "周会纪要" --content-file "总结.md" --folder "工作记录"

# 网页收藏
python scripts/ima_sync.py save-url "https://mp.weixin.qq.com/s/xxx" --kb <kb_id>

# 搜索知识库
python scripts/ima_sync.py search-kb "AI内容创作" --kb <kb_id>

# 列出可添加的知识库
python scripts/ima_sync.py list-kb
```

---

## 六、核心能力实现（真实接口路径）

### 6.1 单文件上传到知识库（核心 4 步）

**Step 1 — 文件类型预检（本地）**
判断扩展名是否在支持列表，确定 `content_type` 与 `media_type`（文件类型枚举：pdf=1, doc/docx=1, xls/xlsx=5, ppt/pptx=4, md/txt=1, html=1, png/jpg/jpeg/gif/webp/svg=3，未知默认 1）。

**Step 2 — 创建媒体 `openapi/wiki/v1/create_media`**
```json
POST openapi/wiki/v1/create_media
{
  "file_name": "报告.md",
  "file_size": 10240,
  "content_type": "text/markdown",
  "knowledge_base_id": "<kb_id>",
  "file_ext": "md"
}
```
→ 返回 `data.media_id` 与 `data.cos_credential`（含 secret_id/secret_key/token/bucket_name/region/cos_key/start_time/expired_time）

**Step 3 — 上传到腾讯云 COS（用 cos_credential 临时凭证）**
用 `cos-python-sdk-v5` 将文件 PUT 到 `cos_key`。
```python
from qcloud_cos import CosConfig, CosS3Client
cfg = CosConfig(
    SecretId=cos_credential["secret_id"],
    SecretKey=cos_credential["secret_key"],
    Token=cos_credential["token"],
    Region=cos_credential["region"],
)
client = CosS3Client(cfg)
client.upload_file(
    Bucket=cos_credential["bucket_name"],
    Key=cos_credential["cos_key"],
    LocalFilePath=file_path,
    EnableMD5=True,
)
```

**Step 4 — 关联到知识库 `openapi/wiki/v1/add_knowledge`**
```json
POST openapi/wiki/v1/add_knowledge
{
  "media_type": 1,
  "media_id": "<media_id>",
  "title": "报告.md",
  "knowledge_base_id": "<kb_id>",
  "file_info": {
    "cos_key": "<cos_key>",
    "file_size": 10240,
    "file_name": "报告.md"
  }
}
```
→ 返回 `data.entry_id`，文件出现在目标知识库。

### 6.2 批量目录上传
扫描目录 → 按扩展名过滤 → 逐个走 6.1 四步 → 实时进度 + 失败重试（3 次，退避 2/5/10s）→ 汇总报告。

### 6.3 自动增量备份（去重）
- 维护状态文件（默认 `~/.config/ima-sync/state.json`），记录「已备份文件的相对路径 + mtime + size 指纹」。
- 每次运行扫描 watch 目录，计算指纹，**仅上传新增或修改**的文件。
- 配合 WorkBuddy 自动化（见第十节）可实现「每次生成自动存档」。

### 6.4 文本转笔记 `openapi/note/v1/import_doc`
```json
POST openapi/note/v1/import_doc
{
  "content_format": 1,
  "content": "# 标题\n\n正文（Markdown）",
  "folder_id": "<可选，笔记本ID>"
}
```
→ 返回 `data.doc_id`。
**追加到已有笔记**：`POST openapi/note/v1/append_doc` `{"doc_id":"<id>","content_format":1,"content":"..."}`（敏感操作，须用户明确指定目标笔记）。

### 6.5 网页收藏 `openapi/wiki/v1/import_urls`
```json
POST openapi/wiki/v1/import_urls
{
  "knowledge_base_id": "<kb_id>",
  "urls": ["https://mp.weixin.qq.com/s/xxx", "https://example.com/a"]
}
```
支持微信公众号文章、知乎、公开网页；**不支持** B站/YouTube 视频链接、`file://` 本地链接。

### 6.6 双向检索（对齐官方）
- 搜索知识库内容：`POST openapi/wiki/v1/search_knowledge` `{"query":"...","knowledge_base_id":"<kb_id>","cursor":""}`
- 搜索知识库（按名）：`POST openapi/wiki/v1/search_knowledge_base` `{"query":"","cursor":"","limit":50}`
- 列出可添加知识库：`POST openapi/wiki/v1/get_addable_knowledge_base_list` `{"cursor":"","limit":50}`
- 搜索笔记：`POST openapi/note/v1/search_note_book` `{"search_type":0,"query_info":{"title":"会议纪要"},"start":0,"end":20}`
- 读取笔记正文：`POST openapi/note/v1/get_doc_content` `{"doc_id":"<id>","target_content_format":0}`

---

## 七、智能路由（差异化核心）

按路径前缀/扩展名自动选库，避免每次手动指定。配置 `~/.config/ima-sync/routes.json`：

```json
{
  "rules": [
    {"match": {"path_prefix": "E:/workbuddy/outputs/公众号文章/"}, "target": {"knowledge_base_id": "kb_xxx"}, "tags": ["公众号","AI内容"]},
    {"match": {"file_type": "xlsx"}, "target": {"knowledge_base_id": "kb_yyy"}, "tags": ["数据","复盘"]},
    {"match": {"file_type": "md", "filename_match": "*周会*"}, "target": {"type": "note", "folder": "周会纪要"}}
  ],
  "default": {"type": "knowledge_base", "knowledge_base_id": "kb_default"}
}
```

`auto-backup` / `upload-dir` 默认按路由自动选库；若路由未命中则列出可添加知识库让用户选。

---

## 八、关键注意事项（来自官方经验，必读）

### ⚠️ UTF-8 编码（仅 notes 写入）
`import_doc` / `append_doc` 前，**必须**确保 `content`/`title` 为合法 UTF-8。来自文件（先检测编码转 UTF-8）、WebFetch（可能 GBK，须转码）、剪贴板的内容都不能假设已合法。非法编码会导致 ima 中**乱码且不可修复**。
```python
content = open(path, 'rb').read().decode('utf-8', errors='ignore')  # 或自动探测 gbk/big5
```

### ⚠️ PowerShell 5.1 环境（影响所有模块）
PowerShell 5.1 的 `Invoke-RestMethod` 会**静默将 Body 从 UTF-8 转 GBK**，导致中文乱码且无报错。检测版本，5.1 下必须将 JSON 显式转为 UTF-8 字节数组发送：
```powershell
$utf8 = [System.Text.Encoding]::UTF8.GetBytes($body)
Invoke-RestMethod -Uri $url -Method Post -Body $utf8 -ContentType "application/json; charset=utf-8" -Headers $headers
```

### ⚠️ 文件上传保持原样
上传文件到知识库时**不得转码**，以二进制原样上传，服务端自行处理编码。擅自转码会破坏 PDF/图片/Excel。

### ⚠️ 本地图片不支持写入笔记
`import_doc`/`append_doc` 的 `content` 仅支持文本/Markdown，**不支持本地图片路径**。写入前须过滤 `![](file:///...)`、`![](C:\...)` 等，并主动告知用户（网络图片 `http(s)://` 可保留）。

---

## 九、错误处理

| retcode | 含义 | 处理 |
|---------|------|------|
| 0 | 成功 | — |
| 100001 | 参数错误 | 检查请求体格式/必填字段 |
| 100002 | 无效 ID | 检查凭证 |
| 100003 | 服务器内部错误 | 稍后重试 |
| 100004 | size 不合法/空间不够 | 检查文件大小 |
| 100005 | 无权限 | 确认操作自己的资源 |
| 100006 | 笔记已删除 | 告知用户 |
| 100008 | 版本冲突 | 重新获取内容再操作 |
| 100009 | 超过笔记大小限制 | 拆分多次 `append_doc` |
| 20002 | API 限频 | 降速，加 retry（批量已内置 1-2s 间隔） |
| 200002 | skill auth failed（凭证失效/过期） | **不是网络问题**：去 <https://ima.qq.com/agent-interface> 续期或重新生成 Key |
| 220001 | 参数错误（如 media_type 不受支持） | SVG 等矢量图不受支持，先转 png/jpg |
| 220004 | 知识库权限/不存在 | 用 `list-kb` 取编码串 ID，勿用网页 URL 里的纯数字 ID |

### ⚠️ 凭证 401：IMA Skills API Key 有 30 天有效期

实测结论（2026-09-06）：凭证生成满 30 天后，所有接口统一返回：

```
HTTP 401  {"code":200002,"msg":"skill auth failed"}
```

这不是网络抖动，也不是脚本 bug，是 Key 到期。处理要点：

- **续期优先于重新生成**：在 <https://ima.qq.com/agent-interface> 点「续期」，client_id 与 api_key 字符串均不变，配置文件无需改动，重跑即可。
- **重新生成**才会换字符串，届时须覆盖 `~/.config/ima/api_key`（必要时连同 client_id）。
- 一键自检：`python scripts/ima_sync.py check`，能列出知识库即凭证有效。
- 脚本已内置识别：HTTP 401/403 或 code 200002 会打印中文修复指引，且 `auto-backup` 立即终止，避免几十个文件排队重试。

> 提示：IMA 的 MCP 连接器与 OpenAPI 凭证是两套体系，MCP 能连通不代表 OpenAPI 凭证有效。

---

## 十、自动增量备份（配合 WorkBuddy 自动化）

本技能的杀手锏：**让 WorkBuddy 成果「生成即存档」**。

在 WorkBuddy 中创建一个 recurring 自动化（如每小时），prompt 为：
> 「运行 qianjin-ima-sync 的自动增量备份：扫描 `E:/workbuddy/outputs` 下新增/修改的文件，按智能路由规则上传到对应 ima 知识库。完成后报告成功/失败数量；新知识库先 `list-kb` 确认。」

脚本内部用 `state.json` 指纹去重，只传变化文件，安全幂等。

---

## 十一、安全

- ✅ 凭据仅经 `ima-openapi-clientid/key` 头发往 `ima.qq.com`，绝不发往其他域名或写日志。
- ✅ 临时 COS 凭证仅用于本次上传，过期自动失效。
- ✅ 凭据文件权限建议设 `600`。
- ✅ 笔记内容属隐私：群聊场景仅展示标题/摘要，不展示正文。

---

## 十二、触发词

| 场景 | 示例 |
|------|------|
| 单文件上传 | "把刚生成的报告传到ima" |
| 批量备份 | "把 outputs 下这个月的成果都备份到ima" |
| 自动备份 | "开启自动备份" / "每次生成自动存ima" |
| 文本转笔记 | "把刚才的总结存到ima笔记" |
| 网页收藏 | "把这篇微信文章存到ima案例库" |
| 搜索 | "在ima里找XX的笔记" / "搜ima知识库" |
| 智能备份 | "把WorkBuddy今天生成的都传上去" |

---

## 十三、版本记录

| 版本 | 日期 | 变更 |
|------|------|------|
| v2.1 | 2026-09-06 | 新增凭证鉴权失败识别（HTTP 401/403 + code 200002 输出中文修复指引，不再误报为"网络/请求失败"）；`auto-backup` 遇鉴权失败 fail-fast 立即终止；补 `check` 自检说明与 30 天有效期排查指引；修正错误码 20002/20004 → 200002/220001/220004 |
| v2.0 | 2026-07-18 | 对齐官方真实 API（ima.qq.com + ima-openapi 头 + openapi/*/v1 路径）；新增真实脚本 scripts/ima_sync.py；融合双向读写/检索；新增自动增量备份 + 智能路由 |
| v1.0 | 2026-07-18 | 初始理念稿（API 路径有误，已废弃） |

---

*底层基于腾讯官方 IMA OpenAPI，所有操作走 ima.qq.com 官方接口。*
