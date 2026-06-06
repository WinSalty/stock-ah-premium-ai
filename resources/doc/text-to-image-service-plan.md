# 文生图基础服务接入开发方案

更新日期：2026-05-27

## 1. 背景与目标

本功能用于在 `stock-ah-premium-ai` 项目中新增可复用的文生图基础服务，首期先提供一个独立菜单让用户输入提示词生成图片，后续可被问答、雪球发布、打板报告、封面图生成等模块复用。

首期目标如下：

- 后端封装统一文生图服务，不让前端直接接触 API Key。
- 图片生成结果保存到阿里 OSS 私有 Bucket，页面关闭后仍可继续查看历史图片。
- 图片记录按系统用户隔离；普通用户只看自己的图片，管理员可查看全部图片。
- 每人默认每天最多生成 10 次；管理员可在用户管理菜单维护单个用户每日次数或重置当日已用次数。
- 前端新增“图片生成”菜单，兼顾桌面端和移动端展示。
- API Key 只通过环境变量或本机未入库文件注入，不写入项目代码、SQL、文档或前端产物。

## 2. 外部 API 口径

已读取 86GameStore 生图 API 文档，当前可按 OpenAI Images API 兼容方式调用。

接口口径：

- Base URL：`https://api.86gamestore.com`
- Endpoint：`POST /v1/images/generations`
- Model：`gpt-image-2`
- 认证：请求头 `Authorization: Bearer <API_KEY>`，`Content-Type: application/json`
- 请求体：`model`、`prompt`、`size` 必填，`n` 可选，首期固定 `n=1`
- 返回：可能是 `{ data: [{ url: "https://..." }] }`，也可能是 `{ data: [{ b64_json: "..." }] }`
- 当前公开文档只描述文生图 `generations` 能力，未写参考图上传、图生图、图片编辑或 `image`/`mask` 等入参；但 86GameStore 自定义页面存在参考图上传样式，说明网页端可能使用了未公开文档的内部接口或 OpenAI 兼容编辑接口。首期产品层按“支持上传参考图”设计，供应商适配层在开发时通过接口验证后启用真实调用。

OpenAI 官方口径：

- OpenAI Image API 支持 `generations` 和 `edits`；`edits` 可用已有图片作为参考生成新图，也可配合 mask 做局部编辑。
- OpenAI Responses API 的 `image_generation` 工具支持在上下文中接收图片输入，图片可来自 URL、Base64 data URL 或 Files API 的 file ID。
- 因此本项目的抽象层应区分“纯文生图”和“带参考图生成/编辑”，避免被单一供应商文档限制住后续扩展。

支持尺寸：

| 清晰度 | size | 比例 | 文档消耗 |
| --- | --- | --- | --- |
| 1K | `1024x1024` | 1:1 | 0.05 |
| 2K | `2048x2048` | 1:1 | 0.10 |
| 2K | `1536x1024` | 3:2 | 0.10 |
| 2K | `1024x1536` | 2:3 | 0.10 |
| 4K | `3840x2160` | 16:9 | 0.20 |
| 4K | `2160x3840` | 9:16 | 0.20 |

首期默认 `1024x1024`，原因是费用最低、生成更快、移动端列表加载压力更小；页面开放全部合法尺寸供用户选择，管理员后续可按成本情况收紧。

## 3. 配置与密钥管理

后端新增配置项，统一放在 `backend/app/core/config.py`，并同步 `backend/.env.example`，但不写真实密钥。

