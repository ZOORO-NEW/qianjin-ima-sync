---
name: qianjin-ima-sync
description: "WorkBuddy 生成内容自动备份到腾讯 ima 知识库。输入文件路径或文本内容，自动调用 IMA OpenAPI 上传到指定知识库或创建笔记。支持单文件上传、批量备份、文本转笔记、网页收藏。适用于工作流成果存档、个人知识库积累、跨设备内容同步。触发词：备份到ima、上传到ima、存到ima知识库、ima同步、ima备份、归档到ima、保存到腾讯ima、生成的内容上传到ima。"
version: "1.0"
author: qianjin
tags:
  - ima
  - knowledge-base
  - backup
  - tencent
  - workbuddy-integration
  - file-upload
license: MIT
---

# qianjin-ima-sync · WorkBuddy 成果自动备份到 ima

> **打通 WorkBuddy 与腾讯 ima 知识库的最后一步**。WorkBuddy 的连接器能直接连 ima，但**无法把生成的文件上传到 ima**——这个技能就是补上这个缺口。

---

## 一、能力概述

| 能力 | 说明 | 典型场景 |
|------|------|---------|
| **单文件上传** | 把本地文件（PDF/MD/DOCX/XLSX/图片等15种）传到 ima 知识库 | 写完一篇文章 → 立即备份 |
| **批量备份** | 上传整个目录的所有文件 | 项目结束 → 整包归档 |
| **文本转笔记** | 把文本内容直接创建为 ima 笔记 | 写完聊天总结/会议纪要 → 立即保存 |
| **网页收藏** | 把微信文章/网页链接加入 ima 知识库 | 看到好文章 → 自动收藏 |
| **智能路由** | 按文件类型/标签自动选择知识库 | 不同项目自动归档到对应库 |

### 1.1 与 ima 原生 skill 的区别

