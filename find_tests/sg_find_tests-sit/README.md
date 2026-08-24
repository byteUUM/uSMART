# 最大可买可卖接口优化 —— 测试脚本（SIT）

对应测试文档：`../explain.md`

## 目录结构

```
sg_find_tests-sit/
├── common/
│   ├── config.py    环境/账号/标的/接口路径/错误码/Redis&MQ 信息
│   ├── client.py    请求发送、基线对比、断言、并发与耗时工具
│   ├── cache.py     Redis 缓存辅助（3.5/3.6 用）
│   └── mq.py        RabbitMQ 辅助（RFS-02 用）
├── test_3_1_combo_option_power.py   3.1 组合期权购买力      CBO-01~09
├── test_3_2_stock_short_max.py      3.2 股票沽空最大可买可卖 SHT-01~06
├── test_3_3_stock_max.py            3.3 股票最大可买可卖     STK-01~07
├── test_3_4_option_short_max.py     3.4 期权沽空最大可卖     OPS-01~09
├── test_3_5_user_info_cache.py      3.5 用户信息缓存         CACHE-01~08
├── test_3_6_cache_refresh.py        3.6 缓存失效/刷新触发    RFS-01~06
├── test_3_7_combo_quote.py          3.7 组合腿行情批量查询   QUO-01~05
├── test_3_8_order_preview.py        3.8 下单预览             PRV-01~02
├── test_4_regression.py             4.  回归重点             REG-01~05
├── test_5_performance.py            5.  性能验证             PERF-01~04
├── test_6_context.py                6.  并发与上下文透传     CTX-01~03
├── baseline/                        取数一致性基线（自动生成）
└── requirements.txt
```

## 使用方式

```powershell
pip install -r requirements.txt

python test_3_3_stock_max.py
python -c "import test_3_3_stock_max as t; t.stk_replace_max()"
```

---

## 一、接口路径（实测）

### 路径规则

1. 接口文档（png）写的是 `/order-center-sg/api/...` —— 这是 **APP 网关**路由，在 `usmartclient-sit` 上**全部 404**。
2. 本机可用的是**中台**路由 `/order-center-sg/admin-api/...`，且**不带 `order/` 这一段**：

```
文档  /order-center-sg/api/order/stock-order-replace-max/v1
中台  /order-center-sg/admin-api/stock-order-replace-max/v1     <- 少了 order/
```

### ★ 最大的坑：`110003` 不是权限问题

路径写错时网关**不返回 404**，而是返回：

```json
{"code":110003,"msg":"您无权限,请申请"}
```

已用一个完全不存在的路径 `admin-api/this-path-does-not-exist-xyz/v1` 验证 —— 返回的也是 110003。

> **`110003` 的真实含义是「路径未匹配」**。看到它请先核对 URL，**不要**当成权限问题去申请权限。
> 建议向后端提一条改进：这个码应该返回 404。

### 已实测可用（4 个）

| 接口 | 路径（`admin-api/` 下） |
| --- | --- |
| 股票改单最大可改 | `stock-order-replace-max/v1` |
| 股票沽空改单最大可改 | `short-order-replace-max/v1` |
| 期权沽空最大可卖 | `short-option-sell-max/v1` |
| 期权沽空改单最大可卖 | `short-option-replace-sell-max/v1` |

### 路径待后端确认（3 个）

去掉 `order/` 后仍返回 110003，已试 19 个命名变体均不通：

| 接口 | 文档路径 | 影响章节 |
| --- | --- | --- |
| 计算消耗购买力 | `/api/calculate-consumed-purchasing-power/v1` | 3.1、3.3、3.7、3.8 |
| 订单最大可买可卖聚合 | `/api/order/order-replace-max/v2` | 3.1、3.3 |
| 股票沽空最大可买可卖 | `/api/order/short-order-max-qty-get/v1` | 3.2 |

拿到路径后填入 `config.PATHS` 对应 key 即可，其余代码不用改。

---

## 二、★ 改单接口不读 `fundAccount`（影响测试方法）

实测把 `fundAccount` 换成 4 个完全不同的账号（`10002178` / `80125438` / `80009415` / `90000037`），
`stock-order-replace-max/v1` 返回的 `cashBalance`、`maxBuyQty` **一模一样**。

> 说明账号是由 **`orderId` + token** 推出来的，body 里的 `fundAccount` 被忽略。

**测试含义（很重要）**：想验证不同账户类型（CASH / MARGIN / pro / 冻结），
**必须用该账号自己的 token + 该账号自己的订单 ID**。只改 `fundAccount` 是无效的，
会得到一个**假的"通过"**。直接影响这几个用例的做法：

- RFS-01（现金升融资）
- RFS-06（账户降级）
- CBO-08（冻结账户查询）
- REG-01（冻结账户真实下单）

另外：token 与 `fundAccount` 不属于同一用户时，会返回 `110002 登录状态已失效, 请重新登录` ——
这**不一定是 token 过期**，先确认账号与 token 是否匹配。

---

## 三、实测响应字段名（原先猜的一半是错的）

`stock-order-replace-max/v1` / `short-order-replace-max/v1` 的真实 `data` 字段：

```
maxBuyQty  maxSellQty  maxPurchasePower  maxCashBuyQty  maxCashBuyMulti
cashBalance  businessQty  entrustQty  modifiedLowerAmount  modifiedUpperAmount  shortRate
```