建议配置：

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `IMAGE_GEN_BASE_URL` | `https://api.86gamestore.com` | 文生图服务 Base URL。 |
| `IMAGE_GEN_API_KEY` | 空 | 环境变量直接注入的 API Key，作为文件读取失败后的兜底。 |
| `IMAGE_GEN_API_KEY_FILE` | `/Users/salty/codeProject/ai/doc/86gamestore-image-apikey.txt` | 本机未入库密钥文件，优先读取。 |
| `IMAGE_GEN_MODEL` | `gpt-image-2` | 默认文生图模型。 |
| `IMAGE_GEN_TIMEOUT_SECONDS` | `300` | 生图最长等待时间，文档示例也使用 300 秒。 |
| `IMAGE_GEN_DAILY_LIMIT_DEFAULT` | `10` | 新用户默认每日生成次数。 |
| `IMAGE_GEN_STORAGE_BACKEND` | `oss` | 图片存储后端，生产环境使用阿里 OSS；`local` 仅用于单测或旧环境兜底。 |
| `IMAGE_GEN_STORAGE_DIR` | `/opt/stock-ah-premium-ai/data/generated-images` | 本地兜底存储根目录，仅 `IMAGE_GEN_STORAGE_BACKEND=local` 时使用。 |
| `IMAGE_GEN_OSS_ENDPOINT` | 空 | 阿里 OSS Bucket 所在地域 Endpoint。 |
| `IMAGE_GEN_OSS_BUCKET` | 空 | 保存生成图和参考图的私有 Bucket。 |
| `IMAGE_GEN_OSS_PREFIX` | `stock-ah-premium-ai/generated-images` | OSS 对象统一业务前缀。 |
| `IMAGE_GEN_OSS_ACCESS_KEY_ID(_FILE)` | 空 | OSS AccessKey ID，文件读取优先。 |
| `IMAGE_GEN_OSS_ACCESS_KEY_SECRET(_FILE)` | 空 | OSS AccessKey Secret，文件读取优先。 |
| `IMAGE_GEN_OSS_SECURITY_TOKEN(_FILE)` | 空 | 可选 STS 临时令牌，文件读取优先。 |
| `IMAGE_GEN_OSS_SIGNED_URL_EXPIRES_SECONDS` | `86400` | 鉴权后返回给前端的 OSS 签名 URL 有效期，默认 1 天。 |

密钥读取规则：

- `Settings.resolve_image_gen_api_key()` 先读 `IMAGE_GEN_API_KEY_FILE`，文件不存在或为空时再读 `IMAGE_GEN_API_KEY`。
- 日志、指标、数据库和前端响应中均不得保存或返回完整 API Key。
- `request_payload_json` 如需审计，只保存 `model`、`prompt`、`size`、`n`，不保存请求头。

## 4. OSS 文件存储方案

生产环境使用阿里 OSS 私有 Bucket 保存生成图和参考图；后端所有列表、详情和旧文件接口都先完成系统用户鉴权，再返回 1 天有效的 OSS 签名 URL。

对象键结构：

```text
stock-ah-premium-ai/generated-images/
  outputs/
    2026/
      05/
        27/
          user-1/
            20260527-153012-<record_id>-<short_hash>.png
  references/
    2026/
      05/
        27/
          user-1/
            20260527-153012-<record_id>-<short_hash>.png
```

保存规则：

- 后端收到外部 API 返回后立即下载 URL 图片或解码 `b64_json`，上传到 OSS 私有 Bucket。
- 数据库保存 OSS object key，例如 `stock-ah-premium-ai/generated-images/outputs/2026/05/27/user-1/xxx.png`，不保存签名 URL。
- 文件名包含记录 ID 和内容 hash 短码，避免用户 prompt 泄露到文件名。
- 普通用户访问图片 URL 前必须校验记录归属；管理员可以访问全部记录。
- 前端拿到的 URL 是 1 天有效的签名 URL，过期后刷新列表或详情即可重新获取。
- `local` 模式仅用于单测或旧环境兜底，继续使用临时文件加原子替换，避免中断时留下半张图片。
- 删除能力首期不做物理删除，只预留 `deleted_at` 字段和后续接口位置。

## 5. 数据模型与迁移

新增 Alembic 迁移，建议版本命名为 `20260527_0039_create_image_generation.py`，实际编号按当前迁移链顺延。

