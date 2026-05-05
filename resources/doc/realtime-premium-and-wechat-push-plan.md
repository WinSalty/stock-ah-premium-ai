# 实时 AH 溢价与微信推送实现方案

创建日期：2026-05-04
author: sunshengxian

## 1. 背景与目标

当前项目以 Tushare 官方 AH 比价、A 股/港股日线、外汇日线为主口径，适合做交易日级别的 AH 溢价筛选和投研问答。但如果要在盘中判断“自选股是否触达阈值”，仅靠 Tushare 很难稳定拿到港股和汇率实时数据，因此需要引入独立的实时行情层和消息推送层。

本方案解决两个问题：

1. 盘中实时 AH/H/A 溢价率如何计算，并在行情源不稳定时降级。
2. 实时阈值触发后，如何用个人低门槛方式推送到微信。

## 2. 结论先行

推荐采用“三层行情源 + 一层推送”的轻量方案：

1. **实时行情主源**：优先接入有明确 API 能力的券商或行情服务，用于 A 股、港股实时价和时间戳。
2. **汇率源**：HKD/CNY 优先使用独立外汇报价源；若无法实时获取，允许短时间使用最近可用汇率并在结果中标记 `fx_stale=true`。
3. **Qwen 联网搜索**：只作为“低频补充/人工验证/新闻解释”能力，不作为实时价格主源。
4. **微信推送**：个人轻量使用优先接入 pushplus；后续如要完全自控，再切换企业微信自建应用。

第一阶段建议先做 pushplus + 可插拔行情 provider，不急于把所有数据源一次性做到最完美。

## 3. 实时 AH 溢价计算口径

实时计算仍沿用当前官方 AH 比价主口径：

```text
A/H 比价 = A股价格(CNY) / (H股价格(HKD) * HKD/CNY)
A/H 溢价率 = (A/H 比价 - 1) * 100

H/A 比价 = (H股价格(HKD) * HKD/CNY) / A股价格(CNY)
H/A 溢价率 = (H/A 比价 - 1) * 100
```

实时字段应至少包含：

- `a_last_price`：A 股最新价，币种 CNY。
- `hk_last_price`：H 股最新价，币种 HKD。
- `hkd_cny_rate`：港币兑人民币汇率。
- `a_quote_time`、`hk_quote_time`、`fx_quote_time`：三个来源的报价时间。
- `is_realtime`：是否满足实时口径。
- `quote_quality`：`REALTIME`、`DELAYED`、`STALE_FX`、`PARTIAL`、`UNAVAILABLE`。
- `data_source`：主行情源名称。

建议实时判定规则：

| 场景 | 判定 | 处理 |
| --- | --- | --- |
| A 股、港股、汇率均在有效时间窗内 | `REALTIME` | 可触发提醒 |
| A 股和港股实时，汇率超过有效时间窗但仍是当日数据 | `STALE_FX` | 可展示，提醒中注明汇率滞后 |
| 港股或 A 股任一方延迟 | `DELAYED` | 展示但不触发强提醒 |
| 任一价格缺失 | `PARTIAL` | 不计算阈值触发 |
| 行情源异常 | `UNAVAILABLE` | 使用最近官方日线口径兜底展示 |

## 4. 行情源方案

### 4.1 推荐架构

后端新增统一接口，先抽象再接具体数据源：

```text
RealtimeQuoteProvider
  ├── get_a_quote(ts_code) -> RealtimeQuote
  ├── get_hk_quote(hk_ts_code) -> RealtimeQuote
  └── get_fx_rate(pair="HKD/CNY") -> RealtimeFxRate
```

服务层新增：

- `RealtimeMarketDataService`：负责调用 provider、缓存报价、标准化币种和时间戳。
- `RealtimePremiumService`：负责用标准化报价计算实时 AH/H/A 溢价。
- `RealtimeAlertService`：负责判断是否触发阈值、去重、冷却和推送。

不要让页面、LLM 或提醒逻辑直接依赖某个第三方 API 返回结构。

### 4.2 数据源分层

| 层级 | 用途 | 优点 | 风险 |
| --- | --- | --- | --- |
| 券商/正规行情 API | 主行情源 | 相对稳定、时间戳清晰、可追责 | 可能需要开户、订阅或额度 |
| 公开网页/非正式接口 | 个人实验兜底 | 低门槛、成本低 | 易失效，合规和稳定性弱 |
| Qwen 联网搜索 | 解释、查源、人工验证 | 能快速找公开资料和来源 | 不适合做实时数值主源 |