| 项目 | ima 原生 skill | qianjin-ima-sync（本技能） |
|------|--------------|--------------------------|
| 调用 IMA OpenAPI | ✅ | ✅ |
| 读取/搜索笔记/知识库 | ✅ | ✅（保留基础能力） |
| **从本地路径上传文件** | ⚠️ 需手动给路径 | ✅ **自动接管 WorkBuddy 生成的 outputs/** |
| **批量上传整个目录** | ❌ | ✅ |
| **自动按文件类型选择知识库** | ❌ | ✅ |
| **上传进度反馈** | ❌ | ✅（每文件实时显示） |
| **与 WorkBuddy 工作流集成** | ❌ | ✅（设计目标） |

---

## 二、API 基础信息

| 项目 | 内容 |
|------|------|
| **API 基础地址** | `https://api.ima.qq.com/v1` |
| **认证方式** | Bearer Token |
| **请求格式** | JSON（部分上传接口用 multipart/form-data） |
| **API Key 格式** | `ima_sk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` |
| **官方文档** | https://ima.qq.com/agent-interface |

### 2.1 凭据配置

首次使用前，需要用户配置以下两个凭证：

| 变量名 | 说明 | 获取方式 |
|--------|------|---------|
| `IMA_CLIENT_ID` | 应用标识 | 访问 https://ima.qq.com/agent-interface 获取 |
| `IMA_API_KEY` | 接口调用密钥 | 同上，**仅显示一次请立即保存** |

#### 配置方式（按优先级尝试）

**方式一：环境变量（推荐）**
```bash
export IMA_OPENAPI_CLIENTID="你的ClientID"
export IMA_OPENAPI_APIKEY="你的APIKey"
```

**方式二：配置文件**
```bash
mkdir -p ~/.config/ima
echo "你的ClientID" > ~/.config/ima/client_id
echo "你的APIKey" > ~/.config/ima/api_key
```

**方式三：技能首次运行时引导用户输入**
- 检测到无凭据时，向用户展示获取链接和操作步骤
- 临时保存为环境变量（不写盘），本次会话有效

### 2.2 凭据检查（强制）

每次执行前必须执行：

```python
import os
def check_ima_credentials():
    client_id = os.environ.get('IMA_OPENAPI_CLIENTID')
    api_key = os.environ.get('IMA_OPENAPI_APIKEY')
    if not client_id or not api_key:
        config_path = os.path.expanduser('~/.config/ima/')
        if os.path.exists(os.path.join(config_path, 'client_id')):
            client_id = open(os.path.join(config_path, 'client_id')).read().strip()
            api_key = open(os.path.join(config_path, 'api_key')).read().strip()
    if not client_id or not api_key:
        raise Exception("""
⚠️ 未检测到 IMA 凭据，请按以下步骤配置：

1. 访问 https://ima.qq.com/agent-interface
2. 点击「获取 API Key」获取 Client ID 和 API Key
3. 配置环境变量：
   export IMA_OPENAPI_CLIENTID="你的ClientID"
   export IMA_OPENAPI_APIKEY="你的APIKey"
   （重启 WorkBuddy 后生效）
""")
    return client_id, api_key
```

---

## 三、支持的操作

### 3.1 文件上传到知识库（核心能力）

**完整流程（4步）：**

```
Step 1: 文件类型预检（preflight-check）
  ↓ 确认是 ima 支持的类型
Step 2: 创建媒体记录（create_media）
  ↓ 获得 media_id
Step 3: 上传到 COS（cos-upload）
  ↓ 获得文件在 COS 的存储位置
Step 4: 关联到知识库（add_knowledge）
  ↓ 文件出现在目标知识库
```

**Step 1 - 文件类型预检**

```python
def preflight_check(file_path: str) -> dict:
    """预检：确认文件类型是否被 ima 支持"""
    SUPPORTED_EXTS = {
        'pdf', 'docx', 'doc', 'xlsx', 'xls', 'pptx', 'ppt',
        'md', 'txt', 'html',
        'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg',
    }
    UNSUPPORTED = {
        'video': '视频文件不支持，请用 IMA 桌面客户端',
        'audio': '音频文件不支持',
        'url_bilibili': 'B站视频链接不支持',
        'url_youtube': 'YouTube 视频链接不支持',
        'url_file': 'file:// 链接不支持',
    }
    # ... 检测逻辑
```

**Step 2 - 创建媒体记录**

```python
POST https://api.ima.qq.com/v1/wiki/medias
Headers:
  Authorization: Bearer {API_KEY}
  Content-Type: application/json
Body:
{
  "knowledge_base_id": "kb_xxx",
  "file_name": "article_2026-07-18.md",
  "file_size": 102400,
  "file_ext": "md",
  "content_type": "text/markdown"
}
→ 响应：{"code": 0, "data": {"media_id": "media_xxx"}}
```

**Step 3 - 上传到 COS**

```python
# 通过腾讯云 COS 上传（使用 ima 提供的临时凭证）
POST https://cos.{region}.myqcloud.com/{bucket}/{key}
Headers:
  Content-Type: {content_type}
  Authorization: {temp_secret}

# 临时凭证由 create_media 响应返回
# 或单独调用获取 COS 上传凭证的接口
```

**Step 4 - 关联到知识库**

```python
POST https://api.ima.qq.com/v1/wiki/entries
Headers:
  Authorization: Bearer {API_KEY}
  Content-Type: application/json
Body:
{
  "knowledge_base_id": "kb_xxx",
  "media_id": "media_xxx",
  "media_type": 1,
  "title": "article_2026-07-18.md"
}
→ 响应：{"code": 0, "data": {"entry_id": "entry_xxx"}}
```

### 3.2 批量上传目录

```python
def batch_upload_directory(directory: str, knowledge_base_id: str, 
                         recursive: bool = False, file_types: list = None):
    """上传整个目录到指定知识库"""
    results = {'success': [], 'failed': [], 'skipped': []}
    
    for file_path in scan_files(directory, recursive):
        # 文件类型过滤
        if file_types and not file_path.endswith(tuple(file_types)):
            results['skipped'].append((file_path, '类型不匹配'))
            continue
        
        # 预检
        if not preflight_check(file_path)['supported']:
            results['skipped'].append((file_path, '类型不支持'))
            continue
        
        try:
            upload_file(file_path, knowledge_base_id)
            results['success'].append(file_path)
            print(f"✅ {file_path}")
        except Exception as e:
            results['failed'].append((file_path, str(e)))
            print(f"❌ {file_path}: {e}")
    
    return results
```

### 3.3 文本转笔记

```python
POST https://api.ima.qq.com/v1/notes
Headers:
  Authorization: Bearer {API_KEY}
  Content-Type: application/json
Body:
{
  "title": "周会议题总结 - 2026-07-18",
  "content": "## 议题 1：...",
  "content_format": 1,  # 1=Markdown, 0=纯文本
  "folder_name": "周会纪要",  # 可选：归入指定文件夹
  "tags": ["会议纪要", "周会"]  # 可选
}
```

**追加到已有笔记：**
```python
POST https://api.ima.qq.com/v1/notes/{note_id}/append
Body:
{
  "content": "\n## 新增内容\n...",
  "content_format": 1
}
```

### 3.4 网页收藏到知识库

```python
POST https://api.ima.qq.com/v1/wiki/entries/import-urls
Body:
{
  "knowledge_base_id": "kb_xxx",
  "urls": [
    "https://mp.weixin.qq.com/s/abc123",
    "https://example.com/article"
  ]
}
```

**支持：微信公众号文章、知乎专栏、新闻报道等公开网页**
**不支持：B站、YouTube 视频链接、file:// 本地链接**

### 3.5 知识库与笔记查询

```python
# 列出所有可访问的知识库
GET https://api.ima.qq.com/v1/wiki/knowledge-bases

# 搜索知识库内容
POST https://api.ima.qq.com/v1/wiki/entries/search
Body:
{
  "query": "AI 内容创作",
  "knowledge_base_id": "kb_xxx",  # 可选，留空则搜索全部
  "limit": 20
}

# 列出笔记
GET https://api.ima.qq.com/v1/notes?limit=20&folder=工作记录

# 读取笔记内容
GET https://api.ima.qq.com/v1/notes/{note_id}/content
```

---

## 四、智能路由（差异化核心能力）

按文件类型/路径前缀/标签自动选择目标知识库，避免每次手动指定：

### 4.1 路由配置

```python
# ~/.config/ima-sync/routes.json
{
  "rules": [
    {
      "match": {"path_prefix": "E:/workbuddy/outputs/公众号文章/"},
      "target": {"knowledge_base_id": "kb_xxx", "type": "knowledge_base"},
      "tags": ["公众号", "AI内容"]
    },
    {
      "match": {"path_prefix": "E:/workbuddy/outputs/数据分析/"},
      "target": {"knowledge_base_id": "kb_yyy", "type": "knowledge_base"},
      "tags": ["数据", "复盘"]
    },
    {
      "match": {"file_type": "md", "filename_match": "*周会*"},
      "target": {"type": "note", "folder": "周会纪要"},
      "tags": ["会议"]
    },
    {
      "match": {"file_type": "pdf"},
      "target": {"type": "ask_user"}  # 让用户选择
    }
  ],
  "default": {
    "type": "knowledge_base",
    "knowledge_base_id": "kb_default"
  }
}
```

### 4.2 智能识别 WorkBuddy 输出

```python
WORKBUDDY_OUTPUT_PATTERNS = {
    "公众号文章": "E:/workbuddy/outputs/公众号文章/*.md",
    "数据分析报告": "E:/workbuddy/outputs/数据分析/*.xlsx",
    "技能脚本": "E:/workbuddy/skills/**/*.py",
    "周会纪要": "E:/workbuddy/outputs/周会/*.md",
    "AI 配音视频": "E:/workbuddy/outputs/*.mp4",  # 跳过：mp4 不支持
    "知识地图": "E:/workbuddy/outputs/知识地图/*.svg",  # svg 支持
}
```

---

## 五、核心使用场景

### 场景 1：把刚写完的公众号文章备份到 ima

> 用户：把刚生成的《AI内容创作全链路》那篇文章传到ima

技能执行：
1. 找到最新生成的 `AI内容创作全链路_xxx.md`
2. 调用 `preflight_check` → ✅ MD 文件支持
3. 列出 ima 知识库，询问用户选择目标
4. 用户选择"AI 实战"知识库
5. 执行 4 步上传流程
6. 返回："✅ 已上传到 ima「AI 实战」知识库"

### 场景 2：批量备份整个 outputs 目录

> 用户：把 outputs 下这个月的成果都备份到ima

技能执行：
1. 扫描 `E:/workbuddy/outputs/2026-07/` 下所有支持的文件
2. 智能路由：MD → 知识库 / XLSX → 数据分析知识库 / 大文件 → 询问
3. 显示预估：15个文件，预计3-5分钟
4. 用户确认后开始批量上传
5. 实时显示进度：`[3/15] 文章1.md ✅`
6. 完成报告：成功 12，失败 0，跳过 3（视频）

### 场景 3：把聊天总结/会议纪要存为笔记

> 用户：刚才的对话总结一下，存到ima

技能执行：
1. 总结对话内容为结构化笔记
2. 询问用户标题、文件夹、标签
3. 调用 `POST /notes` 创建笔记
4. 返回："✅ 笔记「XX对话总结」已创建在「工作记录」文件夹"

### 场景 4：把看到的公众号好文存下来

> 用户：把 https://mp.weixin.qq.com/s/xxx 存到ima的「案例库」

技能执行：
1. 调用 `POST /wiki/entries/import-urls`
2. 等待 ima 服务端解析网页
3. 反馈："✅ 微信文章已收藏到「案例库」"

### 场景 5：搜索 ima 知识库找资料

> 用户：在ima里找一下关于"AI内容创作"的笔记

技能执行：
1. 调用 `POST /wiki/entries/search`
2. 返回 3-5 条相关结果
3. 询问是否需要查看原文/导入到本地

---

## 六、执行流程

### 6.1 完整流程图

```
用户输入指令
  │
  ▼