### 5.1 `ai_image_generation`

保存每次文生图请求、状态、文件和审计信息。

关键字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | int | 主键。 |
| `user_id` | int | 创建用户，普通用户所有查询必须按此字段隔离。 |
| `prompt` | text | 用户输入提示词，首期原样保存，便于关闭页面后继续查看。 |
| `model` | varchar(64) | 实际调用模型，默认 `gpt-image-2`。 |
| `size` | varchar(32) | 实际请求尺寸。 |
| `status` | varchar(32) | `PENDING`、`GENERATING`、`READY`、`FAILED`。 |
| `provider` | varchar(64) | 固定 `86gamestore`，便于未来切换供应商。 |
| `mime_type` | varchar(64) | 图片 MIME 类型，例如 `image/png`。 |
| `file_relative_path` | varchar(512) | 输出图片存储对象键，OSS 模式为 Bucket 内 object key。 |
| `file_size_bytes` | int | 文件大小。 |
| `file_sha256` | varchar(64) | 文件内容 hash，便于排查重复文件和损坏。 |
| `external_url_expires_unknown` | bool | URL 返回时标记外链不作为长期存储依据。 |
| `reference_file_relative_path` | varchar(512) | 用户上传参考图的存储对象键，纯文生图为空。 |
| `reference_mime_type` | varchar(64) | 参考图 MIME 类型。 |
| `reference_file_size_bytes` | int | 参考图文件大小。 |
| `reference_file_sha256` | varchar(64) | 参考图内容 hash，用于审计、去重和排查。 |
| `generation_mode` | varchar(32) | `TEXT_TO_IMAGE`、`IMAGE_REFERENCE`，后续可扩展 `IMAGE_EDIT_MASK`。 |
| `request_payload_json` | text/longtext | 脱敏后的请求摘要，不含鉴权头。 |
| `response_summary_json` | text/longtext | 脱敏后的响应摘要，只记录返回类型、数量、错误结构。 |
| `elapsed_ms` | float | 外部生成和下载总耗时。 |
| `error_message` | varchar(512) | 用户侧失败摘要，不保存供应商详细错误、密钥或完整外链敏感参数。 |
| `created_at` / `updated_at` | datetime | 通用时间字段。 |
| `deleted_at` | datetime | 预留逻辑删除。 |

索引：

- `idx_ai_image_generation_user_created`：`user_id, created_at`
- `idx_ai_image_generation_status_created`：`status, created_at`
- `idx_ai_image_generation_file_sha`：`file_sha256`
- `idx_ai_image_generation_reference_sha`：`reference_file_sha256`

### 5.2 `ai_image_generation_error_log`

保存后台任务和供应商调用失败详情，仅管理员可查，普通用户响应不返回该表内容。

关键字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | int | 主键。 |
| `generation_id` | int | 图片生成记录 ID。 |
| `user_id` | int | 图片所属用户。 |
| `provider` | varchar(64) | 供应商标识。 |
| `model` | varchar(64) | 实际调用模型。 |
| `phase` | varchar(64) | 失败阶段，例如 `generate`、`provider_reference`、`store_reference`。 |
| `retry_count` | int | 本次供应商调用已重试次数。 |
| `status_code` | int | 供应商 HTTP 状态码，可为空。 |
| `error_type` | varchar(128) | 异常类型。 |
| `user_message` | varchar(512) | 用户侧失败摘要。 |
| `detail_message` | longtext | 管理员排查用详细错误，服务层截断后写入。 |
| `created_at` / `updated_at` | datetime | 通用时间字段。 |

### 5.3 `ai_image_user_quota`

保存用户每日次数配置和当天已用次数，支持管理员维护或重置。