**建议**：工程上先支持 `provider=mock/http` 两类配置，后续把券商 API、公开接口或手工 HTTP 源都接入同一个 provider 协议。

### 4.3 低价或免费行情源候选

按“个人低门槛、能覆盖 A 股 + 港股 + 汇率、适合阈值提醒”的目标，当前可考虑这些来源。

| 来源 | 覆盖 | 成本线索 | 适合程度 | 备注 |
| --- | --- | --- | --- | --- |
| 富途 OpenAPI | 港股、美股、A 股等 | OpenAPI 本身可用，但行情权限和 App 权限不完全共享；未开户或总资产较低也有订阅额度 | 高，若已有富途账户 | 适合做主源；需要本机运行 OpenD，且确认港股/A 股权限和延迟等级 |
| 老虎 Tiger OpenAPI | 港股、美股等，SDK 文档列出实时行情和 WebSocket 推送 | 开户并入金后 OpenAPI 可免费使用 | 高，若已有老虎账户 | 适合主源；需确认 A 股/港股通对应标的权限和所在地区账户能力 |
| Longbridge OpenAPI | 文档称实时报价 API 支持证券；可混查美股、港股等 | 基础行情权可能赠送，高级行情需在 Quote Store 购买行情卡 | 中高，若已有长桥账户 | OpenAPI 行情权限与 App/PC/Web 不共享；需确认港股 LV1 权限成本 |
| QOS | A 股、港股、外汇、WebSocket、实时快照 | 免费档 3 只交易产品、每分钟 5 次；100 只自由组合约 88 USDT/月起 | 高，适合先试点 | 最贴合“少量自选 + 实时提醒”；如果只盯 1-2 对 AH + HKD/CNY，可先用免费档验证 |
| iTick | 港股、美股、热门 A 股、外汇等 | 免费档 5 calls/min、1 个 WebSocket、3 个订阅；个人 Basic 约 79 美元/月 | 中高 | 覆盖面好，但免费档只够很少标的；付费后适合中等自选池 |
| TickDB | A 股、港股、美股、外汇、加密等 | 页面说明有免费有限额，付费解锁全部；未在首页展示明确价格 | 中 | 适合作备选统一行情 API，需要进一步试用确认 A/H 标的和 HKD/CNY |
| AllTick | 港股、中国 A 股、外汇等 | 提供 Start Free Usage；公开页未展示清晰价格 | 中 | 技术上覆盖 AH + FX，但需要试用确认免费额度和稳定性 |
| 必盈 API | 沪深 A 股、港股实时行情、港股通等 | 免费版每日 200 次，包年约 688 元，三年约 1088 元 | 中 | 成本低，但网站声明不保证准确性、及时性等；适合低频校验或备源 |
| AKShare | A 股实时聚合、港股聚合等 | 开源免费 | 低到中 | 适合实验和兜底；港股接口文档标注 15 分钟延时，不适合强实时触发 |
| fxapi.app | HKD/CNY 可通过外汇交叉汇率计算 | 免费、免认证，约 5 分钟更新 | 高，适合汇率源 | 汇率可单独使用；若行情源自带 HKD/CNY，也可与其互校 |

推荐优先级：

1. **已有券商账户优先**：如果本机已有富途、老虎或长桥账户，并能接受本机常驻网关/SDK，优先用券商 OpenAPI 做主源。真实报价、权限边界和合规性会比网页聚合更清楚。
2. **无券商账户先试 QOS 免费档**：先选 1-2 对最关注 AH 标的，加 `HKD/CNY` 汇率，跑通实时溢价和 pushplus 提醒闭环。如果自选池扩大，再考虑 88 USDT/月的 100 只组合档。
3. **汇率独立走 fxapi.app**：即使股票行情来自券商或 QOS，也建议保留独立汇率 provider，做交叉校验和故障兜底。
4. **AKShare 只做实验兜底**：A 股可用于低门槛试跑，港股延迟口径不适合作“实时触达阈值”强提醒。
5. **TickDB、AllTick、iTick 做备选统一源**：如果希望一个服务覆盖 A/H/FX，并愿意接受美元月费或试用额度，可进入第二轮 PoC。

实现上建议新增这些 provider key：

```text
REALTIME_PROVIDER=qos
REALTIME_PROVIDER_FALLBACK=fxapi,akshare
REALTIME_SYMBOL_LIMIT=20
REALTIME_REFRESH_SECONDS=60
REALTIME_REQUIRE_REALTIME_FOR_ALERT=true
```