1. 凭据检查 ← 缺失则引导配置
  │
  ▼
2. 解析任务类型
  ├── 单文件上传 → 进入 6.2
  ├── 批量上传 → 进入 6.3
  ├── 文本转笔记 → 进入 6.4
  └── 网页收藏 → 进入 6.5
  │
  ▼
3. 选择目标知识库/文件夹
  ├── 用户指定 → 直接使用
  ├── 智能路由 → 自动匹配
  └── 都不行 → 列出可选项让用户选
  │
  ▼
4. 预检 / 确认
  ├── 文件类型预检
  ├── 显示预估时间
  └── 用户确认（批量操作必需要）
  │
  ▼
5. 执行上传
  ├── 显示实时进度
  ├── 错误重试（3次）
  └── 部分成功也要继续
  │
  ▼
6. 输出报告
  ├── 成功/失败/跳过 数量
  ├── 失败原因分析
  └── 后续操作建议
```

### 6.2 单文件上传

```python
def upload_single_file(file_path: str, target):
    """单文件上传到指定目标"""
    # 1. 预检
    pre = preflight_check(file_path)
    if not pre['supported']:
        return {'error': pre['reason']}
    
    # 2. 创建媒体
    media = create_media(
        knowledge_base_id=target['knowledge_base_id'],
        file_name=os.path.basename(file_path),
        file_size=os.path.getsize(file_path),
        file_ext=pre['ext'],
        content_type=pre['mime_type']
    )
    
    # 3. 上传 COS
    cos_upload(file_path, media['upload_credentials'])
    
    # 4. 关联知识库
    entry = add_knowledge(
        media_id=media['media_id'],
        knowledge_base_id=target['knowledge_base_id'],
        title=os.path.basename(file_path)
    )
    
    return {'entry_id': entry['entry_id'], 'url': entry.get('url')}
