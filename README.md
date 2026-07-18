# qianjin-ima-sync · WorkBuddy 成果自动备份到 ima

**基于腾讯官方 IMA OpenAPI（`ima.qq.com`）封装的 WorkBuddy 专用备份技能。**
底层接口与官方 `ima-skills` 完全一致，本技能在其之上额外提供：**整目录批量上传 + 智能路由（按路径自动选库）+ 自动增量备份（配合自动化定时运行）**。

## 与官方 `ima-skills` 的关系

本技能不复刻官方底层，而是建立在同一套官方 OpenAPI 之上：

- 底层 API、认证方式、笔记/知识库读写检索能力 —— 与官方 `ima-skills` 完全一致
- 差异化能力：**整目录批量上传**、**智能路由自动选库**、**自动增量备份（去重）**

两者凭据通用，可并存。装了官方也能用，但本技能让你「一键整包归档 + 自动定时备份」更省事。

## 核心能力

| 能力 | 说明 |
|------|------|
| 📤 **单文件上传** | 4 步（预检→建媒体→COS→关联）上传到 ima 知识库 |
| 📁 **批量备份** | 整目录扫描，按类型过滤，逐个上传 |
| 🔁 **自动增量备份** | 扫描 outputs，仅上传新增/修改文件（指纹去重） |
| 📝 **文本转笔记** | 任意文本/Mardown 直接创建为 ima 笔记 |
| 🔗 **网页收藏** | 微信文章、公开网页一键加入知识库 |
| 🎯 **智能路由** | 按文件路径/类型自动选择目标知识库，免手动指定 |
| 🔍 **双向检索** | 搜索知识库内容、搜索/读取笔记 |

## 快速开始

### 1. 安装依赖
```bash
pip install requests cos-python-sdk-v5
```

### 2. 配置凭据（与官方一致）
```bash
# 方式 A：环境变量
export IMA_OPENAPI_CLIENTID="你的ClientID"
export IMA_OPENAPI_APIKEY="你的APIKey"

# 方式 B：配置文件
mkdir -p ~/.config/ima
echo "你的ClientID"  > ~/.config/ima/client_id
echo "你的APIKey"    > ~/.config/ima/api_key
```
获取地址：https://ima.qq.com/agent-interface

### 3. 常用命令
```bash
# 凭据检查 / 列出可添加知识库
python scripts/ima_sync.py check
python scripts/ima_sync.py list-kb

# 单文件上传
python scripts/ima_sync.py upload-file "报告.md" --kb <知识库ID>

# 整目录批量上传
python scripts/ima_sync.py upload-dir "E:/workbuddy/outputs/2026-07" --kb <知识库ID>

# 自动增量备份（配合自动化定时运行）
python scripts/ima_sync.py auto-backup --watch "E:/workbuddy/outputs" --state "~/.config/ima-sync/state.json"

# 文本转笔记
python scripts/ima_sync.py note-new --title "周会纪要" --content-file "总结.md" --folder "工作记录"

# 网页收藏
python scripts/ima_sync.py save-url "https://mp.weixin.qq.com/s/xxx" --kb <知识库ID>

# 搜索知识库
python scripts/ima_sync.py search-kb "AI内容创作" --kb <知识库ID>
```

## 自动增量备份（生成即存档）

配合 WorkBuddy 自动化（recurring，如每小时）运行 `auto-backup`：
- 脚本维护状态文件（默认 `~/.config/ima-sync/state.json`），记录已备份文件的路径+mtime+size 指纹
- 每次仅上传新增/修改的文件，幂等安全

在 WorkBuddy 中创建自动化，prompt 示例：
> 运行 qianjin-ima-sync 自动增量备份：执行 `scripts/ima_sync.py auto-backup --watch E:/workbuddy/outputs --state ~/.config/ima-sync/state.json`，按智能路由上传到对应 ima 知识库。完成后报告成功/失败数量。

## 智能路由

配置 `~/.config/ima-sync/routes.json`：
```json
{
  "rules": [
    {"match": {"path_prefix": "E:/workbuddy/outputs/公众号文章/"}, "target": {"knowledge_base_id": "kb_xxx"}, "tags": ["公众号"]},
    {"match": {"file_type": "xlsx"}, "target": {"knowledge_base_id": "kb_yyy"}}
  ],
  "default": {"type": "knowledge_base", "knowledge_base_id": "kb_default"}
}
```

## 支持的文件类型

✅ PDF、Word、Excel、PPT、Markdown、TXT、HTML、PNG、JPG、GIF、SVG 等
❌ 视频、音频、B站/YouTube 链接（需用 IMA 桌面客户端）

## 重要注意事项

- **UTF-8**：写入笔记前确保内容为合法 UTF-8，否则 ima 中乱码且不可修复
- **PowerShell 5.1**：Body 须显式转 UTF-8 字节数组，否则中文乱码
- **文件原样上传**：上传文件不得转码，以二进制上传
- **本地图片**：笔记接口不支持本地图片，写入前须过滤

## 安装位置

```
~/.workbuddy/skills/qianjin-ima-sync/
├── SKILL.md
├── README.md
└── scripts/
    └── ima_sync.py
```

## License

MIT