关键字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | int | 主键。 |
| `user_id` | int | 唯一用户。 |
| `daily_limit` | int | 每日可生成次数，默认 10。 |
| `quota_date` | date | 当前计数对应日期，按 `Asia/Shanghai` 计算。 |
| `used_count` | int | 当日已消耗次数。 |
| `last_reset_at` | datetime | 管理员最近重置时间。 |
| `updated_by_user_id` | int | 最近维护管理员。 |
| `created_at` / `updated_at` | datetime | 通用时间字段。 |

唯一约束：

- `uk_ai_image_user_quota_user`：`user_id`

并发口径：

- 生成前在事务中读取或创建用户 quota 行，并使用 `SELECT ... FOR UPDATE` 锁住该用户 quota。
- 如果 `quota_date` 不是东八区今天，先将 `used_count` 重置为 0，再判断次数。
- 检查通过后先把 `used_count + 1` 并提交，创建 `GENERATING` 记录后立即返回前端，再由后台任务发起外部调用，避免并发请求同时越过限制，也避免用户关闭页面导致任务丢失。
- 外部调用失败时返还本次扣减的次数：服务层在标记 `FAILED` 后重新锁定 quota 行，将 `used_count` 减 1 且不低于 0；如果图片已成功保存到 OSS，则不返还，避免真实消耗供应商额度后被重复生成。

## 6. 后端分层设计

新增文件建议：

```text
backend/app/db/models/image_generation.py
backend/app/schemas/image_generation.py
backend/app/services/image_generation_service.py
backend/app/services/image_generation_client.py
backend/app/api/routes_image_generation.py
backend/tests/test_image_generation_service.py
backend/tests/test_image_generation_routes.py
```

### 6.1 `ImageGenerationClient`

职责：只负责调用 86GameStore 外部接口并规范化响应。

核心方法：

- `generate(prompt: str, size: str, model: str) -> ImageGenerationProviderResult`
- `generate_with_reference(prompt: str, size: str, model: str, reference_image: StoredReferenceImage) -> ImageGenerationProviderResult`
- 对 HTTP 超时、401、400、429、5xx 做清晰错误映射。
- 对明确包含 `input-images per min` 的图片输入限流响应做最多 30 次短重试；若仍失败，详细错误写入 `ai_image_generation_error_log`，普通用户只看到友好失败摘要。
- 兼容 URL 和 `b64_json` 两种返回；URL 由服务层继续下载，Base64 由服务层解码。
- 开发时优先验证 86GameStore 是否兼容 OpenAI `POST /v1/images/edits`：若兼容，则参考图调用走 multipart `image + prompt + model + size`；若不兼容，再通过自定义页面抓包确认其内部上传和生成接口；若两者都不可用，后端返回“当前供应商暂未开放参考图 API”，但保留 OSS 参考图记录和 UI 能力开关。
- 日志只允许输出状态码、模型、尺寸、耗时和错误摘要，不输出 API Key、完整 Authorization 或原始大体积图片内容。

### 6.2 `ImageGenerationService`

职责：处理业务规则、用户隔离、次数扣减、后台任务、OSS 存储、状态更新和错误日志。

核心方法：

- `create_generation(user, payload, reference_file=None)`：校验 prompt、size、参考图和次数，创建 `GENERATING` 记录后立即返回。
- `process_generation(generation_id)`：后台调用供应商、下载或解码输出图、保存到 OSS 并更新为 `READY`/`FAILED`。
- `list_generations(user, filters)`：普通用户只查自己，管理员可按用户、状态、日期、关键词筛选。
- `get_generation(user, generation_id)`：按权限读取详情。
- `image_file_signed_url(user, generation_id)`：校验权限后返回 1 天有效的 OSS 签名 URL。
- `get_or_create_quota(user_id)`：读取用户每日限制。
- `update_user_quota(admin_user, user_id, payload)`：管理员维护每日次数。
- `reset_user_quota(admin_user, user_id)`：管理员把今日已用次数归零。

状态流转：

```text
PENDING -> GENERATING -> READY
PENDING -> GENERATING -> FAILED
```

异常处理：