```

### 6.3 批量上传

```python
def batch_upload(directory: str, target, recursive=False, file_types=None):
    """批量上传整个目录"""
    files = scan_files(directory, recursive=recursive, file_types=file_types)
    if not files:
        return {'message': '没有符合条件的文件'}
    
    # 预估
    total_size = sum(os.path.getsize(f) for f in files)
    print(f"📊 准备上传 {len(files)} 个文件，总大小 {total_size/1024:.1f}KB")
    print(f"⏱️ 预计耗时 {len(files) * 5}-{len(files) * 15} 秒")
    
    # 用户确认
    if not confirm("是否继续？"):
        return {'cancelled': True}
    
    # 执行
    results = {'success': [], 'failed': [], 'skipped': []}
    for i, file_path in enumerate(files, 1):
        print(f"\n[{i}/{len(files)}] {os.path.basename(file_path)}")
        try:
            upload_single_file(file_path, target)
            results['success'].append(file_path)
            print(f"  ✅ 成功")
        except Exception as e:
            # 失败重试 3 次
            for attempt in range(3):
                try:
                    time.sleep(2)
                    upload_single_file(file_path, target)
                    results['success'].append(file_path)
                    print(f"  ✅ 重试成功")
                    break
                except:
                    pass
            else:
                results['failed'].append((file_path, str(e)))
                print(f"  ❌ 失败: {e}")
    
    return results
