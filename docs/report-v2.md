# Financial Visualizer V2：单公司报告

公开版提供股票代码到单公司 HTML 的 V2 流程，不附带历史公司数据或缓存，也不需要预先登记公司。范围为 US GAAP 美股非金融公司，最多五个完整财年；季度、金融行业、IFRS、估值和交易不在当前范围。
## 使用

在克隆的项目根目录，使用 Python 3.10+（无需 pip 依赖）：

```bash
python3 scripts/report.py prepare --symbol COST
```

输出 JSON 包含工作目录和各文件路径。默认目录在 `.local/v2/workspaces/`，缓存位于 `.local/v2/cache/`。公司身份来自 SEC ticker 目录，并与 submissions 及 Company Facts 的 CIK 核对；依据最新年度 US GAAP 标签及资产、收入、CFO 的相同货币单位确定报告币种。SIC 6000–6999（含金融与地产行业）明确拒绝，未知行业不猜测。目录/申报中的公司名称分别保留，以 CIK 和股票代码核验身份。

从 recent 和必要的历史 submissions 文件取得最多六个年度截止日。年度收入和 CFO 的真实起止日必须相同，并为 350–380 天，支持 52/53 周；原年度 accession 的 FY 标签决定财年，不用比较期事实的 `fy` 推断年份。少于五年就显示实际可用年份。不能核定的期间、过渡年报及断档停止，不能退到旧五年窗口而隐藏最近期间。

默认保留首次获取版本的 SEC 数据。需要更新时：

```bash
python3 scripts/report.py prepare --symbol COST --refresh
```

可用 `--data-root <目录>`、`--workspace <新目录>` 改路径。SEC 要求声明 user agent；建议使用 `SEC_USER_AGENT` 或 `--user-agent '机构名 联系邮箱'`。`--offline` 仅使用经核验的 V2 缓存，不能与 `--refresh` 同用。`--skip-filings` 延后年度 HTML 获取，并不表示不需要原文研究。

缓存按 URL、内容 SHA256 保存响应、获取时间和版本；只有成功且格式有效的响应才更新 latest 指针。刷新失败且有完整缓存时使用旧版本，并在工作清单和报告中显示准确版本及获取时间。损坏缓存在离线模式报错，联网时可重新获取。资料截止时间不晚于核心资料的实际获取日期；本次准备时间单独保存，不把重用旧缓存说成今日更新。

## 首次使用与常见诊断