- 供应商或 OSS 保存失败：记录 `FAILED` 并返还次数，`ai_image_generation.error_message` 只保存用户友好摘要。
- 详细错误：写入 `ai_image_generation_error_log.detail_message`，仅管理员可查看。
- 供应商不支持参考图：记录 `FAILED` 并返还次数；前端提示用户移除参考图后重试。

## 7. 后端 API 设计

新增路由统一挂载到 `/api/image-generation`。

用户接口：

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| `POST` | `/api/image-generation/generations` | `image_generation` | 创建文生图任务；使用 `multipart/form-data` 时可携带参考图，接口立即返回 `GENERATING` 记录，后台继续生成。 |
| `GET` | `/api/image-generation/generations` | `image_generation` | 查询图片列表；普通用户仅自己的记录，管理员可查全部。 |
| `GET` | `/api/image-generation/generations/{id}` | `image_generation` | 查看详情。 |
| `GET` | `/api/image-generation/generations/{id}/file` | `image_generation` | 兼容旧入口；OSS 模式后端鉴权后 307 跳转到 1 天有效签名 URL。 |
| `GET` | `/api/image-generation/quota/me` | `image_generation` | 查看当前用户今日次数、每日上限和剩余次数。 |

管理员接口：

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| `GET` | `/api/image-generation/admin/quotas` | `users` | 在用户管理页查询所有用户文生图次数配置。 |
| `PATCH` | `/api/image-generation/admin/quotas/{user_id}` | `users` | 修改某用户每日上限。 |
| `POST` | `/api/image-generation/admin/quotas/{user_id}/reset` | `users` | 重置某用户今日已用次数。 |
| `GET` | `/api/image-generation/generations/{id}/error-logs` | `users` | 管理员查看单条图片生成的详细失败日志。 |

纯文生图请求示例：

```json
{
  "prompt": "A clean financial dashboard hero illustration, warm sunlight, premium editorial style.",
  "size": "1024x1024"
}
```

带参考图请求使用 `multipart/form-data`：

- `prompt`：文本提示词。
- `size`：输出尺寸，默认 `1024x1024`。
- `reference_image`：可选参考图文件，支持 `png`、`jpg/jpeg`、`webp`，单文件上限建议 10MB。

响应示例：

```json
{
  "id": 12,
  "status": "READY",
  "prompt": "A clean financial dashboard hero illustration, warm sunlight, premium editorial style.",
  "model": "gpt-image-2",
  "size": "1024x1024",
  "image_url": "https://<bucket>.<endpoint>/stock-ah-premium-ai/generated-images/outputs/2026/05/27/user-1/xxx.png?...",
  "quota": {
    "daily_limit": 10,
    "used_count": 3,
    "remaining_count": 7,
    "quota_date": "2026-05-27"
  },
  "created_at": "2026-05-27T15:30:12"
}
```

## 8. 菜单与权限

新增菜单权限码：

- `image_generation`：图片生成。

默认权限：

- 管理员默认拥有 `image_generation`。
- 普通用户默认拥有 `image_generation`，通过每日 10 次限制控制成本。

需要修改的位置：

- `backend/app/services/auth_service.py`
  - `ALL_MENU_PERMISSIONS` 新增 `image_generation: 图片生成`。
  - `DEFAULT_ROLE_PERMISSIONS` 给管理员和普通用户加入 `image_generation`。
- 新增迁移给既有管理员和普通用户补齐权限，或仅给管理员补齐后由管理员手动授权。
- `frontend/src/App.tsx`
  - `PageKey` 新增 `image_generation`。
  - `allMenuItems` 新增菜单项，图标可用 `Image` 或 `Sparkles`。
  - `pages` 映射新增 `ImageGenerationPage`。
  - `MOBILE_PRIMARY_PAGE_KEYS` 建议加入 `image_generation`，顺序放在 `chat` 后面。
- `frontend/src/pages/UserAdminPage.tsx`
  - `menuPermissionOptions` 新增“图片生成”。