```

### 6.4 文本转笔记

```python
def text_to_note(title: str, content: str, folder: str = None, tags: list = None):
    """把文本转为 ima 笔记"""
    return requests.post(
        f"{IMA_API_BASE}/notes",
        headers=IMA_HEADERS,
        json={
            "title": title,
            "content": content,
            "content_format": 1,  # Markdown
            "folder_name": folder,
            "tags": tags or []
        }
    ).json()
```

### 6.5 网页收藏

```python
def save_url_to_ima(url: str, knowledge_base_id: str):
    """把网页链接加入 ima 知识库"""
    # 检查是否支持
    if 'bilibili.com' in url or 'youtube.com' in url:
        return {'error': '视频链接不支持，请用 IMA 桌面客户端'}
    
    return requests.post(
        f"{IMA_API_BASE}/wiki/entries/import-urls",
        headers=IMA_HEADERS,
        json={
            "knowledge_base_id": knowledge_base_id,
            "urls": [url]
        }
    ).json()
```

---

## 七、错误处理

### 7.1 常见错误码

| 错误码 | 含义 | 处理 |
|--------|------|------|
| 401 | API Key 无效 | 引导用户重新生成 |
| 403 | 知识库权限不足 | 提示用户检查知识库权限 |
| 20002 | API 频率限制 | 提示用户降速，加 retry 逻辑 |
| 404 | 知识库/笔记不存在 | 让用户重新选择 |
| 文件类型不支持 | PDF/Office/图片之外的格式 | 明确告诉用户哪些支持 |
| 临时凭证过期 | COS 上传凭证失效 | 重新调用 create_media 刷新凭证 |

### 7.2 重试策略

```python
RETRY_CONFIG = {
    'max_retries': 3,
    'backoff': [2, 5, 10],  # 等待秒数
    'retry_on': [Timeout, ConnectionError, 500, 502, 503, 504, 20002]
}
```

---

## 八、安全与限制

### 8.1 安全要求

- ✅ API Key 只能通过环境变量或 `~/.config/ima/` 配置文件
- ✅ 绝不能硬编码、打印、写入日志
- ✅ 临时保存凭据也不写盘
- ✅ 凭据文件权限设为 600

### 8.2 API 限制

- ⚠️ **频率限制**：API 有 QPS 限制，批量上传自动加 1-2 秒间隔
- ⚠️ **文件大小**：单文件最大 100MB（建议单次操作不要超过 500MB 总和）
- ⚠️ **不支持视频**：MP4/MOV/AVI 不支持，提示用户用 IMA 桌面客户端
- ⚠️ **不支持 B 站/YouTube 链接**：同上
- ⚠️ **不支持 file:// 本地链接**：同上

### 8.3 数据安全声明

本技能是 WorkBuddy 官方 ima 技能的扩展：
- 数据传输走 ima 官方 OpenAPI（https://api.ima.qq.com）
- 凭据只发往 ima.qq.com，不会发到任何其他域名
- 临时文件不上传到第三方服务（除 ima 和腾讯云 COS 之外）
- 用户上传什么完全由用户控制

---

## 九、触发词

| 场景 | 对话示例 |
|------|---------|
| 单文件上传 | "把刚生成的报告传到ima" / "上传这篇文章到ima" |
| 批量备份 | "把 outputs 下这个月的成果都备份到ima" / "归档到ima" |
| 文本转笔记 | "把刚才的总结存到ima笔记" / "存成ima笔记" |
| 网页收藏 | "把这篇微信文章存到ima案例库" |
| 搜索知识库 | "在ima里找一下XX的笔记" / "搜ima知识库" |
| 列出知识库 | "我的ima有哪些知识库" / "显示ima知识库列表" |
| 智能备份 | "把WorkBuddy今天生成的都传上去" |

---

## 十、使用示例

### 示例 1：单文件上传

```
用户：把 E:/workbuddy/outputs/公众号文章/AI内容创作.md 传到ima
助手：
🔍 检查凭据... ✅
📊 目标文件：AI内容创作.md (32.5KB)
📋 知识库列表：
  1. AI 实战 [kb_001]
  2. 工作记录 [kb_002]
  3. 默认知识库 [kb_003]