并在 `realtime_quote_snapshot.source` 中记录具体来源，例如 `FUTU_OPENAPI`、`QOS`、`ITICK`、`AKSHARE`、`FXAPI`。

### 4.4 合规与许可边界

港交所实时行情存在明确的数据许可和非展示使用边界。若系统用港股实时行情自动计算派生指标、触发提醒或未来辅助交易，就已经不只是“人工看盘”。个人本地自用通常风险较低，但仍应避免：

- 对外提供实时行情看板。
- 转发第三方原始报价给多人使用。
- 把延迟或 Basic Market Prices 伪装成实时行情。
- 用未授权网页接口做商业化或高频抓取。

本项目应在数据质量字段中明确标注 `REALTIME`、`DELAYED`、`STALE_FX`，提醒内容也带上行情来源和报价时间。

### 4.5 Qwen 联网搜索的定位

阿里云百炼文档显示，OpenAI 兼容 Chat Completions 可通过 `enable_search: true` 启用联网搜索；可通过 `search_options.search_strategy` 选择 `turbo`、`max`、`agent` 等策略，也可配置 `forced_search` 强制搜索、`freshness` 限定新近内容、`assigned_site_list` 限定来源站点。文档也说明联网搜索适用于股票价格、天气等实时问题，但这是“模型检索并生成回答”，不是可审计的行情数据 API。

因此本项目中 Qwen 搜索适合：

- 问答页回答“为什么今天 AH 溢价异动”时补充新闻和公告。
- 当行情源异常时，给管理员生成“排障建议和可能的数据源变动说明”。
- 低频手工验证某只港股报价或汇率页面是否能检索到。

不建议：

- 每分钟批量抓取自选股价格。
- 把模型回答中的价格直接写入实时行情表。
- 用自然语言搜索结果触发交易提醒。

若后续接入 Qwen 联网搜索，建议只在 LLM 服务新增可选参数：

```json
{
  "enable_search": true,
  "search_options": {
    "search_strategy": "turbo",
    "forced_search": true,
    "freshness": 1,
    "enable_source": true
  }
}
```

对投资问答可开启来源回传；对阈值判断仍只使用结构化行情 provider。

## 5. 数据库与 API 设计

### 5.1 新增实时行情快照表

建议新增 `realtime_quote_snapshot`：

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `market` | `A`、`HK`、`FX` |
| `symbol` | 标准代码，如 `600036.SH`、`03968.HK`、`HKD/CNY` |
| `last_price` | 最新价或汇率 |
| `currency` | `CNY`、`HKD` |
| `quote_time` | 第三方报价时间 |
| `source` | 数据源 |
| `quality` | `REALTIME`、`DELAYED`、`STALE`、`ERROR` |
| `raw_payload_json` | 原始响应摘要，不存敏感字段 |
| `created_at` | 入库时间 |

### 5.2 新增实时溢价快照表

建议新增 `realtime_ah_premium_snapshot`：

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `a_ts_code` | A 股代码 |
| `hk_ts_code` | H 股代码 |
| `a_last_price` | A 股最新价 |
| `hk_last_price` | H 股最新价 |
| `hkd_cny_rate` | HKD/CNY |
| `ah_ratio` | A/H 比价 |
| `ah_premium_pct` | A/H 溢价率 |
| `ha_ratio` | H/A 比价 |
| `ha_premium_pct` | H/A 溢价率 |
| `quote_quality` | 综合质量 |
| `source` | 主来源 |
| `calculated_at` | 计算时间 |

### 5.3 新增提醒记录表

建议新增 `alert_event`：

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `user_id` | 用户 |
| `watchlist_id` | 自选项 |
| `event_type` | `THRESHOLD_REACHED`、`NEAR_THRESHOLD`、`DATA_RECOVERED` |
| `metric_direction` | `AH` 或 `HA` |
| `metric_premium_pct` | 触发时观察溢价 |
| `target_premium_pct` | 用户阈值 |
| `message_title` | 推送标题 |
| `message_content` | 推送内容 |
| `push_channel` | `PUSHPLUS`、`WECHAT_WORK` |
| `push_status` | `PENDING`、`SENT`、`FAILED`、`SKIPPED` |
| `dedupe_key` | 去重键 |
| `created_at` | 创建时间 |
| `sent_at` | 发送时间 |

## 6. 定时与缓存策略