## 9. 前端页面设计

新增文件建议：

```text
frontend/src/api/imageGeneration.ts
frontend/src/pages/ImageGenerationPage.tsx
```

页面模块：

- 顶部说明：展示今日剩余次数、默认尺寸和可回看历史图片的产品说明，避免出现服务器、供应商接口等后台技术口径。
- 生成表单：提示词输入、多尺寸选择、提交按钮；提交后提示“已开始生成”，用户离开页面后仍可回到历史图片查看进度。
- 参考图上传：可选上传 1 张参考图，生成前先本地预览；如果后端返回不支持，则提示用户移除参考图后生成。
- 图片预览：生成成功后立即展示图片、prompt、尺寸、生成时间、下载按钮。
- 历史图库：卡片网格展示历史图片；普通用户只展示自己的，管理员可筛选用户、状态、日期和关键词。
- 失败记录：普通用户展示友好失败摘要；管理员可打开错误详情查看日志表里的排查信息。
- 管理员模式：在列表中展示用户列；用户管理页面另有次数维护区。

移动端口径：

- 表单使用单列布局，提示词输入区域高度适中，提交按钮固定在表单底部。
- 历史图库使用 2 列卡片；窄屏低于 420px 时退化为 1 列。
- 图片预览使用 `object-fit: contain`，避免竖图或宽图溢出。
- 生成中状态要明确提示“生成可能需要几十秒到数分钟”，并通过历史列表轮询刷新状态。
- 不使用前端 Base64 长串存储；图片 URL 统一由后端鉴权后返回 OSS 短期签名 URL。

参考图上传口径：

- 页面开放“上传参考图”入口，但后端能力由供应商适配层决定；若 86GameStore 的公开接口不支持，页面给出可理解失败提示并返还次数。
- 参考图保存到 OSS `references/` 对象键下，数据库记录 `reference_file_relative_path`、`reference_mime_type`、`reference_file_sha256`，并在调用前校验文件大小、类型和用户归属。
- 参考图必须走后端鉴权和 OSS 私有存储，不允许前端把图片直接传给第三方接口，也不把参考图公开成无需鉴权的永久 URL。
- 参考图属于用户上传内容，普通用户只能查看和复用自己的参考图；管理员可以审计全部记录，但默认列表不直接展示大图，避免管理页加载过重。

## 10. 用户管理页次数维护

在 `UserAdminPage` 增加“文生图次数”区块，或在用户编辑弹窗中增加字段。首期建议单独区块，避免把菜单权限弹窗变得过长。

展示字段：

- 用户名称、登录名、角色、状态。
- 每日上限。
- 今日已用。
- 今日剩余。
- 计数日期。
- 操作：修改每日上限、重置今日次数。

交互规则：

- 每日上限最小 0，最大建议 100；0 表示当天不可生成。
- 重置只清空当日 `used_count`，不修改历史图片记录。
- 修改或重置成功后刷新用户列表和 quota 列表。
- 管理员对自己也可维护，但页面提示“过低可能导致当前账号无法继续生成”。

## 11. 复用扩展口径

为了后续很多模块复用，首期不要把逻辑写死在页面里，而是沉淀服务层能力。

后续模块可复用的接口：

- `ImageGenerationService.create_generation(...)`：用户主动生成图片。
- `ImageGenerationService.create_system_generation(...)`：预留给后台任务或业务模块生成封面，调用时需要传入业务来源。
- `ai_image_generation` 预留字段可在二期追加 `source_type`、`source_id`、`source_title`，例如 `CHAT_COVER`、`XUEQIU_COVER`、`LIMIT_UP_REPORT_COVER`。

首期不建议立即自动接入其它模块，避免外部接口成本不可控；先通过独立菜单验证稳定性、费用和图片质量。

## 12. 测试与验收

后端单元测试：