首次使用可按 [README 的固定工作目录示例](../README.md#手动执行流程) 操作；在 AI 环境中使用见 [Skill 指南](skill-usage.md)。真实公司工作目录和新 HTML 被 Git 忽略，不作为克隆后的默认输入。需要新资料时重新 prepare，而不是从文档中的验收日期推断当前最新数据。

`prepare` 默认复用已有有效缓存，只有 `--refresh` 才主动更新，不能把每次 prepare 都理解为重新获取最新披露。它会输出研究清单但不会自动调用模型；`supplements.json` 为空时仍可构建有明确缺口的部分报告。

| 错误代码 | 处理方向 |
| --- | --- |
| `identity_ambiguous` | 股票代码未唯一对应 SEC 发行人，核对代码和身份，不借用另一家公司 |
| `industry_unsupported` / `accounting_unsupported` | 当前行业或会计准则不支持，不能强行按 US GAAP 非金融公司生成 |
| `currency_unknown` / `period_ambiguous` / `fiscal_year_unknown` | 缺少唯一币种或完整财年依据，查原披露和来源版本 |
| `fetch_failed` | 联网获取失败且无可用缓存，检查网络、SEC 响应及 user agent 后重新 prepare |
| `cache_missing` / `cache_invalid` | 离线缓存不存在或损坏；需要在可联网时取得有效版本 |
| `workspace_exists` | 选择新的工作目录；prepare 没有 --overwrite 参数 |
| `workspace_invalid` | 原始文件、身份或标准化事实与已保存版本不符，不手改 normalized.json 绕过检查 |
| `supplement_invalid` | 根据具体诊断核对出处、原值/倍率、范围、重复行或版本冲突，修正有证据的输入 |
| `output_exists` | 改输出路径；确实要替换报告时才给 build 加 --overwrite |

完整开发验证见 [开发指南](development.md)，许可证及第三方历史资料的发布范围见 [公开评估](release.md)。

## Skill 的研究步骤

1. 读 `research-tasks.json`、`normalized.json` 和 `checks.json`。`normalized.json` 为固定映射结果，不手工修改。
2. 按缺口读 `sources/` 的官方 HTML 及 `filing-facts.json` 的 inline XBRL 候选；后者保留实体、期间、维度、单位、倍率和变换，不为自定义标签猜测语义。不支持的数字变换保留未知。必要时到官方 IR 或年报附注补充；HTML 不可读时再用 PDF 或用户资料。
3. 将原文观察写入 `supplements.json`，契约见下文。金额、倍率、事实身份和科目映射需要出处；AI 不编写运行时代码或图形坐标。
4. 执行构建，复核 `checks.json` 和报告：

```bash
python3 scripts/report.py build --workspace <工作目录>
# 或者
python3 scripts/report.py build --workspace <工作目录> --output reports/COST-research.html
```

默认输出项目内 `reports/<代码>.html`。已有输出会报 `output_exists`；只有明确要替换时使用 `--overwrite`。覆盖先完整构建，再原子替换；输入不合法时原报告保留。构建阶段无联网路径，重新核验原始资料哈希、身份、期间、币种和标准化结果；工作目录可复制到另一台机器，不依赖原目录或连接服务。

输出每次只有一家公司，没有公司切换，保留年份、播放、金额/比例、来源及六类分析交互；CSS、脚本与该公司报告内嵌，无运行时网络请求。页面可展开资料版本、财年、缺口与研究说明。来源链接只有用户点击才访问外网。

## 补充资料契约

空模板由 prepare 创建：

```json
{
  "version": "financial-visualizer-v2.1",
  "sources": [],
  "facts": [],
  "business": [],
  "reconciliations": [],
  "notes": []
}
```

以下 JSON 仅说明输入形状，发行人、期间和金额均为合成示例，不能当作实际披露。sources 引用本次已保存年报，真实运行时须替换为实际身份和版本：

```json
{
  "id": "annual",
  "preparedSource": "filing-0000123456-26-000001",
  "cik": "0000123456",
  "currency": "USD",
  "publishedAt": "2026-05-01"
}
```

`preparedSource` 取 `workspace.json.sources[].name`，沿用已保存的 URL、文件、SHA256 和获取时间，不能改写。新取得的官方资料需填写 `id,url,file,sha256,cik,currency,publishedAt,retrievedAt`，文件必须在工作目录内。SEC 年报 URL 必须指向相同 CIK；IR 域名须来自 issuer 的官方网站或由 `officialLinkSource` 指向本次已保存 SEC 年报中的真实链接。PDF 可额外引用 `textFile,textSha256` 保存提取或人工转录文字，来源原件仍保留；文字提取与财务含义由 Skill 审阅，格式校验不会证明转录真实性。

一个分部或主营观察的例子：

```json
{
  "id": "products-2026",
  "year": 2026,
  "key": "business_revenue",
  "name": "产品收入",
  "start": "2025-04-01",
  "end": "2026-03-31",
  "currency": "USD",
  "unit": "currency",
  "scope": "consolidated",
  "sourceId": "annual",
  "location": "Consolidated Statements of Income, Products revenue, FY2026 column",
  "mappingNote": "合成公司的产品与服务收入分别列报，两者构成合并收入",
  "documentValue": "600",
  "multiplier": "1000000",
  "documentFactId": "从 filing-facts.json 选择的真实 id",
  "dimensions": {"srt:ProductOrServiceAxis": "us-gaap:ProductMember"},
  "role": "leaf"
}
```

所有金额和倍率必须是十进制字符串，程序计算 `documentValue × multiplier`。若提供 `valueDecimal`，必须等于程序结果。`documentFactId` 需匹配所引用官方 HTML 的实际 inline XBRL 候选，实体、单位、上下文、维度和金额必须相同。没有可用 XBRL 时，以 `rawText` 保存原文准确数字 token，并提供 `location` 定位；括号/负号表示负值，不能把 API 缺标签解释为零。明确的“—”还需 `zeroInterpretation`，且原值只能为零。普通科目的 `key` 与 `normalized.json` 中目标一致；余额 `start=null`，期初余额用实际 beginningDate，期间项目用完整 start/end。

同一年度及科目只能有一个补充观察。与已选 SEC 金额冲突时，必须提供 `resolution: {supersedes: [原factId], reason: "具体版本判断"}`，新来源不得早于被替换来源。结构化候选本身有歧义时，使用 `resolution: {versions: 原缺口中的全部versions, reason: "逐项核验结论"}`。程序记录解决依据，不会自行平均或静默改选；仅判断格式及数值一致不代表财务真实性已获独立审计。

主营 `business` 条目：

```json
{
  "year": 2026,
  "dimension": "revenue_category",
  "definition": "合成公司的合并收入分为产品与服务",
  "facts": ["products-2026", "services-2026"],
  "complete": true,
  "comparableToPrevious": false,
  "comparabilityNote": "使用本期披露，跨年重分类仍待核验"
}
```

维度仅允许 reportable_segment、service_revenue、end_market、geographic_revenue、revenue_category。各行须非负、互斥且为叶子；总项、子项不能混加。程序检查重复底层来源、重复成员以及与收入的求和，但科目层级和定义仍需原文判断。只有行集被明确标完整且合计相等才允许完整构成图；否则保留 partial/conflict。重分类或可比性未核验时显式 false 并说明。

完整 CFO 的 `reconciliations` 条目：

```json
{
  "year": 2026,
  "facts": ["net-income-2026", "depreciation-2026", "其余全部原表调整id"],
  "review": {
    "complete": true,
    "sourceId": "annual",
    "location": "完整经营现金流调节表及FY2026数字列",
    "rows": ["net-income-2026", "depreciation-2026", "其余全部原表调整id"]
  }
}
```

以上是形状示意，不可直接以占位项构建。第一个观察必须是与报告一致的 `net_income`；其余 `key` 以 `cf_` 开头，使用现金流原表的实际符号和相同来源/年度，不能加入小计或端点 CFO。`review.rows` 与完整观察名单相同，逐行核对后才能填写 complete。只有审阅行集齐全且 Decimal 求和等于 CFO 才绘制闭合桥，不能使用残差作为调整。未完整审阅的已知调整仍以部分事实和缺口呈现。

可选的 `incomeFormations` 按财年记录完整非经营项目审阅，条目同样使用 `{year,facts,review:{complete,sourceId,location,rows}}`。引用的观察科目允许 `nonoperating_income`（独立总额）或互斥的 `interest_income,interest_expense,other_nonoperating_income,nonoperating_fx_gain_loss,investment_gain,equity_method_income`。总额不能与子项混加；利息费用的负向作用由固定函数计算。只有该财年有完整原表行集审阅，且营业利润加非经营项目等于税前利润、再减所得税等于净利润时，才生成完整净利润形成图；无审阅年份保留部分事实。额外税后项目或复杂权益法列报不猜测，保留缺口。

说明 `notes` 为 `{text,sourceId,location}`，用于保存带出处的可比性或会计判断；外部文本只渲染为文字，不执行脚本。无法核验的说明不要写成确定结论。

## 财务边界与验证

合并 ProfitLoss 与归母 NetIncomeLoss、含 NCI 权益与母公司权益分别选择；存在合并总额时不将总额与归母值加总。毛利、营业费用缺失时仅允许收入/成本/营业利润的明确算术小计，保留公式和输入，不生成现金流平衡项。现金流现金端点使用已披露的含受限现金合计，不用资产负债表普通现金替代；FX、CFO、CFI、CFF 任一缺失或勾稽不同就不画完整现金桥。

分析复用固定 Decimal 函数；V2 显式传递准备后的事实，并关闭 V1 历史补充。余额变化与现金调节分开；投资买卖不当资本支出，不做无证据的金融/经营分类或 NOA/RNOA。报告状态保守为 partial，有差异为 conflict，不将结构通过标为完整财务核验。

```bash
python3 -B -m unittest discover -s tests -v
python3 scripts/verify.py --browser
```

新增 V2 离线测试覆盖未知代码、52/53 周、少于五年、重述、身份/币种/IFRS/金融行业拒绝、缺受限现金端点、原始及标准化资料损坏、官方证据补充、重复行/总子项、原表行集审阅及覆盖保护。真实新公司接入与浏览器验收结果另见 [V2 验收记录](release.md)。