**响应里不存在的字段**（原先按文档场景推测的，需与开发确认验证点改怎么判断）：

| 字段 | 原本想验证 | 受影响用例 |
| --- | --- | --- |
| `availableTag` | 可沽空标识 | SHT-02 |
| `maxAvailable` | 可沽空上限 | SHT-03 |
| `estimateMargin` | 预计保证金 | SHT-01 |
| `fee` / `otc` / `stampDuty` | OTC / 印花税费用 | STK-03、STK-04 |

注意 `purchasePower` 实际叫 **`maxPurchasePower`**。

期权沽空接口（`short-option-sell-max/v1`）的字段名**仍未验证** ——
手上所有账号都没有 `OPTION_SHORT` 权限，全部返回 400505，拿不到成功响应。

---

## 四、实测错误码（与 explain.md 的英文枚举名不同）

服务端返回**数字 code + 中文文案**，不是 `FUND_ACCOUNT_INFO_NONE` 这类枚举名。
断言请用 `expect_code()` 配合 `config.ERROR_CODES`：

| explain.md 枚举名 | 实测 code | 实测文案 |
| --- | --- | --- |
| NO_CORRESPONDING_TRADE_PERMISSION | **400505** | 无对应交易权限 |
| OPTION_FUND_ACCOUNT_ERROR | **400092** | 资金账号不正确！ |
| FUND_ACCOUNT_INFO_NONE | **450004** | 获取用户信息异常 |
| BASE_CAPITAL_FUNDACCOUNT_ERROR | （无 code） | 资金帐号不能为空 |
| —（路径未匹配，**非权限**） | **110003** | 您无权限,请申请 |
| —（账号与 token 不匹配） | **110002** | 登录状态已失效, 请重新登录 |
| —（参数校验） | **450003** | xxx不能为空 |

**OPS-03 已验证通过**：`explain.md` 第 7 节提到的错误码变更是**真实生效**的 ——
`10002178`(CASH) / `80125438`(MARGIN) / `80125375` 查期权沽空最大可卖均返回
`400505 无对应交易权限`。前端/监控若按旧码 `OPTION_NO_OPTION_PRIVILEGE` 判断，需同步改造。

---

## 五、待后端/环境确认清单

### 需要后端给的

| # | 内容 | 影响 |
| --- | --- | --- |
| 1 | 上面 3 个接口在中台的**准确路径**；若中台没有则给 **APP 网关 SIT 地址** | 3.1/3.2/3.3/3.7/3.8 |
| 2 | 用户信息缓存 **key 前缀**、资金账号→客户号**映射 key**、**锁 key** 名 | 3.5、3.6 全部 |
| 3 | **刷新用户信息缓存**内部接口路径 | RFS-03 |
| 4 | **现金升融资**接口路径（或确认走后台手工操作） | RFS-01 |
| 5 | **组合下单预览**接口路径 | 3.8 |
| 6 | MQ 的 exchange / routing key / 开户消息体结构 | RFS-02 |
| 7 | RFS-05（新增交易权限）、RFS-06（账户降级）这两条链路**是否接了缓存刷新** | 两个 P0 |
| 8 | `availableTag` / `maxAvailable` / 费用字段 从哪里判断 | SHT-02/03、STK-03/04 |

### 需要测试数据

| # | 内容 | 当前状态 |
| --- | --- | --- |
| 9 | 真实期权代码 + 组合各腿 | `UTL260918C50000` 等是**编的** |
| 10 | `comboStrategy` 枚举值 | `VERTICAL`/`STRADDLE` 是**猜的** |
| 11 | 美股 OTC 标的、`availableTag=2` 不可沽空标的 | 编的 |
| 12 | 各账户类型自己的 **token + 在途订单 ID**（见第二节） | 只有 `80125375` 可用 |
| 13 | 一个有 `OPTION_SHORT` 权限的账号 | 手上 4 个都没有 |
| 14 | 沽空 / 期权沽空 / 组合 的在途订单 ID | 只有股票的 `1605376494721105920` |

### 流程性前提

| # | 内容 | 说明 |
| --- | --- | --- |
| 15 | **一套「优化前」（master）环境** | `explain.md` 把取数一致性列为第一优先，但需要基线才能比对。**有时间窗口**——旧环境一旦被覆盖就补不回来 |
| 16 | Redis(`10.60.6.x`) / MQ(`10.60.6.x`) 内网连通 | 3.5、3.6 需要 |

---

## 六、取数一致性怎么跑

```powershell
# 1) 在优化前版本(master)环境存基线
python -c "import test_3_3_stock_max as t; from common.client import save_baseline; save_baseline('STK-replace', t.stk_replace_max())"

# 2) 在优化后环境重跑，会自动逐字段比对并打印差异
python -c "import test_3_3_stock_max as t; t.stk_replace_max()"
```

拿不到 master 环境时，退化方案是"多次调用自身一致"，已实现在
`SHT-06`、`STK-07`、`OPS-09`、`CBO-09` 里（覆盖度弱于真基线比对）。

---

## 注意

- `test_4_regression.py` 会**真实下单/改单/撤单**，仅在 SIT/UAT 执行。
- `test_3_5` / `test_3_6` 会**直接改动 Redis 数据**（删 key、改 TTL、写测试值），仅在 SIT/UAT 执行。
- `common/config.py` 里存了 SIT 的登录 token，**不要提交到公共仓库**。