- API Key 未配置时返回明确错误，不泄露密钥字段。
- 普通用户创建图片时扣减当日次数。
- 当日次数达到上限后拒绝生成。
- 东八区跨日后自动重置 `used_count`。
- 管理员可查询所有图片，普通用户无法读取他人图片详情和文件。
- URL 返回和 `b64_json` 返回都能保存到 OSS。
- 上传参考图时，后端会先保存参考图、校验文件类型和大小，再调用供应商；供应商不支持时返还次数。
- 外部 401、400、429、5xx、超时均能落库为 `FAILED`，普通用户只看到友好摘要，管理员可查看详细错误日志。
- `input-images per min` 图片输入限流响应最多重试 30 次；重试后仍失败时记录 `retry_count`。
- 管理员修改每日上限、重置今日次数生效。

前端验证：

- `npm run build` 通过。
- 桌面端菜单、生成表单、历史图库和管理员筛选正常。
- 移动端 390px 宽度下表单、图片卡片、底部导航不重叠、不横向溢出。
- 刷新页面或关闭后重新进入，历史图片仍可查看。
- 创建图片后立刻关闭页面，再重新进入时可以在历史列表看到 `GENERATING`、`READY` 或 `FAILED` 状态。
- 普通用户不显示他人图片和管理员筛选项。
- 参考图上传控件在移动端可正常预览、替换和移除，不造成横向溢出。

端到端人工验收：

- 用普通用户生成 1 张 `1024x1024` 图片，确认 OSS 出现图片对象，数据库有 `READY` 记录且接口返回 1 天有效签名 URL。
- 用普通用户上传 1 张参考图并生成；如果供应商接口支持，确认生成记录关联参考图和输出图；如果供应商接口不支持，确认失败提示清晰且次数已返还。
- 连续生成到第 10 次后，第 11 次被拒绝。
- 管理员进入用户管理页把该用户次数重置后，可再次生成。
- 管理员账号能看到所有用户图片；普通用户只能看到自己的图片。

## 13. 分阶段落地清单

第一阶段：后端基础能力。

- 新增配置项和密钥读取方法。
- 新增两张表、SQLAlchemy 模型、Alembic 迁移。
- 新增文生图 client、service、schemas、routes。
- 新增图片文件鉴权读取接口。
- 新增后端单元测试。

第二阶段：前端菜单和图库。

- 新增 `imageGeneration.ts` API 封装。
- 新增 `ImageGenerationPage`。
- 接入 `App.tsx` 菜单、页面映射和移动端主导航。
- 补充全局样式或页面样式，完成移动端适配。

第三阶段：管理员次数维护。

- 后端新增管理员 quota 接口。
- 用户管理页新增文生图次数维护区。
- 补充管理员修改、重置的前端交互和错误提示。

第四阶段：文档、检查与提交。

- 更新 `resources/doc/database-schema.md`。
- 更新 `resources/sql/03_full_schema_with_comments.sql`。
- 更新 `resources/doc/development-progress.md`。
- 执行 `scripts/check.sh`，如涉及真实外部生成调用，先由用户确认是否消耗额度。
- 完成正式代码交付后 commit 并 push。

## 14. 已确认口径与待确认事项

已确认口径：

- 普通用户默认开放“图片生成”菜单，每人每天默认 10 次。
- 外部调用失败返还本次生成次数；图片已成功生成并保存到 OSS 的场景不返还。
- 默认尺寸使用 `1024x1024`，同时支持用户选择所有合法尺寸。
- 首期不做提示词英文优化或自动翻译，避免用户输入和最终图片意图不一致。
- 产品层支持参考图上传；供应商层优先验证 86GameStore 是否兼容 OpenAI `images/edits` 或存在未公开自定义接口，若不可用则给出失败提示并返还次数。

仍需部署前确认：

- 生产环境正式部署需配置阿里 OSS 私有 Bucket、Endpoint、对象前缀和 AccessKey；前端只使用后端鉴权后下发的 1 天有效签名 URL。