个人轻量使用不建议做高频 tick 级轮询。建议：

- A 股和港股交易时段内，每 30-60 秒刷新一次自选股实时报价。
- 仅刷新用户自选股，不扫全市场。
- HKD/CNY 每 1-5 分钟刷新一次；汇率变化通常慢于股价，允许更长缓存。
- 同一 `watchlist_id + direction + target + trading_day` 触发后设置冷却，例如 30 分钟或价格重新回落后再触发。
- 非交易时段不轮询，只保留手动刷新。

提醒触发规则：

```text
用户关注方向为 AH：
  metric_premium_pct = ah_premium_pct

用户关注方向为 HA：
  metric_premium_pct = ha_premium_pct

触发：
  preferred_direction == AH 且 ah_premium_pct >= target_premium_pct
  preferred_direction == HA 且 ha_premium_pct >= target_premium_pct
```

如果当前项目已有 `distance_to_target_pct`，实时层可以沿用该字段，避免前端认知分裂。

## 7. 微信推送方案

### 7.1 推荐：pushplus

pushplus 对个人最轻量：

- 关注公众号后获取 token。
- 后端 POST `https://www.pushplus.plus/send`。
- 参数包括 `token`、`title`、`content`、`template`、`channel` 等。
- 支持 `markdown`、`html`、`json` 模板；也可通过 `topic` 做一对多。

本项目建议新增配置：

```text
PUSHPLUS_ENABLED=true
PUSHPLUS_TOKEN_FILE=/Users/salty/codeProject/ai/doc/pushplus.txt
PUSHPLUS_SECRET_KEY_FILE=/Users/salty/codeProject/ai/doc/pushplus.txt
PUSHPLUS_TOKEN=
PUSHPLUS_SECRET_KEY=
PUSHPLUS_TEMPLATE=markdown
PUSHPLUS_CHANNEL=wechat
ALERT_COOLDOWN_MINUTES=30
```

当前实现采用好友消息方案：

- 个人信息页通过 PushPlus 开放接口 `getQrCode` 生成个人二维码，用户扫码后成为 PushPlus 好友。
- 后端通过开放接口 `friend/list` 拉取好友列表，用户在个人信息页选择自己的好友完成绑定。
- 真实推送仍调用 `/send`，使用 `to` 字段填写好友令牌；好友令牌仅存后端，不返回前端明文。
- `/Users/salty/codeProject/ai/doc/pushplus.txt` 可同时保存用户 token 和 SecretKey，支持 `PUSHPLUS_TOKEN=...` / `PUSHPLUS_SECRET_KEY=...` 或前两行分别写 token、SecretKey。
- 阈值提醒和股价提醒只在对应市场交易日发送；同一个提醒按 `用户 + 自选股 + 条件 + 交易日` 去重，每天最多推送一次。

推送内容建议：

```markdown
# AH 阈值触发

招商银行 A/H 溢价达到 42.3%

- A 股：600036.SH，38.21 CNY
- H 股：03968.HK，32.10 HKD
- HKD/CNY：0.9142
- 方向：AH
- 目标阈值：40.0%
- 行情质量：REALTIME
- 时间：2026-05-04 14:32:10
```

优点：最快落地、无需企业微信后台、适合个人。

缺点：依赖第三方平台，有额度和可用性限制；生产化前要做失败重试和降级。

### 7.2 备选：企业微信自建应用

企业微信自建应用更自控，但配置更重：

1. 创建企业微信或个人企业。
2. 创建自建应用，拿到 `corpid`、`corpsecret`、`agentid`。
3. 调用 `gettoken` 获取 `access_token`。
4. POST `/cgi-bin/message/send?access_token=ACCESS_TOKEN` 发送文本、图文等应用消息。

适合后续需要更强自控、多人接收、企业内部使用的阶段。

配置建议：

```text
WECHAT_WORK_ENABLED=false
WECHAT_WORK_CORP_ID_FILE=/Users/salty/codeProject/ai/doc/wechat-work-corp-id.txt
WECHAT_WORK_SECRET_FILE=/Users/salty/codeProject/ai/doc/wechat-work-secret.txt
WECHAT_WORK_AGENT_ID=
WECHAT_WORK_TO_USER=@all
```

### 7.3 不推荐：个人公众号模板消息

个人低门槛场景不建议走公众号模板消息。公众号主动模板消息通常需要服务号、认证、模板权限和更完整的微信生态配置，远比 pushplus 重。

## 8. 后端实现拆分