请选择目标知识库（输入编号）：
> 1
📤 开始上传...
  Step 1/4 预检：✅ MD 文件支持
  Step 2/4 创建媒体记录：✅ media_id=media_abc123
  Step 3/4 上传 COS：✅ 32.5KB 已上传
  Step 4/4 关联知识库：✅ entry_id=entry_xyz789
✅ 上传成功！
  知识库：AI 实战
  条目：AI内容创作.md
  链接：https://ima.qq.com/kb/entry/xyz789
```

### 示例 2：批量备份

```
用户：把 outputs/2026-07 下所有 md 和 xlsx 备份到ima
助手：
🔍 检查凭据... ✅
📁 扫描目录：outputs/2026-07/
📊 找到 12 个文件（MD: 8, XLSX: 4），总大小 245KB
⏱️ 预计耗时 60-180 秒

是否继续？[y/N]
> y

[1/12] 公众号文章1.md ✅ (32KB)
[2/12] 公众号文章2.md ✅ (28KB)
[3/12] 公众号文章3.md ✅ (41KB)
...
[8/12] 公众号文章8.md ✅ (22KB)
[9/12] 7月数据分析.xlsx ✅ (18KB)
...
[12/12] 项目复盘.xlsx ✅ (12KB)

✅ 批量上传完成！
  成功：12
  失败：0
  跳过：0
```

### 示例 3：智能路由

```
用户：把刚生成的 outputs/数据分析/Q2复盘.xlsx 传到ima
助手：
🔍 检查凭据... ✅
📊 目标文件：Q2复盘.xlsx
🎯 智能路由匹配：路径前缀 "outputs/数据分析/" → 知识库「数据复盘」
✅ 自动确认目标：kb_005「数据复盘」
📤 上传中...
✅ 成功上传到「数据复盘」知识库
```

---

## 十一、版本记录

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-07-18 | 初始版本：单文件/批量上传、文本转笔记、网页收藏、智能路由 |

---

*基于 IMA 官方 OpenAPI v1 构建，所有操作走 ima.qq.com 官方接口。*