建议分 4 个小迭代。

### 迭代 1：推送能力打底

新增：

- `NotificationService`
- `PushplusClient`
- `POST /api/settings/test-push`
- `alert_event` 表

验收：

- 能从本机 token 文件读取 pushplus token。
- 管理员点击测试推送，微信收到一条消息。
- token 不进入前端响应和日志。

### 迭代 2：实时行情 provider 抽象

新增：

- `RealtimeQuoteProvider` 协议。
- `HttpRealtimeQuoteProvider` 示例实现。
- `RealtimeMarketDataService`。
- `realtime_quote_snapshot` 表。

验收：

- 对单个 A/H 配对返回标准化报价。
- 任一数据缺失时返回明确 `quote_quality`。

### 迭代 3：实时溢价计算与页面展示

新增：

- `RealtimePremiumService`
- `GET /api/ah-premiums/realtime`
- `realtime_ah_premium_snapshot` 表

前端：

- AH 机会筛选页增加“实时/官方日线”切换。
- 实时数据展示报价时间和质量标签。
- `STALE_FX`、`DELAYED` 状态不伪装成完全实时。

### 迭代 4：阈值触发与推送

新增：

- 交易时段定时任务。
- 自选股阈值扫描。
- 冷却去重。
- 推送失败重试。

验收：

- 阈值触发只推一次，不刷屏。
- 行情恢复、行情异常、触达阈值三类事件可区分。
- 推送内容包含价格、汇率、阈值、质量和时间。

## 9. 风险与控制

| 风险 | 控制 |
| --- | --- |
| 免费或非正式行情源失效 | provider 可插拔，失败降级为官方日线 |
| 数据延迟被误认为实时 | 强制展示 `quote_quality` 和时间戳 |
| 汇率不实时导致误差 | `fx_stale` 标记，汇率过期则不强提醒 |
| 推送刷屏 | `dedupe_key` + 冷却时间 + 交易日限制 |
| token 泄露 | 仅本机文件读取，不进入日志和前端 |
| LLM 搜索结果不可复核 | LLM 不写行情表，不触发阈值 |

## 10. 推荐落地顺序

1. 先做 pushplus 测试推送，立刻验证个人微信通知链路。
2. 加 `RealtimeQuoteProvider` 抽象和 mock provider，用假数据跑通实时溢价、阈值和推送闭环。
3. 用 QOS 免费档或已有券商 OpenAPI 接入 1-2 对 AH 标的，只服务自选股。
4. 独立接入 `fxapi.app` 汇率源，并与行情源自带汇率互校。
5. 加页面实时标签和手动刷新。
6. 自选池扩大后，再评估 QOS 100 只组合档、iTick Basic、TickDB 或 AllTick。
7. 最后再把 Qwen 联网搜索接到问答页，用于解释异动和排查数据源，不参与阈值计算。

## 11. 参考资料

- 阿里云百炼联网搜索文档：`https://help.aliyun.com/zh/model-studio/web-search`
- 富途 OpenAPI 权限与额度：`https://openapi.futunn.com/futu-api-doc/intro/authority.html`
- Longbridge 实时报价 API：`https://open.longbridge.com/docs/quote/pull/quote`
- Longbridge 行情权限说明：`https://open.longbridge.com/docs/qa/broker`
- Tiger OpenAPI Python SDK：`https://pypi.org/project/tigeropen/`
- QOS 行情 API：`https://qos.hk/`
- iTick 行情 API：`https://itick.io/en`
- TickDB 实时行情 API：`https://tickdb.ai/`
- AllTick 股票 API：`https://api.alltick.co/stock-api`
- 必盈 API：`https://www.biyingapi.com/`
- AKShare 股票数据文档：`https://akshare.akfamily.xyz/data/stock/stock.html`
- fxapi.app 汇率 API：`https://fxapi.app/`
- HKEX 市场数据许可说明：`https://www.hkex.com.hk/Services/Market-Data-Services/Real-Time-Data-Services/Data-Licensing/HKEX-IS-%28China%29/Market-Data-Vendor-Licence/Licence-Agreements_Guiding-Notes/Licence-Agreement?sc_lang=zh-HK`
- pushplus 消息接口文档：`https://h5.pushplus.plus/doc/guide/api.html`
- pushplus GitHub 介绍：`https://github.com/pushplus/pushplus`
- 企业微信发送应用消息 API：`https://s.apifox.cn/apidoc/docs-site/406014/api-10061693`
